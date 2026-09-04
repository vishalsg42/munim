"""`munim config`, so an application credential needs no file.

The id can be a parameter: it is not a secret, it appears in the Cloud Console
and in every authorize URL. The secret is prompted rather than accepted on the
command line, because an argument lands in shell history and is visible to
anyone who can run `ps` while the command is running.
"""

import pytest

from munim import cli
from munim.appcreds import resolve


class Backend:
    def __init__(self): self.s = {}
    def get(self, client, provider): return self.s.get((client, provider))
    def set(self, client, provider, secret): self.s[(client, provider)] = secret
    def forget(self, client, provider): return self.s.pop((client, provider), None) is not None


@pytest.fixture
def backend(monkeypatch):
    b = Backend()
    monkeypatch.setattr("munim.appcreds.default_backend", lambda: b)
    for name in ("GMAIL_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    return b


def test_set_stores_an_application(backend, monkeypatch):
    monkeypatch.setattr("munim.cli.getpass", lambda prompt="": "a-secret")

    assert cli.main(["config", "set", "gmail", "--client-id", "an-id"]) == 0
    assert resolve("gmail", backend) == ("an-id", "a-secret")


def test_the_secret_is_never_a_command_line_argument():
    """Deliberate. An argument is in the shell history of whoever ran it and in
    the process list while it runs."""
    import io, contextlib
    err = io.StringIO()
    with contextlib.redirect_stderr(err), pytest.raises(SystemExit):
        cli.main(["config", "set", "gmail", "--client-secret", "oops"])
    assert "unrecognized arguments" in err.getvalue()


def test_an_empty_secret_is_allowed(backend, monkeypatch):
    """Some providers issue none, and Google documents an installed-app secret
    as not confidential."""
    monkeypatch.setattr("munim.cli.getpass", lambda prompt="": "")

    assert cli.main(["config", "set", "gmail", "--client-id", "an-id"]) == 0
    assert resolve("gmail", backend) == ("an-id", "")


def test_list_shows_what_is_set_and_never_a_secret(backend, monkeypatch, capsys):
    monkeypatch.setattr("munim.cli.getpass", lambda prompt="": "a-secret")
    cli.main(["config", "set", "gmail", "--client-id", "an-id"])

    cli.main(["config", "list"])

    out = capsys.readouterr()
    printed = out.out + out.err
    assert "gmail" in printed and "an-id" in printed
    assert "a-secret" not in printed


def test_unset_removes_it(backend, monkeypatch):
    monkeypatch.setattr("munim.cli.getpass", lambda prompt="": "a-secret")
    cli.main(["config", "set", "gmail", "--client-id", "an-id"])

    assert cli.main(["config", "unset", "gmail"]) == 0
    assert resolve("gmail", backend) is None


def test_unsetting_nothing_says_so(backend, capsys):
    assert cli.main(["config", "unset", "gmail"]) == 0
    assert "nothing" in (capsys.readouterr().err.lower())


def test_it_sees_what_a_dotenv_configured(tmp_path, monkeypatch, capsys):
    """`config list` said "not set" for gmail while `doctor` said "registered
    application", from the same values. doctor loads the .env and config did
    not, so one command contradicted the other about the same fact.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GMAIL_OAUTH_CLIENT_ID=from-a-dotenv\nGMAIL_OAUTH_CLIENT_SECRET=s\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_ID", raising=False)
    # The suite-wide guard points MUNIM_ENV at nothing so no test reads the
    # developer's own file. This one wants a file, so it names its own.
    monkeypatch.setenv("MUNIM_ENV", str(env_file))

    cli.main(["config", "list"])

    printed = capsys.readouterr()
    assert "from-a-dotenv" in printed.out + printed.err
