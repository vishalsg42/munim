"""The registry knows which clients exist and what they have.

It must never know a secret. mcpwarden got this right (docs/DECISIONS.md D15):
the registry holds references, the keychain holds values.
"""

import json

import json

import pytest

from munim.registry import ClientRecord, Registry, UnknownClient


def test_a_new_registry_has_no_clients(tmp_path):
    assert Registry(tmp_path / "registry.json").clients() == []


def test_added_clients_survive_a_reload(tmp_path):
    path = tmp_path / "registry.json"
    Registry(path).add(ClientRecord(name="acme", domain="acme.example"))

    reloaded = Registry(path).get("acme")
    assert reloaded.domain == "acme.example"


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
            ClientRecord(name="acme", token="sk-secret-value")
        )

    registry.add(ClientRecord(name="acme"))
    assert "sk-secret-value" not in path.read_text()
    # A stored record carries an id, a name and a domain and nothing else.
    # Whether a provider is connected is the keychain's to answer, not this
    # file's, and the file is keyed by id: the name is a label and a label that
    # is also a primary key cannot be changed without moving credentials.
    stored = json.loads(path.read_text())
    (key, record), = stored.items()
    assert key.startswith("c_")
    assert set(record) == {"id", "name", "domain"}
    assert record["id"] == key


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
    """`add` refuses to overwrite, so there has to be an update path - a client
    acquires a domain after it is registered."""
    path = tmp_path / "registry.json"
    registry = Registry(path)
    registry.add(ClientRecord(name="acme"))

    record = registry.get("acme")
    record.domain = "acme.example"
    registry.update(record)

    assert Registry(path).get("acme").domain == "acme.example"


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


def test_a_registry_written_before_the_keychain_was_the_only_truth_still_loads(tmp_path):
    """`providers` was a second copy of a fact the keychain already held, and
    `munim connect` never updated it. Removing the field must not lock anyone
    out of their own registry: `extra="forbid"` would reject the stale key and
    take every client down at once."""
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "acme": {"name": "acme", "domain": "acme.example",
                 "providers": ["vercel", "cloudflare"]},
    }))

    record = Registry(path).get("acme")
    assert record.domain == "acme.example"
    assert not hasattr(record, "providers")


def test_an_id_survives_being_read_twice(tmp_path):
    """The bug this exists for cost live credentials.

    Migrating a name-keyed registry minted an id on every read and never wrote
    it back, so no two reads agreed. Anything filed under an id could never be
    found again: every client read as disconnected while its tokens sat in the
    keychain under an id nothing would ever generate a second time.
    """
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"acme": {"name": "acme", "domain": "acme.example"}}))

    first = Registry(path).get("acme").id
    second = Registry(path).get("acme").id
    assert first == second, "a fresh id on every read is not an identity"
    assert first.startswith("c_")

    # And it is on disk, not just consistent in memory.
    stored = json.loads(path.read_text())
    assert first in stored
    assert "acme" not in stored, "still keyed by the label"


def test_migrating_keeps_the_name_as_a_label(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"Ivy & Fern": {"domain": "ivyandfern.co.uk"}}))
    record = Registry(path).get("Ivy & Fern")
    assert record.name == "Ivy & Fern"
    assert record.domain == "ivyandfern.co.uk"


def test_a_client_is_reachable_by_id_or_by_name(tmp_path):
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="Acme"))
    record = registry.get("Acme")
    assert registry.get(record.id).id == record.id
    assert registry.get("Acme").id == record.id
