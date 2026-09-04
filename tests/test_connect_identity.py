"""A session is filed under the client's id, never under their label.

The id is the identity and the name is a label the operator can change at any
time (D26). Credentials filed under the label make a rename a data migration,
and a half-done one leaves a client that looks connected and is not.

That was still true here after the rest of the codebase moved to ids. A real
`munim connect Kloudfirst cloudflare` stored its tokens under "Kloudfirst" and
its account marker under the id, so the two halves of one session lived in
different places. Nothing looked wrong, because a migration ran on every
command and quietly moved the tokens to the id before anything read them. The
bug was only visible as a stray "moved Kloudfirst: cloudflare session" line on
the next command, after a connect that had just succeeded.
"""

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry
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


def _fake_login(monkeypatch, ring, account, seen):
    """Stand in for the browser round trip, storing a session the way the real
    one does: under whatever key it was handed."""
    async def connect_and_identify(client, provider, **kw):
        seen.append(client)
        store = KeychainTokenStorage(client, provider, ring)
        ring.set_password(store._service("tokens"), client,
                          '{"access_token": "t", "token_type": "Bearer"}')
        return ["a", "b", "c"], account

    monkeypatch.setattr("munim.remote.session.connect_and_identify",
                        connect_and_identify)


def test_a_named_client_is_connected_under_its_id(world, monkeypatch):
    """The regression: the label went to the store instead of the id."""
    registry, ring = world
    registry.add(ClientRecord(name="Kloudfirst"))
    record = registry.get("Kloudfirst")
    seen = []
    _fake_login(monkeypatch, ring, "kloudfirst@gmail.com's Account", seen)

    assert cli.connect_via_mcp("Kloudfirst", "cloudflare") == 0

    assert seen == [record.id], "the session was opened under the label"
    assert KeychainTokenStorage(record.id, "cloudflare", ring)._read("tokens")
    assert not KeychainTokenStorage("Kloudfirst", "cloudflare", ring)._read("tokens")


def test_the_session_survives_a_rename(world, monkeypatch):
    """The reason ids exist. A label change must not touch a credential."""
    registry, ring = world
    registry.add(ClientRecord(name="Kloudfirst"))
    record = registry.get("Kloudfirst")
    _fake_login(monkeypatch, ring, "kloudfirst@gmail.com's Account", [])
    cli.connect_via_mcp("Kloudfirst", "cloudflare")

    registry.rename("Kloudfirst", "Kloudfirst Technologies")

    store = KeychainTokenStorage(record.id, "cloudflare", ring)
    assert store._read("tokens"), "a rename orphaned the session"
    assert store.account() == "kloudfirst@gmail.com's Account"


def test_tokens_and_account_marker_land_together(world, monkeypatch):
    """They were written to two different keys, which is how one of them can
    go missing without the other noticing."""
    registry, ring = world
    registry.add(ClientRecord(name="Kloudfirst"))
    record = registry.get("Kloudfirst")
    _fake_login(monkeypatch, ring, "kloudfirst@gmail.com's Account", [])

    cli.connect_via_mcp("Kloudfirst", "cloudflare")

    store = KeychainTokenStorage(record.id, "cloudflare", ring)
    assert store._read("tokens") and store.account()


def test_an_auto_named_client_is_filed_under_its_new_id(world, monkeypatch):
    """Connecting without a name creates the client, so the id exists only
    after the provider answers. The session still has to end up under it."""
    registry, ring = world
    _fake_login(monkeypatch, ring, "kloudfirst@gmail.com's Account", [])

    assert cli.connect_via_mcp(None, "cloudflare") == 0

    record = registry.get("kloudfirst@gmail.com's Account")
    store = KeychainTokenStorage(record.id, "cloudflare", ring)
    assert store._read("tokens"), "the auto-named session is not under the id"
    assert not KeychainTokenStorage(record.name, "cloudflare", ring)._read("tokens")
    assert not KeychainTokenStorage(cli.PROVISIONAL, "cloudflare", ring)._read("tokens")


def test_connecting_an_unregistered_name_registers_it(world, monkeypatch):
    """Otherwise the session has no id to be filed under, which is how it ended
    up under a label in the first place."""
    registry, ring = world
    _fake_login(monkeypatch, ring, "acme@example's Account", [])

    assert cli.connect_via_mcp("Acme", "cloudflare") == 0

    record = registry.get("Acme")
    assert KeychainTokenStorage(record.id, "cloudflare", ring)._read("tokens")
