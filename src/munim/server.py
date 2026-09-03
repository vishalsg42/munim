"""The MCP surface.

Transport and tool registration only - no provider logic lives here.

Two rules hold across every tool (docs/DECISIONS.md D5, D6):
  - No ambient client. Anything touching a provider takes `client` explicitly.
  - No credential ever crosses this boundary. No tool returns a token.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from munim.container import Container, KeychainBackend
from munim.env import load as load_env
from munim.registry import Registry


def build_server(backend=None, registry=None) -> FastMCP:
    server = FastMCP("munim")
    backend = backend or KeychainBackend()
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")

    @server.tool()
    def list_clients() -> list[dict]:
        """List the client containers that are registered."""
        return [
            {"client": r.name, "domain": r.domain, "providers": r.providers}
            for r in registry.clients()
        ]

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
    # The MCP server is a subprocess spawned by the coding agent and does not
    # inherit the operator's shell, so the model key has to come from .env here.
    load_env()
    build_server().run()


if __name__ == "__main__":
    main()
