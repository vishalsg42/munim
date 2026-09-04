"""Some MCP servers authenticate with an API key in a header.

Munim knew three ways in: a provider that issues a client on demand, one that
needs an application registered by hand, and one whose URL carries the
credential. A fourth was in front of us the whole time. Claude Code connects to
Google's Stitch server like this:

    stitch: https://stitch.googleapis.com/mcp
    Headers: X-Goog-Api-Key: AQ.Ab8RN6...

No OAuth, no consent screen, no test users, no seven day expiry. Munim's table
described that same server as needing a registered Google Cloud OAuth
application, which is a much higher bar for something that takes a header, and
the README claimed you could point Munim at any MCP server while it had no way
to send one.
"""

import pytest

from munim.remote.servers import AUTH_KINDS, RemoteServer, SERVERS


class Backend:
    def __init__(self, store=None): self.store = store or {}
    def get(self, client, provider): return self.store.get((client, provider))
    def set(self, client, provider, secret): self.store[(client, provider)] = secret


def test_header_is_an_auth_kind():
    assert "header" in AUTH_KINDS


def test_a_header_server_records_which_header():
    """"Send the key" is not enough to act on. X-Goog-Api-Key and
    Authorization are not interchangeable, and guessing gets a 401 that looks
    like a bad credential."""
    server = RemoteServer(provider="acme", url="https://mcp.acme.com/mcp",
                          public_client=False, auth="header",
                          header="X-Acme-Key")
    assert server.header == "X-Acme-Key"


def test_a_header_server_needs_no_browser():
    """Like the url kind: there is nothing to authorise, so `ready` means the
    operator has a key rather than that setup is zero."""
    server = RemoteServer(provider="acme", url="https://mcp.acme.com/mcp",
                          public_client=False, auth="header",
                          header="X-Acme-Key")
    assert server.auth == "header"
    assert not server.ready


def test_the_key_is_read_from_the_keychain():
    from munim.remote.session import headers_for

    backend = Backend({("c_abc", "stitch"): "a-real-key"})
    assert headers_for("c_abc", "stitch", backend) == {"X-Goog-Api-Key": "a-real-key"}


def test_a_missing_key_says_what_to_run():
    from munim.remote.session import NeedsLogin, headers_for

    with pytest.raises(NeedsLogin, match="--token"):
        headers_for("c_abc", "stitch", Backend())


def test_a_provider_that_is_not_header_authed_sends_none():
    from munim.remote.session import headers_for

    assert headers_for("c_abc", "cloudflare", Backend()) is None


def test_stitch_is_recorded_as_header_authed():
    """It was recorded as needing an application registered by hand, which sent
    people through ten minutes of Google Cloud for a server that takes a key."""
    assert SERVERS["stitch"].auth == "header"
    assert SERVERS["stitch"].header == "X-Goog-Api-Key"
