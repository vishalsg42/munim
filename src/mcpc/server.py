"""The MCP surface.

Transport and tool registration only - no provider logic lives here.

Two rules hold across every tool (docs/DECISIONS.md D5, D6):
  - No ambient client. Anything touching a provider takes `client` explicitly.
  - No credential ever crosses this boundary. No tool returns a token.
"""

from mcp.server.fastmcp import FastMCP

from mcpc.container import Container, KeychainBackend


def build_server(backend=None) -> FastMCP:
    server = FastMCP("mcpc")
    backend = backend or KeychainBackend()

    @server.tool()
    def list_clients() -> list[str]:
        """List the client containers that are registered."""
        return []

    @server.tool()
    def client_status(client: str) -> dict:
        """Report which providers are connected for one client.

        Never returns a credential - only whether one is present.
        """
        container = Container(client, backend)
        connected = []
        for provider in ("vercel", "cloudflare", "resend", "supabase"):
            try:
                container.credential(provider)
            except Exception:
                continue
            connected.append(provider)
        return {"client": container.client, "connected": connected}

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
