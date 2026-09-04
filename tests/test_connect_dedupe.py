"""One provider account must not become two clients.

It did, here, on a real machine: two Cloudflare accounts arrived auto-named
while the same clients already existed under human names, and the result was
four clients for two accounts. A call could then have gone to either, which is
the split identity D5 exists to prevent, and `munim merge` had to be written to
repair it.

The repair is not the fix. The fix is that a session remembers which account it
turned out to be, so connecting one that is already held is recognised.
"""

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry
from munim.remote.accounts import holder_of
from munim.remote.storage import KeychainTokenStorage


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


@pytest.fixture
def world(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "r.json")
    ring = Ring()
    monkeypatch.setattr(cli, "_registry", lambda: registry)
    monkeypatch.setattr("munim.remote.storage.keyring", ring)
    return registry, ring


def _connected(ring, client_id, provider, account):
    store = KeychainTokenStorage(client_id, provider, ring)
    ring.set_password(store._service("tokens"), client_id,
                      '{"access_token": "t", "token_type": "Bearer"}')
    store.remember_account(account)


def test_the_holder_of_an_account_is_findable(world):
    registry, ring = world
    registry.add(ClientRecord(name="Balaji Roofings"))
    record = registry.get("Balaji Roofings")
    _connected(ring, record.id, "cloudflare", "acct@example's Account")

    found = holder_of(registry, "cloudflare", "acct@example's Account")
    assert found is not None and found.id == record.id


def test_a_client_does_not_report_itself(world):
    """Re-connecting a client to the account it already has is a refresh, not
    a clash."""
    registry, ring = world
    registry.add(ClientRecord(name="Balaji Roofings"))
    record = registry.get("Balaji Roofings")
    _connected(ring, record.id, "cloudflare", "acct@example's Account")

    assert holder_of(registry, "cloudflare", "acct@example's Account",
                     exclude=record.id) is None


def test_an_unknown_account_has_no_holder(world):
    registry, ring = world
    registry.add(ClientRecord(name="Balaji Roofings"))
    assert holder_of(registry, "cloudflare", "somebody-else") is None


def test_accounts_do_not_leak_across_providers(world):
    """The same string under a different provider is a different fact."""
    registry, ring = world
    registry.add(ClientRecord(name="Acme"))
    record = registry.get("Acme")
    _connected(ring, record.id, "cloudflare", "shared-name")
    assert holder_of(registry, "vercel", "shared-name") is None


def test_naming_a_second_client_for_a_held_account_is_refused(world, monkeypatch):
    """The case that actually happened, from the other direction."""
    registry, ring = world
    registry.add(ClientRecord(name="Balaji Roofings"))
    registry.add(ClientRecord(name="Balaji Roofings Duplicate"))
    held = registry.get("Balaji Roofings")
    _connected(ring, held.id, "cloudflare", "acct@example's Account")

    async def pretend(client, provider, **kwargs):
        return ["docs", "search", "execute"], "acct@example's Account"
    monkeypatch.setattr("munim.remote.session.connect_and_identify", pretend)

    code = cli.connect_via_mcp("Balaji Roofings Duplicate", "cloudflare")
    assert code == 2, "a second client was allowed to hold one account"
