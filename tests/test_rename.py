"""Renaming a client has to take everything filed under its name with it.

A client can now be named after the account it was authorised as, and
`Tech.example@gmail.com's Account` is not what anyone calls their client. So
renaming stopped being a nicety. Leaving the sessions behind would silently
disconnect a client that still looks connected in `doctor`.
"""

import pytest

from munim.registry import ClientRecord, Registry, UnknownClient


def test_a_client_keeps_its_domain_through_a_rename(tmp_path):
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="Tech.x@gmail.com's Account",
                              domain="balajiroofings-quote.vercel.app"))

    record = registry.rename("Tech.x@gmail.com's Account", "Balaji Roofings")

    assert record.name == "Balaji Roofings"
    assert record.domain == "balajiroofings-quote.vercel.app"
    assert Registry(tmp_path / "r.json").get("Balaji Roofings").domain == \
        "balajiroofings-quote.vercel.app"


def test_the_old_name_is_gone(tmp_path):
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="old"))
    registry.rename("old", "new")
    with pytest.raises(UnknownClient):
        registry.get("old")


def test_renaming_onto_an_existing_client_is_refused(tmp_path):
    """Merging two clients into one is a mutation on the wrong account waiting
    to happen."""
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="acme"))
    registry.add(ClientRecord(name="beta"))
    with pytest.raises(ValueError, match="already registered"):
        registry.rename("acme", "beta")
    assert {r.name for r in registry.clients()} == {"acme", "beta"}


def test_renaming_something_unregistered_says_so(tmp_path):
    with pytest.raises(UnknownClient):
        Registry(tmp_path / "r.json").rename("nobody", "somebody")


def test_a_session_follows_the_rename(tmp_path, monkeypatch):
    """The part that would fail silently: doctor would still show the client as
    connected while the token sat under a name nothing looks up."""
    from munim import cli
    from munim.remote.storage import KeychainTokenStorage

    class Ring:
        def __init__(self): self.s = {}
        def get_password(self, a, b): return self.s.get((a, b))
        def set_password(self, a, b, c): self.s[(a, b)] = c
        def delete_password(self, a, b): self.s.pop((a, b), None)

    ring = Ring()
    monkeypatch.setattr("munim.remote.storage.vault", ring)

    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="old"))
    monkeypatch.setattr(cli, "_registry", lambda: registry)

    store = KeychainTokenStorage("old", "cloudflare", ring)
    ring.set_password(store._service("tokens"), "old",
                      '{"access_token": "t", "token_type": "Bearer"}')

    class NoKeys:
        def get(self, c, p): return None
        def set(self, c, p, s): pass
    monkeypatch.setattr("munim.container.KeychainBackend", lambda: NoKeys())

    assert cli.rename("old", "new") == 0
    assert KeychainTokenStorage("new", "cloudflare", ring)._read("tokens") is not None
    assert KeychainTokenStorage("old", "cloudflare", ring)._read("tokens") is None
