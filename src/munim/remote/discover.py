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

import httpx

from munim.remote.servers import RemoteServer

INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2026-07-28", "capabilities": {},
               "clientInfo": {"name": "munim", "version": "0"}},
}
HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}


class NotAnMcpServer(Exception):
    """Whatever is at that URL did not answer like an MCP server."""


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
    try:
        tools = listed.json()["result"]["tools"]
    except Exception:
        return ""
    if not tools:
        return ""
    called = await http.post(url, headers=headers, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": tools[0]["name"], "arguments": {}}})
    return called.headers.get("www-authenticate", "") if called.status_code == 401 else ""


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

        if not challenge:
            # It answered a tool call without credentials. Either it is open, or
            # the credential is already in the URL, which is how Zoho works.
            return RemoteServer(
                provider=provider, url=url, public_client=True, auth="url",
                note="answered a tool call unauthenticated, so either it needs "
                     "nothing or the URL carries the credential")

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
