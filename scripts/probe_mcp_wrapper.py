"""Throwaway probe: can Munim hold two accounts on one remote MCP server at once?

This is the question D25 turns on and no documentation answers it. If two OAuth
sessions to the same provider MCP server can coexist inside one process, then
wrapping the providers' own servers keeps the cross-client read that the whole
project rests on, and the adapters can go. If they cannot, wrapping is
mcpwarden: multi-account by registering N servers in the coding agent, with no
way to ask a question that spans them.

Nothing here is production code. It writes its tokens to a scratch directory,
not the keychain, and it never touches a client's records: it lists tools and
stops.

    uv run python scripts/probe_mcp_wrapper.py "Acme Ltd" "Kloudfirst"

Each name opens a browser once. Sign in as a *different* account each time,
which is the entire point.
"""

import asyncio
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVER = "https://mcp.cloudflare.com/mcp"
CALLBACK_PORT = 8976
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/oauth/callback"
SCRATCH = Path("/tmp/munim-mcp-probe")


class FileStorage(TokenStorage):
    """One directory per client. The point of the probe is that these do not
    collide: two accounts, two token sets, alive at the same time."""

    def __init__(self, client: str) -> None:
        self._dir = SCRATCH / client.replace(" ", "_")
        self._dir.mkdir(parents=True, exist_ok=True)

    async def get_tokens(self) -> OAuthToken | None:
        path = self._dir / "tokens.json"
        return OAuthToken(**json.loads(path.read_text())) if path.exists() else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        (self._dir / "tokens.json").write_text(tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        path = self._dir / "client.json"
        return (OAuthClientInformationFull(**json.loads(path.read_text()))
                if path.exists() else None)

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        (self._dir / "client.json").write_text(info.model_dump_json())


def _wait_for_callback() -> tuple[str, str | None]:
    """Serve until the callback arrives, ignoring anything else that hits the
    port. One stray favicon request must not cost a login."""
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/oauth/callback":
                self.send_response(404); self.end_headers(); return
            params = parse_qs(parsed.query)
            result["code"] = params.get("code", [""])[0]
            result["state"] = params.get("state", [""])[0]
            body = b"<!doctype html><p style='font:16px sans-serif'>Connected. Close this tab."
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
    server.timeout = 0.5
    for _ in range(600):
        if result:
            break
        server.handle_request()
    server.server_close()
    if not result:
        raise TimeoutError("no callback")
    return result["code"], result["state"] or None


async def connect(client: str):
    """One MCP session, authenticated as whoever signs in."""
    storage = FileStorage(client)

    async def open_browser(url: str) -> None:
        print(f"\n  [{client}] sign in as this client's account:\n  {url}\n")
        webbrowser.open(url)

    async def wait() -> tuple[str, str | None]:
        return await asyncio.to_thread(_wait_for_callback)

    auth = OAuthClientProvider(
        server_url=SERVER,
        client_metadata=OAuthClientMetadata(
            client_name="Munim (probe)",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        ),
        storage=storage,
        redirect_handler=open_browser,
        callback_handler=wait,
    )
    return auth


async def tools_for(client: str) -> tuple[str, list[str]]:
    auth = await connect(client)
    async with streamablehttp_client(SERVER, auth=auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return client, [t.name for t in tools.tools]


async def main() -> int:
    clients = sys.argv[1:] or ["Client A", "Client B"]
    print(f"Probing {SERVER}")
    print(f"Clients: {', '.join(clients)}")
    print("Each opens a browser once. Sign in as a DIFFERENT account each time.\n")

    # Sequential for the sign-in, because two browser windows at once is not a
    # test of anything except patience.
    sessions = []
    for name in clients:
        sessions.append(await tools_for(name))

    print("\n--- both sessions, held at the same time ---")
    for name, tools in sessions:
        print(f"{name}: {len(tools)} tools -> {', '.join(tools[:6])}")

    print("\nTokens on disk, one directory per client:")
    for d in sorted(SCRATCH.iterdir()):
        print("   ", d)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
