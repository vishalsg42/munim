"""A client that logged in through the browser is connected.

Saying that out loud because for a while it was not true anywhere a person
would look. `munim connect Kloudfirst cloudflare` completed, stored a session,
and then `munim clients` said "nothing connected" and the `list_clients` MCP
tool reported an empty list. The credential was fine; every report of it was
wrong, which is worse than a missing credential because it sends the operator
to reconnect an account that is already connected.

The cause was that "connected" was asked as "is there an API key", and OAuth
sessions are a different keychain entry. `doctor` had already been taught the
difference. Nothing else had, so the answer lives in one place now.
"""

import json

from mcp.shared.auth import OAuthToken

from munim.connected import connections, describe
from munim.remote.storage import KeychainTokenStorage


class FakeKeyring:
    """Stands in for the OS keychain, for both kinds of entry."""

    def __init__(self):
        self.store = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


class FakeBackend:
    """The pasted-key store, which is a plain string per (client, provider)."""

    def __init__(self, ring):
        self._ring = ring

    def get(self, client, provider):
        return self._ring.get_password(f"munim:{provider}", client)

    def set(self, client, provider, secret):
        self._ring.set_password(f"munim:{provider}", client, secret)


async def _log_in(ring, client, provider):
    await KeychainTokenStorage(client, provider, ring).set_tokens(
        OAuthToken(access_token="live-session", token_type="Bearer")
    )


async def test_a_browser_login_counts_as_connected():
    """The regression. This is the whole bug in four lines."""
    ring = FakeKeyring()
    await _log_in(ring, "c_abc", "cloudflare")

    keys, sessions = connections("c_abc", FakeBackend(ring), ring)

    assert sessions == ["cloudflare"]
    assert keys == []
    assert describe("c_abc", FakeBackend(ring), ring) == "cloudflare (mcp)"


async def test_a_pasted_key_still_counts():
    ring = FakeKeyring()
    FakeBackend(ring).set("c_abc", "vercel", "a-real-token")

    keys, sessions = connections("c_abc", FakeBackend(ring), ring)

    assert keys == ["vercel"]
    assert sessions == []


async def test_both_routes_are_reported_separately():
    """They are not the same thing and the report should not merge them: one
    is a credential Munim calls with, the other is a session with someone
    else's server, and they fail in different ways."""
    ring = FakeKeyring()
    FakeBackend(ring).set("c_abc", "vercel", "a-real-token")
    await _log_in(ring, "c_abc", "cloudflare")

    keys, sessions = connections("c_abc", FakeBackend(ring), ring)

    assert keys == ["vercel"]
    assert sessions == ["cloudflare"]
    assert describe("c_abc", FakeBackend(ring), ring) == "vercel · cloudflare (mcp)"


async def test_nothing_stored_reads_as_nothing_connected():
    ring = FakeKeyring()

    assert connections("c_abc", FakeBackend(ring), ring) == ([], [])
    assert describe("c_abc", FakeBackend(ring), ring) == "nothing connected"


async def test_one_clients_session_is_not_another_clients():
    """The multi-account claim, asked of the status reader rather than the
    store. A status line that leaked across clients would be the same failure
    D5 exists to prevent, just rendered instead of executed."""
    ring = FakeKeyring()
    await _log_in(ring, "c_one", "cloudflare")

    assert connections("c_two", FakeBackend(ring), ring) == ([], [])
