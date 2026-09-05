"""A completed login is never thrown away.

`munim connect vercel`, with no client named, authorises first and asks the
provider who that was second. Vercel grants `openid offline_access` and nothing
that names an account, so the answer is nobody.

That used to print "run it again with a name" and return 2. Two things were
wrong with it. The browser login had already happened, so the operator was being
asked to do it again for no reason. And the tokens stayed filed under the
provisional key, where nothing could name them and nothing would clean them up:
a live credential orphaned by a command that reported failure. This is the class
of leftover `_sweep_orphans` had to be written for.

The operator knows which client it is. Ask them.
"""

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


@pytest.fixture
def estate(tmp_path, monkeypatch):
    ring = Ring()
    reg = Registry(tmp_path / "r.json")
    monkeypatch.setattr(cli, "_registry", lambda: reg)
    monkeypatch.setattr("munim.remote.storage.keyring", ring)
    monkeypatch.setattr("munim.container.keyring", ring)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    return reg, ring


def test_an_existing_client_can_adopt_the_session(estate, monkeypatch, capsys):
    reg, _ = estate
    reg.add(ClientRecord(name="Acme"))

    record = cli.adopt_provisional(reg, "vercel", ask=lambda: "1")
    assert record is not None and record.name == "Acme"


def test_a_client_can_be_created_alongside_existing_ones(estate, monkeypatch, capsys):
    """Refusing because the name is new would mean logging in again for no
    reason. The login has already happened.

    A client is registered first so that the menu exists: with an empty registry
    there is no "not listed" step, because there is nothing listed to be absent
    from, and the prompt asks for a name directly.
    """
    reg, _ = estate
    reg.add(ClientRecord(name="Acme"))
    answers = iter(["n", "Ivy & Fern"])

    record = cli.adopt_provisional(reg, "vercel", ask=lambda: next(answers))
    assert record is not None and record.name == "Ivy & Fern"
    assert reg.get("Ivy & Fern").id == record.id, "it was not actually registered"


def test_backing_out_keeps_nothing(estate, capsys):
    """The alternative is tokens nobody chose an owner for, which is how the
    orphans this project already had to sweep up came to exist."""
    reg, _ = estate
    assert cli.adopt_provisional(reg, "vercel", ask=lambda: "") is None


def test_with_no_terminal_it_says_so_rather_than_hanging(estate, monkeypatch, capsys):
    reg, _ = estate
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

    assert cli.adopt_provisional(reg, "vercel") is None
    said = capsys.readouterr().err
    assert "no terminal" in said
    assert "munim connect" in said, "a refusal with no next step is a complaint"


def test_the_session_moves_onto_the_chosen_client(estate):
    """The point of the whole exercise: the tokens end up under a client id, not
    under the provisional key."""
    from munim.remote.storage import KeychainTokenStorage

    reg, ring = estate
    record = ClientRecord(name="Acme")
    reg.add(record)

    provisional = KeychainTokenStorage(cli.PROVISIONAL, "vercel", ring)
    provisional._write("tokens", _Token("t"))
    provisional.move_to(record.id)

    assert KeychainTokenStorage(record.id, "vercel", ring)._read("tokens")
    assert KeychainTokenStorage(cli.PROVISIONAL, "vercel", ring)._read("tokens") is None


def test_nothing_is_left_under_the_provisional_key_when_declined(estate):
    """A live credential filed where nothing can name it is worse than no
    credential at all."""
    from munim.remote.storage import KeychainTokenStorage

    reg, ring = estate
    store = KeychainTokenStorage(cli.PROVISIONAL, "vercel", ring)
    store._write("tokens", _Token("t"))

    store.forget()
    assert store._read("tokens") is None
    assert not [k for k in ring.s if cli.PROVISIONAL in k[1]]


class _Token:
    def __init__(self, value): self.value = value
    def model_dump_json(self): return '{"access_token": "%s"}' % self.value


# ---- the picker with nothing to pick -------------------------------------

def test_an_empty_registry_asks_for_a_name_rather_than_offering_a_menu(estate, capsys):
    """Printing "Which client is this for?" above a single line reading "a
    client not listed" is a menu with no items on it. The operator has to work
    out that the answer is `n` before they can type the name they already knew.
    """
    reg, _ = estate

    assert cli.ask_which_client(reg, ask=lambda: "Ivy & Fern") == "Ivy & Fern"
    asked = capsys.readouterr().err
    assert "Name for this client" in asked
    assert "Which client is this for" not in asked
    assert "a client not listed" not in asked


def test_the_menu_comes_back_as_soon_as_there_is_something_to_pick(estate, capsys):
    """The other direction. Asserting only that the menu is hidden would pass
    if the menu had been deleted."""
    reg, _ = estate
    reg.add(ClientRecord(name="Acme", domain="acme.test"))

    chosen = cli.ask_which_client(reg, ask=lambda: "1")
    assert chosen == reg.get("Acme").id, "the menu must return an id, not a label"
    asked = capsys.readouterr().err
    assert "Which client is this for" in asked
    assert "Acme" in asked and "acme.test" in asked


def test_an_empty_name_backs_out_rather_than_registering_nothing(estate):
    reg, _ = estate
    assert cli.ask_which_client(reg, ask=lambda: "   ") is None


def test_adoption_uses_the_name_typed_into_an_empty_registry(estate):
    """End to end: a first connection on a fresh install has no menu, and the
    session still ends up filed under a real client id."""
    reg, _ = estate
    record = cli.adopt_provisional(reg, "vercel", ask=lambda: "Ivy & Fern")

    assert record is not None
    assert record.name == "Ivy & Fern"
    assert record.id.startswith("c_"), "credentials are filed by identity"
    assert reg.get("Ivy & Fern").id == record.id
