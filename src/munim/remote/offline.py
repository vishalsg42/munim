"""Ask for a refresh token where the authorization server offers one.

Connecting Vercel produced a session with no refresh token and an hour of life.
An hour later it was dead and the only way back was another browser login. That
is not Vercel's doing: Vercel documents that `offline_access` issues a refresh
token valid for 30 days with rotation, and its authorization server advertises
the scope.

What happens is that MCP's scope selection strategy takes the scope from the
resource's `scopes_supported`, and Vercel's resource correctly omits
`offline_access` from that list, so it is never asked for.

MCP SEP-2207, "OIDC-Flavored Refresh Token Guidance", status Final, is written
about this exact failure. It says a resource SHOULD NOT advertise
`offline_access` in its protected resource metadata, and that a client MAY add
it when the authorization server's own metadata advertises it. So this is not
working around the specification; it is the part of the specification the
pinned SDK has not shipped.

The Python SDK implements it from 2.0.0. strands-agents pins mcp<2.0.0, and
strands is the requirement this project is built on, so the version cannot be
raised yet.

**Delete this module when that pin lifts.** The SDK's own implementation is in
`mcp/client/auth/utils.py::get_client_metadata_scopes`, takes the same three
inputs and applies the same two conditions, and having both would mean two
places to be wrong.
"""


def with_offline_access(scope, authorization_server_metadata, grant_types):
    """`scope` plus offline_access, where SEP-2207 says it is allowed.

    Both conditions matter and both are the SEP's:

      - the authorization server advertises it. Asking for a scope a server
        does not define is a rejected authorisation, and it fails at the
        consent screen in front of the operator.
      - the client declares the refresh_token grant. A refresh token you have
        no grant to exchange is a longer-lived credential than you can use.

    A `None` scope is returned unchanged. The strategy chose to omit the
    parameter, and turning that into a bare "offline_access" would narrow a
    request that was deliberately open.
    """
    if not scope:
        return scope

    supported = getattr(authorization_server_metadata, "scopes_supported", None)
    if not supported or "offline_access" not in supported:
        return scope
    if "refresh_token" not in (grant_types or ()):
        return scope

    asked = scope.split()
    if "offline_access" in asked:
        return scope
    return " ".join([*asked, "offline_access"])
