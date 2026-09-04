"""Where each provider's own MCP server lives, and what it can be asked for.

Every one of these was probed on 2026-09-04 by following the MCP discovery
chain from an unauthenticated request: 401 with `WWW-Authenticate`, then
protected resource metadata, then authorization server metadata. All three
advertise a registration endpoint, which is what makes a session per client
possible without anyone registering an application first (D25).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteServer:
    provider: str
    url: str
    # Whether the authorization server will issue a client without a secret.
    # Where it will not, registration issues one at run time and it is stored
    # beside the tokens; it is never a value in this repository.
    public_client: bool
    note: str = ""


SERVERS: dict[str, RemoteServer] = {
    "cloudflare": RemoteServer(
        provider="cloudflare",
        url="https://mcp.cloudflare.com/mcp",
        public_client=True,
        note="registration confirmed working, token_endpoint_auth_method none",
    ),
    "vercel": RemoteServer(
        provider="vercel",
        url="https://mcp.vercel.com",
        public_client=True,
        note="registration confirmed: HTTP 201, token_endpoint_auth_method none, "
             "no secret, despite the authorization server metadata omitting "
             "`none` from token_endpoint_auth_methods_supported. Asked for "
             "client_secret_post and was given a public client, so the metadata "
             "understates it and only registering finds that out. Vercel states "
             "it supports only clients it has reviewed; whether that rejects a "
             "dynamically registered one at token exchange is still unverified",
    ),
    "resend": RemoteServer(
        provider="resend",
        url="https://mcp.resend.com/mcp",
        public_client=True,
        note="registration confirmed: HTTP 201, token_endpoint_auth_method none, "
             "no secret",
    ),
}


def server_for(provider: str) -> RemoteServer | None:
    """None rather than a guess. A provider with no MCP server is absent from
    this table, not represented by a plausible-looking URL (D11)."""
    return SERVERS.get(provider)
