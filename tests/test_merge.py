"""Folding one client into another, and refusing to when it would lose a login.

Connecting an account already known under another label makes a second client,
and then a call could go to either. Merging is the repair. The interesting part
is the refusal: when both sides hold the same provider they are two different
accounts rather than one client recorded twice, and picking a winner silently
drops a credential for a live account.
"""

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry, UnknownClient


class Keys:
    def __init__(self): self.s = {}
    def get(self, c, p): return self.s.get((c, p))
    def set(self, c, p, v): self.s[(c, p)] = v


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


@pytest.fixture
def world(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "r.json")
    keys, ring = Keys(), Ring()
    monkeypatch.setattr(cli, "_registry", lambda: registry)
    monkeypatch.setattr("munim.container.KeychainBackend", lambda: keys)
    monkeypatch.setattr("munim.remote.storage.vault", ring)
    return registry, keys, ring


def _session(ring, client_id, provider="cloudflare"):
    from munim.remote.storage import KeychainTokenStorage
    store = KeychainTokenStorage(client_id, provider, ring)
    ring.set_password(store._service("tokens"), client_id,
                      '{"access_token": "t", "token_type": "Bearer"}')


def _endpoint(ring, client_id, provider="zoho", url="https://example.test/mcp/x"):
    """A session that is an address and nothing else.

    What a per-installation provider looks like between `--url` being recorded
    and the login finishing, and what every tokens-only test read as empty.
    """
    from munim.remote.storage import KeychainTokenStorage
    KeychainTokenStorage(client_id, provider, ring).remember_endpoint(url)


def test_a_merge_carries_the_credentials(world):
    registry, keys, ring = world
    registry.add(ClientRecord(name="Acme Account"))
    registry.add(ClientRecord(name="Acme Ltd", domain="acme.example"))
    source, target = registry.get("Acme Account"), registry.get("Acme Ltd")
    _session(ring, source.id)

    assert cli.merge("Acme Account", "Acme Ltd") == 0

    from munim.remote.storage import KeychainTokenStorage
    assert KeychainTokenStorage(target.id, "cloudflare", ring)._read("tokens")
    assert KeychainTokenStorage(source.id, "cloudflare", ring)._read("tokens") is None
    with pytest.raises(UnknownClient):
        registry.get("Acme Account")


def test_a_merge_that_would_drop_a_login_is_refused(world):
    """Both holding cloudflare means two accounts, not one client twice."""
    registry, keys, ring = world
    registry.add(ClientRecord(name="one"))
    registry.add(ClientRecord(name="two"))
    _session(ring, registry.get("one").id)
    _session(ring, registry.get("two").id)

    assert cli.merge("one", "two") == 2
    assert {c.name for c in registry.clients()} == {"one", "two"}


def test_a_domain_moves_only_into_an_empty_one(world):
    registry, keys, ring = world
    registry.add(ClientRecord(name="src", domain="from.example"))
    registry.add(ClientRecord(name="dst"))
    cli.merge("src", "dst")
    assert registry.get("dst").domain == "from.example"


def test_forget_refuses_while_anything_is_held(world):
    registry, keys, ring = world
    registry.add(ClientRecord(name="holder"))
    _session(ring, registry.get("holder").id)
    assert cli.forget("holder") == 2
    assert registry.get("holder")


def test_forget_removes_an_empty_client(world):
    registry, keys, ring = world
    registry.add(ClientRecord(name="empty"))
    assert cli.forget("empty") == 0
    with pytest.raises(UnknownClient):
        registry.get("empty")


def test_forget_refuses_a_client_holding_only_an_endpoint(world):
    """The one that lost data rather than merely failing to carry it.

    `forget` asked `_read("tokens")`, so a client whose whole session is an
    address read as holding nothing: the registry row went and the endpoint
    stayed in the keychain under an id no command could name again.
    """
    registry, keys, ring = world
    registry.add(ClientRecord(name="holder"))
    _endpoint(ring, registry.get("holder").id)

    assert cli.forget("holder") == 2
    assert registry.get("holder")


def test_a_merge_of_two_endpoints_for_one_provider_is_refused(world):
    """Two installations, not one client twice.

    `move_to` would overwrite the target's address with the source's, and an
    address that carries a credential cannot be recovered from a login.
    """
    registry, keys, ring = world
    registry.add(ClientRecord(name="one"))
    registry.add(ClientRecord(name="two"))
    _endpoint(ring, registry.get("one").id, url="https://one.test/mcp/a")
    _endpoint(ring, registry.get("two").id, url="https://two.test/mcp/b")

    assert cli.merge("one", "two") == 2
    from munim.remote.storage import KeychainTokenStorage
    assert (KeychainTokenStorage(registry.get("two").id, "zoho", ring).endpoint()
            == "https://two.test/mcp/b")


def test_a_merge_carries_a_client_holding_only_an_endpoint(world):
    registry, keys, ring = world
    registry.add(ClientRecord(name="src"))
    registry.add(ClientRecord(name="dst"))
    source, target = registry.get("src"), registry.get("dst")
    _endpoint(ring, source.id, url="https://src.test/mcp/a")

    assert cli.merge("src", "dst") == 0

    from munim.remote.storage import KeychainTokenStorage
    assert (KeychainTokenStorage(target.id, "zoho", ring).endpoint()
            == "https://src.test/mcp/a")
    assert KeychainTokenStorage(source.id, "zoho", ring).endpoint() is None


def test_a_rename_carries_a_legacy_endpoint_filed_under_the_label(world):
    """Only legacy sessions are keyed on the label, and they can be endpoints.

    `registry.rename` keeps the id, so a session filed under an id needs no
    move. One filed under the old name before the two were split does, and
    after the rename there is nothing left to find it by.
    """
    registry, keys, ring = world
    registry.add(ClientRecord(name="old name"))
    _endpoint(ring, "old name", url="https://legacy.test/mcp/a")

    assert cli.rename("old name", "new name") == 0

    from munim.remote.storage import KeychainTokenStorage
    assert (KeychainTokenStorage("new name", "zoho", ring).endpoint()
            == "https://legacy.test/mcp/a")
