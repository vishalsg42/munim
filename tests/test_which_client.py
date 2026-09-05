"""Asking which client, when the credential cannot say.

An OAuth login can name the client it just authorised: the provider is asked
who that was. A URL that carries a credential cannot, because there is nobody
to ask. Refusing and telling the operator to type a name already on their
screen is worse than showing the list.
"""

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry


@pytest.fixture
def registry(tmp_path):
    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Balaji Roofings", domain="balajiroofings.example"))
    reg.add(ClientRecord(name="Kloudfirst", domain="kloudfirst.com"))
    return reg


def _answers(*replies):
    it = iter(replies)
    return lambda: next(it)


def test_a_number_picks_the_client_it_listed(registry):
    """Listed alphabetically, so the number means the same thing twice."""
    chosen = cli.ask_which_client(registry, ask=_answers("1"))
    assert chosen == registry.get("Balaji Roofings").id


def test_a_name_typed_straight_in_works(registry):
    chosen = cli.ask_which_client(registry, ask=_answers("Kloudfirst"))
    assert chosen == registry.get("Kloudfirst").id


def test_an_id_typed_straight_in_works(registry):
    wanted = registry.get("Kloudfirst").id
    assert cli.ask_which_client(registry, ask=_answers(wanted)) == wanted


def test_the_not_listed_row_asks_for_a_new_name(registry):
    """It used to be the `n` shortcut. It is an ordinary row now, reached by its
    number or by the arrow keys, because a row that can be selected does not
    also need a letter."""
    assert cli.ask_which_client(registry, ask=_answers("3", "Ivy & Fern")) == "Ivy & Fern"


def test_a_new_client_with_no_name_is_not_created(registry):
    assert cli.ask_which_client(registry, ask=_answers("3", "   ")) is None


def test_a_number_out_of_range_chooses_nothing(registry):
    """Better to connect nothing than to connect the wrong account."""
    assert cli.ask_which_client(registry, ask=_answers("9")) is None


def test_backing_out_chooses_nothing(registry):
    def interrupted():
        raise KeyboardInterrupt
    assert cli.ask_which_client(registry, ask=interrupted) is None


def test_it_does_not_ask_when_there_is_no_terminal(registry, monkeypatch, capsys):
    """A script piping into this has nobody to answer, and hanging on input is
    worse than saying so."""
    monkeypatch.setattr(cli, "_registry", lambda: registry)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit):
        cli.main(["connect", "zoho", "--url", "https://x.test/mcp/abc/message"])
    assert "cannot name itself" in capsys.readouterr().err
