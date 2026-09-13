"""A client's REST API, reached through the session they already have.

Two credentials existed for the same account and only one of them could repair
anything. `munim connect acme cloudflare` files an OAuth session; `mailplan`
reaches Cloudflare's REST API, which refuses that session's token, so it asked
for a second credential: a pasted API key. Measured 2026-09-07, that refusal is
real and per provider, and `RemoteServer.rest_takes_session` records it: Vercel
returns 200 to a session token, Cloudflare 400, Resend 403.

What both of them do accept is that session at their own MCP server, and both
servers can reach the endpoints the mail repair needs. Cloudflare's `execute`
takes a JavaScript arrow function calling `cloudflare.request({method, path,
body})`, which is the whole REST API. Resend publishes a tool per endpoint.

So this is a transport rather than a rewrite. `Container.http` hands the
adapters an httpx client whose requests leave as MCP tool calls, and
`adapters/cloudflare.py` and `adapters/resend.py` do not know. The
read-before-write on `(type, name)`, the SPF merge, the refusal to append
beside an existing record, and every test over them go on being true, which is
the only reason this is worth doing two days from a deadline.

**The model is not in this path.** The JavaScript is written here, fixed, with
the request serialised into it as data. The repairing agent still sees two
tools that take no arguments, and still cannot say what to write or whether it
was allowed to.
"""

import json

import httpx

from munim.remote.passthrough import call_tool
from munim.remote import resendtext

# Where each provider's REST base ends, so a request's path can be turned back
# into the path the provider's own API names. `http.get("/zones")` against a
# base of `.../client/v4` arrives here as `/client/v4/zones`.
BASE_PATH = {"cloudflare": "/client/v4", "resend": ""}


def _api_path(provider: str, path: str) -> str:
    prefix = BASE_PATH.get(provider, "")
    if prefix and path.startswith(prefix):
        return path[len(prefix):] or "/"
    return path


def _body(request: httpx.Request):
    raw = request.content
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


def _answer(payload: dict, status: int, request: httpx.Request) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


class OverMCP(httpx.AsyncBaseTransport):
    """Shared plumbing. One MCP session per request, opened by `call_tool`.

    A session per request is not free, and it is what makes the token freshness
    somebody else's problem: `session_for` refreshes, and nothing here holds a
    token or could log one.
    """

    provider = ""

    def __init__(self, client: str, *, keyring=None, log=None) -> None:
        self._client = client
        self._keyring = keyring
        self._log = log

    async def _call(self, tool: str, arguments: dict) -> dict:
        return await call_tool(self._client, self.provider, tool, arguments,
                               keyring=self._keyring, log=self._log,
                               stage="api")


class CloudflareOverMCP(OverMCP):
    """Every request as one `execute` call.

    `execute` returns Cloudflare's own response object, `success`/`errors`/
    `result`, which is exactly what `adapters/cloudflare.py` already reads. The
    adapter cannot tell the difference and neither can its tests.
    """

    provider = "cloudflare"

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        options = {"method": request.method,
                   "path": _api_path("cloudflare", request.url.path)}
        query = dict(request.url.params)
        if query:
            options["query"] = query
        body = _body(request)
        if body is not None:
            options["body"] = body

        # ensure_ascii so the serialised request is plain ASCII JSON, which is
        # valid JavaScript source. A domain with a non-ASCII character would
        # otherwise put a raw code point inside a program.
        code = "async () => cloudflare.request(%s)" % json.dumps(
            options, ensure_ascii=True)

        said = await self._call("execute", {"code": code})
        answer = said.get("result")
        if said.get("failed") or not isinstance(answer, dict):
            return _answer(
                {"success": False,
                 "errors": [{"code": 0, "message": _said_what(answer)}],
                 "result": None},
                502, request)
        return _answer(answer, int(answer.get("status") or 200), request)


class ResendOverMCP(OverMCP):
    """One tool per endpoint, and prose read back into the REST shape.

    The four endpoints `mailplan` uses and the four tools Resend publishes are
    one to one. What is not one to one is the answer: Resend's MCP server
    writes for a person, so `resendtext` reads it back and refuses anything it
    cannot recognise rather than handing a half-parsed DKIM key to something
    that publishes DNS.
    """

    provider = "resend"

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = _api_path("resend", request.url.path).rstrip("/")
        parts = [p for p in path.split("/") if p]
        method = request.method.upper()

        try:
            if parts == ["domains"] and method == "GET":
                said = await self._call("list-domains", {})
                return _answer(
                    {"data": resendtext.domains(resendtext.joined(said.get("result")))},
                    200, request)

            if parts == ["domains"] and method == "POST":
                body = _body(request) or {}
                asked = {"name": body.get("name", "")}
                if body.get("region"):
                    asked["region"] = body["region"]
                said = await self._call("create-domain", asked)
                return _answer(
                    resendtext.one(resendtext.joined(said.get("result"))), 200, request)

            if len(parts) == 2 and parts[0] == "domains" and method == "GET":
                said = await self._call("get-domain", {"id": parts[1]})
                return _answer(
                    resendtext.one(resendtext.joined(said.get("result"))), 200, request)

            if len(parts) == 3 and parts[0] == "domains" \
                    and parts[2] == "verify" and method == "POST":
                said = await self._call("verify-domain", {"id": parts[1]})
                text = resendtext.joined(said.get("result"))
                found = resendtext.domains(text)
                status = found[0]["status"] if found else "pending"
                return _answer({"id": parts[1], "status": status}, 200, request)
        except resendtext.ResendTextError as exc:
            # A 502 with a message, because `Resend._ok` turns a 4xx or 5xx
            # into a ResendError carrying `message`, and the operator needs the
            # text that failed rather than a traceback.
            return _answer({"message": str(exc)}, 502, request)

        return _answer(
            {"message": f"no Resend MCP tool covers {method} {path}. Reaching "
                        f"this endpoint needs a pasted API key: "
                        f'munim connect "<client>" resend --token'},
            501, request)


def _said_what(answer) -> str:
    if isinstance(answer, dict):
        return str(answer.get("error") or answer.get("message") or answer)[:300]
    return str(answer)[:300]


TRANSPORTS = {"cloudflare": CloudflareOverMCP, "resend": ResendOverMCP}


def transport_for(provider: str, client: str, *, keyring=None, log=None):
    """A transport for this provider, or None where there is no route.

    None is the honest answer for Vercel: its REST API takes the session token
    directly, so `Container` borrows it and never comes here.
    """
    made = TRANSPORTS.get(provider)
    return None if made is None else made(client, keyring=keyring, log=log)
