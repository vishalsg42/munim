"""Point Munim at any MCP server and work out what it needs.

The three providers built in are not the product. The product is a session per
client against a server that speaks MCP, and there is no reason that server has
to be one somebody else chose. An operator with their own, or with one of the
hundreds now published, should be able to add it by giving a URL.

What a URL cannot tell you is how it expects to be authenticated, and there are
at least three answers. This asks, by doing exactly what a client does: call it
without credentials and read the challenge. Everything here is a GET or an
unauthenticated call, so probing a server changes nothing on it.
"""

import json

import httpx

from munim.remote.servers import RemoteServer

INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2026-07-28", "capabilities": {},
               "clientInfo": {"name": "munim", "version": "0"}},
}
HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}


# Which tool the probe actually called, so a claim about the server can name
# the evidence behind it.
_tried: list[str] = []


class NotAnMcpServer(Exception):
    """Whatever is at that URL did not answer like an MCP server."""


def _payload(response: httpx.Response) -> dict | None:
    """The JSON-RPC body, however the transport framed it.

    Streamable HTTP may answer as plain JSON or as an SSE stream, and both are
    normal. Reading only the first meant a server replying in frames looked
    like one that had answered nothing, and the classifier then called it
    credential-free: the least safe way to be wrong.
    """
    try:
        return response.json()
    except ValueError:
        pass
    for line in response.text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except ValueError:
                continue
    return None


async def _challenge(http: httpx.AsyncClient, url: str) -> str:
    """The WWW-Authenticate a call produces, if any.

    Some servers challenge on `initialize`; Google's answer it happily and
    challenge on the first `tools/call`. Both are the same fact, arrived at
    differently, so this tries in that order rather than assuming either.
    """
    first = await http.post(url, json=INIT, headers=HEADERS)
    if first.status_code == 401:
        return first.headers.get("www-authenticate", "")

    session = first.headers.get("mcp-session-id")
    headers = dict(HEADERS)
    if session:
        headers["Mcp-Session-Id"] = session

    listed = await http.post(url, headers=headers,
                             json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    if listed.status_code == 401:
        return listed.headers.get("www-authenticate", "")
    body = _payload(listed)
    tools = ((body or {}).get("result") or {}).get("tools") or []
    if not tools:
        return ""
    # Prefer a tool that looks like it touches an account. Servers often expose
    # one or two public helpers, and judging the whole server by the first tool
    # in the list called GoDaddy credential-free on the strength of a domain
    # name suggester.
    def account_shaped(tool: dict) -> bool:
        name = tool["name"].lower()
        return any(word in name for word in
                   ("list", "get", "read", "account", "domains_list", "me"))

    candidates = [t for t in tools if account_shaped(t)] or tools
    _tried.clear()
    _tried.append(candidates[0]["name"])

    called = await http.post(url, headers=headers, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": candidates[0]["name"], "arguments": {}}})
    if called.status_code == 401:
        return called.headers.get("www-authenticate", "")

    # A server may refuse inside the body rather than with a status. That is
    # still a refusal, and treating it as "needs nothing" is the least safe way
    # to be wrong.
    body = _payload(called) or {}
    text = json.dumps(body).lower()
    if any(word in text for word in
           ("unauthorized", "unauthenticated", "not authenticated",
            "missing api key", "invalid token", "forbidden")):
        return "in-body"
    return ""


async def probe(url: str, name: str = "") -> RemoteServer:
    """What this server is and how it wants to be authenticated."""
    provider = name or httpx.URL(url).host.split(".")[0]

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
        try:
            hello = await http.post(url, json=INIT, headers=HEADERS)
        except httpx.HTTPError as exc:
            raise NotAnMcpServer(f"{url} did not answer: {type(exc).__name__}") from exc

        if hello.status_code not in (200, 401):
            raise NotAnMcpServer(
                f"{url} answered HTTP {hello.status_code} to an MCP initialize, "
                f"so it is probably not an MCP server")

        challenge = await _challenge(http, url)

        if challenge == "in-body":
            return RemoteServer(
                provider=provider, url=url, public_client=False, auth="app",
                note="refused a tool call in the response body rather than with "
                     "a 401, so it wants a credential this could not discover. "
                     "Check its own documentation for what")

        if not challenge:
            # One tool answered without credentials. That is not the same as the
            # server needing none: many expose a public helper or two beside
            # everything else. Say which tool was tried so the claim can be
            # checked rather than believed.
            tried = _tried[0] if _tried else "a tool"
            return RemoteServer(
                provider=provider, url=url, public_client=True, auth="url",
                note=f"{tried!r} answered without credentials. Either the server "
                     f"needs none, the URL carries the credential, or that one "
                     f"tool is public while the rest are not: only using it "
                     f"will say which")

        if 'resource_metadata="' not in challenge:
            return RemoteServer(
                provider=provider, url=url, public_client=False, auth="app",
                note=f"challenged without protected resource metadata: "
                     f"{challenge[:80]}")

        meta_url = challenge.split('resource_metadata="')[1].split('"')[0]
        prm = (await http.get(meta_url)).json()
        issuer = prm.get("authorization_servers", [""])[0]

        metadata = {}
        for path in ("/.well-known/oauth-authorization-server",
                     "/.well-known/openid-configuration"):
            answer = await http.get(issuer.rstrip("/") + path)
            if answer.status_code == 200:
                metadata = answer.json()
                break

        registers = bool(metadata.get("registration_endpoint"))
        methods = metadata.get("token_endpoint_auth_methods_supported", [])
        public = "none" in methods

        if registers:
            return RemoteServer(
                provider=provider, url=url, public_client=public, auth="registers",
                note=f"confirmed: registers clients at "
                     f"{metadata['registration_endpoint']}, auth methods {methods}")

        return RemoteServer(
            provider=provider, url=url, public_client=public, auth="app",
            register_at=issuer,
            note=f"{issuer} advertises no registration endpoint, so an "
                 f"application has to be registered by hand. Auth methods {methods}")
