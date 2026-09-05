"""The affordances every CLI has, and the one destructive path that lacked a guard.

`munim disconnect --all` could empty the keychain from a single flag. Getting
back is a browser login per client per provider, so it is the one command here
that deserves to be slow.

The first confirmation written for it was worse than none. It asked
`connected.connections()` what a client held, which reports a provider only when
there are *tokens*, while the command deletes rather more than that. Zoho
authenticates by URL and stores an endpoint and no tokens at all, so the one
credential in this system that no browser login can rebuild was invisible to the
prompt and deleted by the command. The fix is structural: one list, printed and
then acted on.
"""

import json

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
    """One client, and a keyring shared by both the session store and the
    API-key backend, so a test can seed either."""
    ring = Ring()
    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme"))
    monkeypatch.setattr(cli, "_registry", lambda: reg)
    monkeypatch.setattr("munim.remote.storage.keyring", ring)
    monkeypatch.setattr("munim.container.keyring", ring)
    # Shells out to `security dump-keychain` otherwise, which is slow and reads
    # the machine the suite happens to run on.
    monkeypatch.setattr(cli, "find_orphans", lambda known: [])
    return reg, ring


@pytest.fixture
def a_terminal(monkeypatch):
    """`--all` checks for a tty before prompting. Without this the prompt tests
    pass at that guard without ever reaching the question."""
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)


# ---- version -------------------------------------------------------------

@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_the_version_is_printed_and_exits_zero(flag, capsys):
    """`action="version"` exits inside parse_args rather than returning, so a
    test asserting `main(...) == 0` would fail on an uncaught SystemExit."""
    with pytest.raises(SystemExit) as raised:
        cli.main([flag])
    assert raised.value.code == 0
    assert "munim" in capsys.readouterr().out


def test_the_version_is_read_from_the_install_not_a_literal():
    """A second copy of a version string drifts from pyproject eventually."""
    from importlib.metadata import version

    assert cli.installed_version() == version("munim")


# ---- the bare name -------------------------------------------------------

def test_the_bare_name_prints_help_and_succeeds(capsys):
    """Typing a tool's name to find out what it does is not a mistake, and
    answering it with exit 2 says it is."""
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "usage: munim" in out


def test_the_help_describes_munim_rather_than_one_subcommand(capsys):
    """The parser took the module docstring, which is about `connect`. Harmless
    while the bare name was an error; wrong once it became the front door."""
    cli.main([])
    out = capsys.readouterr().out
    assert "many clients" in out
    assert "munim doctor" in out


def test_a_bad_subcommand_still_fails(capsys):
    """The other direction. Asserting only that the bare name returns 0 would
    pass just as well if every input returned 0."""
    with pytest.raises(SystemExit) as raised:
        cli.main(["bogus"])
    assert raised.value.code == 2


# ---- the plan is the deletion --------------------------------------------

def _seed(reg, ring):
    """Three credentials, each of which the old confirmation missed."""
    from munim.remote.storage import KeychainTokenStorage

    record = reg.get("Acme")
    ring.set_password("munim:cloudflare", record.id, "an-api-key")
    # Filed under the label, from before the identity split. Deleted by this
    # command since it was written, and never named by the old confirmation.
    ring.set_password("munim:resend", record.name, "a-legacy-key")
    # Zoho: an endpoint and no tokens. Invisible to a tokens-only check, and
    # the one credential here a browser login cannot rebuild.
    KeychainTokenStorage(record.id, "zoho", ring).remember_endpoint(
        "https://x.zohomcp.in/mcp/deadbeef/message")
    return record


def test_the_preview_names_everything_the_command_then_removes(estate, a_terminal, capsys):
    """The defect this whole restructure exists for. The preview and the
    deletion are one list, so they cannot disagree."""
    reg, ring = estate
    _seed(reg, ring)

    assert cli.main(["disconnect", "--all", "--dry-run"]) == 0
    preview = capsys.readouterr().err
    assert "cloudflare key" in preview
    assert "resend key (filed under the old label)" in preview
    assert "zoho session (endpoint)" in preview, \
        "a Zoho endpoint is a credential no login can rebuild; it must be named"

    assert cli.main(["disconnect", "--all", "--yes"]) == 0
    removed = capsys.readouterr().err
    for named in ("cloudflare key", "resend key", "zoho session"):
        assert named in removed, f"previewed but not removed: {named}"
    assert ring.s == {}, f"something survived that the preview promised: {ring.s}"


def _settled(ring):
    """A snapshot taken after the migration that runs on every invocation.

    `migrate()` copies credentials filed under a client's label onto its id, so
    the first command after seeding a legacy credential legitimately changes the
    keyring. Snapshotting before that made "removes nothing" fail on a move
    nobody objected to.
    """
    cli.main(["clients"])
    return dict(ring.s)


def test_a_dry_run_removes_nothing(estate, capsys):
    reg, ring = estate
    _seed(reg, ring)
    before = _settled(ring)

    assert cli.main(["disconnect", "--all", "--dry-run"]) == 0
    assert ring.s == before
    assert "Nothing was removed" in capsys.readouterr().err


def test_saying_no_removes_nothing(estate, a_terminal, monkeypatch, capsys):
    reg, ring = estate
    _seed(reg, ring)
    before = _settled(ring)
    monkeypatch.setattr("builtins.input", lambda: "no")

    assert cli.main(["disconnect", "--all"]) == 2
    assert ring.s == before


def test_saying_yes_proceeds(estate, a_terminal, monkeypatch):
    reg, ring = estate
    _seed(reg, ring)
    monkeypatch.setattr("builtins.input", lambda: "yes")

    assert cli.main(["disconnect", "--all"]) == 0
    assert ring.s == {}


def test_yes_skips_the_question_entirely(estate, a_terminal, monkeypatch):
    """Not "answers it automatically". A script must not block on a prompt."""
    reg, ring = estate
    _seed(reg, ring)

    def never():
        raise AssertionError("--yes still asked the question")

    monkeypatch.setattr("builtins.input", never)
    assert cli.main(["disconnect", "--all", "--yes"]) == 0


def test_with_no_terminal_it_refuses_and_says_how(estate, monkeypatch, capsys):
    reg, ring = estate
    _seed(reg, ring)
    before = _settled(ring)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

    assert cli.main(["disconnect", "--all"]) == 2
    assert ring.s == before
    said = capsys.readouterr().err
    assert "--dry-run" in said and "--yes" in said


def test_a_client_holding_only_a_legacy_credential_is_still_asked(estate, a_terminal, monkeypatch, capsys):
    """The old confirmation returned True under the comment "nothing to lose"
    whenever its narrow check found nothing, which is exactly when the label
    cleanup still fired. It could skip itself and delete anyway."""
    reg, ring = estate
    ring.set_password("munim:resend", reg.get("Acme").name, "a-legacy-key")
    asked = []
    monkeypatch.setattr("builtins.input", lambda: asked.append(1) or "no")

    assert cli.main(["disconnect", "--all"]) == 2
    assert asked, "deleted a credential without asking"
    assert ring.s, "removed it despite the refusal"


# ---- machine-readable listing -------------------------------------------

def test_json_reports_the_credentials_that_are_actually_there(estate, capsys):
    """Asserted against known seeded credentials rather than against the table.
    Both formats call the same function, so comparing them proves nothing."""
    reg, ring = estate
    _seed(reg, ring)

    assert cli.main(["clients", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    row = payload[0]
    assert row["name"] == "Acme"
    assert row["id"] == reg.get("Acme").id
    assert "cloudflare" in row["api_keys"]
    assert "zoho" in row["mcp_sessions"]


def test_json_is_refused_where_it_would_do_nothing(estate):
    """An accepted-and-ignored flag is a bug report waiting to happen."""
    with pytest.raises(SystemExit) as raised:
        cli.main(["clients", "add", "Other", "--json"])
    assert raised.value.code == 2
