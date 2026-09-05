"""What a client is actually connected to.

There are two ways a client can be connected and they are not the same thing:

  - an API credential Munim calls the provider with, pasted in via
    `munim connect --token`, and
  - a session with the provider's own MCP server, obtained by logging in
    through the browser.

They live in different keychain entries, so asking for one does not find the
other. Everything except `doctor` asked only for the key, which meant a client
that had just finished a browser login was reported as connected to nothing by
`munim clients`, by the `list_clients` MCP tool, and by `client_status`.

That is worse than a missing credential. A missing credential fails loudly at
the call; this sends the operator to reconnect an account that is already
connected, and tells an agent it cannot do work it can in fact do.

`doctor` was taught the difference and nothing else was, so the answer lives
here now and there is one place left to get it wrong.
"""

from munim.container import KeychainBackend
from munim.remote.servers import SERVERS
from munim.remote.storage import KeychainTokenStorage

# Providers Munim holds a callable credential for. Not the same set as SERVERS:
# a provider can offer an MCP server without Munim having an adapter, and an
# adapter can exist for a provider that ships no MCP server.
KEY_PROVIDERS = ("cloudflare", "vercel", "resend")


def connections(client_id, backend=None, keyring_module=None):
    """(api keys, mcp sessions) for one client, each sorted.

    Takes a client id rather than a name, because credentials are filed by
    identity: passing a label here would report a renamed client as empty.
    """
    backend = backend or KeychainBackend()

    keys = [p for p in KEY_PROVIDERS if backend.get(client_id, p) is not None]
    sessions = [
        p for p in sorted(SERVERS)
        # Tokens first, then the endpoint. Zoho authenticates by URL and stores
        # an endpoint and no tokens at all, so a tokens-only test reported a
        # connected Zoho client as holding nothing: `munim clients` said
        # "nothing connected" for a live session. agent/within.py already asked
        # both questions; this was the one place still asking the narrow one.
        #
        # Deliberately not `holds()`, which reads all four kinds. This runs once
        # per client per provider on every listing, so it is one keychain read
        # in the common case and two for Zoho. Using `holds()` here took the
        # suite from 47 seconds to 177.
        if (KeychainTokenStorage(client_id, p, keyring_module)._read("tokens")
            or KeychainTokenStorage(client_id, p, keyring_module).endpoint())
    ]
    return keys, sessions


def describe(client_id, backend=None, keyring_module=None) -> str:
    """One line for a person. Sessions are marked so the two are told apart."""
    keys, sessions = connections(client_id, backend, keyring_module)

    parts = []
    if keys:
        parts.append(", ".join(keys))
    if sessions:
        parts.append(", ".join(f"{p} (mcp)" for p in sessions))
    return " · ".join(parts) or "nothing connected"


def reachable(client_id, backend=None, keyring_module=None) -> list[str]:
    """Every provider this client can reach, by either route, deduplicated.

    For callers that only care whether the work can be done: an agent deciding
    whether to attempt a Cloudflare call does not care which of the two ways
    the credential arrived.
    """
    keys, sessions = connections(client_id, backend, keyring_module)
    return sorted(set(keys) | set(sessions))
