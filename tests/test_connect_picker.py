"""Connecting a second provider should offer the clients you already have.

`munim connect supabase` with no client named went straight to "authorise, then
name the client after whichever account answered". That is right the first time
somebody uses this, and wrong every time after: attaching a second provider to
an existing client is the common case, and it silently created a third client
instead. The only way to avoid it was to remember and retype a name already on
screen, which is the friction `ask_which_client` was written to remove for the
Zoho path and never wired into this one.

Three cases, and they are genuinely different:
  - no clients yet: nothing to choose from, so do not ask
  - clients exist and a terminal is attached: offer them
  - no terminal: never block, fall back to naming by account
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
def world(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "r.json")
    monkeypatch.setattr(cli, "_registry", lambda: registry)
    monkeypatch.setattr("munim.remote.storage.vault", Ring())
    return registry


def _capture(monkeypatch):
    """Which client connect_via_mcp was handed, without running the flow."""
    seen = {}
    monkeypatch.setattr(cli, "connect_via_mcp",
                        lambda c, p: seen.update(client=c, provider=p) or 0)
    return seen


def test_with_clients_and_a_terminal_it_offers_them(world, monkeypatch):
    """The regression: it never asked, and made a third client."""
    world.add(ClientRecord(name="Kloudfirst", domain="kloudfirst.com"))
    world.add(ClientRecord(name="Balaji Roofings"))
    chosen = world.get("Kloudfirst")

    seen = _capture(monkeypatch)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "ask_which_client", lambda reg, **kw: chosen.id)

    assert cli.main(["connect", "supabase"]) == 0
    assert seen["client"] == chosen.id, "did not use the picked client"


def test_with_no_clients_it_does_not_ask(world, monkeypatch):
    """Nothing to choose from. Asking would be a prompt with one option, and
    the account naming the client is the zero-setup path this project wants."""
    seen = _capture(monkeypatch)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "ask_which_client",
                        lambda reg, **kw: pytest.fail("asked with no clients"))

    assert cli.main(["connect", "supabase"]) == 0
    assert seen["client"] is None, "should let the account name the client"


def test_without_a_terminal_it_does_not_block(world, monkeypatch):
    """A prompt nobody can answer is a hang. CI and scripts land here."""
    world.add(ClientRecord(name="Kloudfirst"))
    seen = _capture(monkeypatch)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "ask_which_client",
                        lambda reg, **kw: pytest.fail("prompted with no tty"))

    assert cli.main(["connect", "supabase"]) == 0
    assert seen["client"] is None


def test_naming_a_client_skips_the_picker(world, monkeypatch):
    """Anyone who typed a name has already answered the question."""
    world.add(ClientRecord(name="Kloudfirst"))
    seen = _capture(monkeypatch)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "ask_which_client",
                        lambda reg, **kw: pytest.fail("asked despite a name"))

    assert cli.main(["connect", "Kloudfirst", "supabase"]) == 0
    assert seen["client"] == "Kloudfirst"


def test_backing_out_connects_nothing(world, monkeypatch):
    world.add(ClientRecord(name="Kloudfirst"))
    seen = _capture(monkeypatch)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "ask_which_client", lambda reg, **kw: None)

    assert cli.main(["connect", "supabase"]) == cli.CANCELLED
    assert not seen, "backed out and it connected anyway"


def test_the_account_can_still_name_a_new_client(world, monkeypatch):
    """Wiring in the picker must not remove the path it replaced. Signing in
    and letting the account supply the name is what keeps a label and an
    account from drifting apart, and typing a name by hand is how they drift."""
    world.add(ClientRecord(name="Kloudfirst"))
    seen = _capture(monkeypatch)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "ask_which_client",
                        lambda reg, **kw: cli.ACCOUNT_NAMES_IT)

    assert cli.main(["connect", "supabase"]) == 0
    assert seen["client"] is None, "should authorise first and name after"


def test_the_option_is_offered_only_where_it_works(world):
    """Zoho's URL cannot name itself, so that path must not offer it."""
    world.add(ClientRecord(name="Kloudfirst"))
    shown = []
    monkeypatch_print = shown.append

    import io
    import contextlib
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        cli.ask_which_client(world, ask=lambda: "1", account_can_name=False)
    assert "named after the account" not in err.getvalue()

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        cli.ask_which_client(world, ask=lambda: "1", account_can_name=True)
    assert "named after the account" in err.getvalue()
