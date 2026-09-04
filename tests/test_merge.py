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
    monkeypatch.setattr("munim.remote.storage.keyring", ring)
    return registry, keys, ring


def _session(ring, client_id, provider="cloudflare"):
    from munim.remote.storage import KeychainTokenStorage
    store = KeychainTokenStorage(client_id, provider, ring)
    ring.set_password(store._service("tokens"), client_id,
                      '{"access_token": "t", "token_type": "Bearer"}')


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
