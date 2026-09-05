"""Two nouns, and every command reads as one of them.

The surface grew a command at a time and ended up flat: `add-server` existed
with no `add-client` beside it, so from the terminal a client could only come
into being as a side effect of `connect`. There was no way to write down "I
look after this business" before deciding what to connect.

Clients and servers are the two things Munim knows about, so they are the two
groups. `connect` stays a verb because it is an event rather than a thing.

The old flat names keep working. 0.1.0 shipped with them and breaking a
published surface to tidy it is a bad trade when an alias costs a line.
"""

import pytest

from munim import cli
from munim.registry import Registry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    reg = Registry(tmp_path / "r.json")
    monkeypatch.setattr(cli, "_registry", lambda: reg)
    monkeypatch.setattr("munim.remote.storage.vault", _Ring())
    return reg


class _Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


def test_a_client_can_be_created_before_anything_is_connected(registry, capsys):
    """The gap. You look after a business before you decide which accounts of
    theirs you hold."""
    assert cli.main(["clients", "add", "Ivy & Fern"]) == 0

    record = registry.get("Ivy & Fern")
    assert record.name == "Ivy & Fern"
    assert record.id.startswith("c_")


def test_a_client_can_carry_its_domain(registry):
    assert cli.main(["clients", "add", "Ivy & Fern",
                     "--domain", "ivyandfern.co.uk"]) == 0
    assert registry.get("Ivy & Fern").domain == "ivyandfern.co.uk"


def test_adding_the_same_client_twice_is_refused(registry, capsys):
    """Two rows for one business is the split identity `merge` exists to
    repair. Better not to make it."""
    cli.main(["clients", "add", "Ivy & Fern"])

    assert cli.main(["clients", "add", "Ivy & Fern"]) == 2
    assert "already" in capsys.readouterr().err.lower()
    assert len(registry.clients()) == 1


def test_bare_clients_still_lists(registry, capsys):
    cli.main(["clients", "add", "Ivy & Fern"])
    assert cli.main(["clients"]) == 0
    assert "Ivy & Fern" in capsys.readouterr().out


@pytest.mark.parametrize("argv, alias_of", [
    (["add-server", "acme", "https://mcp.acme.com/mcp"], "servers add"),
    (["rename", "a", "b"], "clients rename"),
    (["forget", "a"], "clients forget"),
    (["merge", "a", "b"], "clients merge"),
])
def test_the_old_flat_names_still_work(registry, argv, alias_of, capsys):
    """0.1.0 shipped with these. Breaking a published surface to tidy it is a
    bad trade when an alias costs a line."""
    registry.add(__import__("munim.registry", fromlist=["ClientRecord"]).ClientRecord(name="a"))
    registry.add(__import__("munim.registry", fromlist=["ClientRecord"]).ClientRecord(name="b"))

    result = cli.main(argv)

    assert result is not None, f"{argv[0]} no longer parses; it aliases {alias_of}"


def test_servers_add_is_the_new_spelling(registry, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("munim.remote.servers.USER_SERVERS", tmp_path / "servers.json")
    result = cli.main(["servers", "add", "acme", "https://mcp.acme.com/mcp"])
    assert result is not None


def test_bare_servers_still_lists(capsys):
    assert cli.main(["servers"]) == 0
    assert "cloudflare" in capsys.readouterr().out
