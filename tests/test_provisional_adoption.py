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


def test_a_client_can_be_created_for_it(estate, monkeypatch, capsys):
    """Refusing because the name is new would mean logging in again for no
    reason. The login has already happened."""
    reg, _ = estate
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
