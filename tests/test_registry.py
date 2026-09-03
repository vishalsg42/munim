"""The registry knows which clients exist and what they have.

It must never know a secret. mcpwarden got this right (docs/DECISIONS.md D15):
the registry holds references, the keychain holds values.
"""

import json

import pytest

from munim.registry import ClientRecord, Registry, UnknownClient


def test_a_new_registry_has_no_clients(tmp_path):
    assert Registry(tmp_path / "registry.json").clients() == []


def test_added_clients_survive_a_reload(tmp_path):
    path = tmp_path / "registry.json"
    Registry(path).add(
        ClientRecord(name="acme", domain="acme.example", providers=["vercel"])
    )

    reloaded = Registry(path).get("acme")
    assert reloaded.domain == "acme.example"
    assert reloaded.providers == ["vercel"]


def test_an_unknown_client_is_an_error_not_an_empty_record(tmp_path):
    with pytest.raises(UnknownClient):
        Registry(tmp_path / "registry.json").get("nobody")


def test_adding_the_same_client_twice_is_rejected(tmp_path):
    registry = Registry(tmp_path / "registry.json")
    registry.add(ClientRecord(name="acme"))
    with pytest.raises(ValueError):
        registry.add(ClientRecord(name="acme"))


def test_the_registry_file_never_contains_a_secret(tmp_path):
    """A ClientRecord has nowhere to put a token, by construction."""
    path = tmp_path / "registry.json"
    registry = Registry(path)
    with pytest.raises(Exception):
        registry.add(
            ClientRecord(name="acme", providers=["vercel"], token="sk-secret-value")
        )

    registry.add(ClientRecord(name="acme", providers=["vercel"]))
    assert "sk-secret-value" not in path.read_text()
    # Providers are named, never valued.
    stored = json.loads(path.read_text())
    assert stored["acme"]["providers"] == ["vercel"]


def test_a_client_can_be_looked_up_by_one_of_its_domains(tmp_path):
    """'why is checkout.acme.example down' should resolve to a client without
    the operator naming one (docs/DECISIONS.md D5)."""
    path = tmp_path / "registry.json"
    registry = Registry(path)
    registry.add(ClientRecord(name="acme", domain="acme.example"))
    registry.add(ClientRecord(name="bharat", domain="bharat.example"))

    assert registry.find_by_domain("checkout.acme.example").name == "acme"
    assert registry.find_by_domain("acme.example").name == "acme"
    assert registry.find_by_domain("unrelated.example") is None


def test_update_replaces_an_existing_client(tmp_path):
    """connect_provider must append to `providers`, and `add` refuses to
    overwrite, so there has to be an update path."""
    path = tmp_path / "registry.json"
    registry = Registry(path)
    registry.add(ClientRecord(name="acme"))

    record = registry.get("acme")
    record.providers.append("cloudflare")
    registry.update(record)

    assert Registry(path).get("acme").providers == ["cloudflare"]


def test_update_refuses_an_unregistered_client(tmp_path):
    from munim.registry import UnknownClient

    with pytest.raises(UnknownClient):
        Registry(tmp_path / "registry.json").update(ClientRecord(name="ghost"))


def test_a_failed_write_leaves_the_previous_file_intact(tmp_path):
    """Atomic write: the agent, the room and interactive tools all write here.
    A truncated file fails json.loads and takes every client down at once."""
    path = tmp_path / "registry.json"
    registry = Registry(path)
    registry.add(ClientRecord(name="acme", domain="acme.example"))
    before = path.read_text()

    import json as _json
    original = _json.dumps

    def explode(*args, **kwargs):
        raise RuntimeError("disk full")

    _json.dumps = explode
    try:
        with pytest.raises(RuntimeError):
            registry.add(ClientRecord(name="bharat"))
    finally:
        _json.dumps = original

    assert path.read_text() == before
    assert Registry(path).get("acme").domain == "acme.example"
    assert list(path.parent.glob("*.tmp")) == []
