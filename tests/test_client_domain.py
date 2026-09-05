"""A client's domain has to be correctable, or the wrong one is watched forever.

`--domain` only ever applied to `clients add`. A client whose domain was wrong
was wrong for good, and that is not cosmetic: `audit_all_clients` checks the
registered domain, so a client recorded as a Vercel preview URL had a hostname
that is always up being watched instead of the site that can break.

That happened on a real client in this project. The site returned 404 for long
enough to be noticed by a person, and munim reported everything fine, because it
was watching `balajiroofings-quote.vercel.app` rather than
`balajiroofingindustries.com`.
"""

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    reg = Registry(tmp_path / "r.json")
    monkeypatch.setattr(cli, "_registry", lambda: reg)
    return reg


def test_a_client_with_no_domain_can_be_given_one(registry, capsys):
    registry.add(ClientRecord(name="Acme"))

    assert cli.set_domain("Acme", "acme.test") == 0
    assert registry.get("Acme").domain == "acme.test"


def test_a_wrong_domain_can_be_corrected(registry, capsys):
    """The whole point. This was impossible before."""
    registry.add(ClientRecord(name="Acme", domain="acme-preview.vercel.app"))

    assert cli.set_domain("Acme", "acme.test") == 0
    assert registry.get("Acme").domain == "acme.test"


def test_the_correction_says_what_it_replaced(registry, capsys):
    """Changing which hostname is monitored silently would be the same failure
    in a different place."""
    registry.add(ClientRecord(name="Acme", domain="acme-preview.vercel.app"))
    cli.set_domain("Acme", "acme.test")

    said = capsys.readouterr().err
    assert "acme.test" in said
    assert "acme-preview.vercel.app" in said, "it did not say what it replaced"


def test_a_domain_can_be_cleared(registry, capsys):
    """Not an error. A client with no domain is somebody you look after and
    have not told munim where to find yet."""
    registry.add(ClientRecord(name="Acme", domain="acme.test"))

    assert cli.set_domain("Acme", "") == 0
    assert registry.get("Acme").domain is None
    assert "nothing will be checked" in capsys.readouterr().err.lower()


def test_an_unknown_client_is_refused(registry, capsys):
    assert cli.set_domain("Nobody", "acme.test") == 2
    assert "Nobody" in capsys.readouterr().err


def test_the_domain_is_what_the_audit_would_watch(registry):
    """The property this exists for: `audit_all_clients` filters on a domain
    being present, and resolves a hostname back to its client."""
    registry.add(ClientRecord(name="Acme"))
    assert [r for r in registry.clients() if r.domain] == [], "nothing to audit yet"

    cli.set_domain("Acme", "acme.test")
    assert [r.name for r in registry.clients() if r.domain] == ["Acme"]
    assert registry.find_by_domain("acme.test").name == "Acme"


def test_it_is_reachable_from_the_command_line(registry, capsys):
    assert cli.main(["clients", "domain", "Acme", "acme.test"]) == 2, \
        "an unknown client should be refused"

    registry.add(ClientRecord(name="Acme"))
    assert cli.main(["clients", "domain", "Acme", "acme.test"]) == 0
    assert registry.get("Acme").domain == "acme.test"


def test_it_takes_exactly_a_client_and_a_site(registry, capsys):
    registry.add(ClientRecord(name="Acme"))
    with pytest.raises(SystemExit):
        cli.main(["clients", "domain", "Acme"])
