"""The Google setup helper must not create a second project, ever.

Vishal's question when this was proposed: "should we maintain the config
somewhere, so we don't create multiple GCP projects?" The answer is that it
never creates one. Project ids are globally unique and a script that creates
one per run leaves a trail of abandoned projects behind, so it uses the project
the operator already has, and `.env` holding the client id is what stops it
running a second time.

There is no state file, because `.env` is the state.
"""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/setup_google_oauth.py")


def _run(args, cwd, env=None):
    import os
    return subprocess.run([sys.executable, str(Path.cwd() / SCRIPT), *args],
                          capture_output=True, text=True, cwd=cwd,
                          env={**os.environ, **(env or {})}, timeout=120)


def test_it_never_creates_a_project():
    """The whole reason there is no config file to maintain."""
    source = SCRIPT.read_text()
    assert "projects create" not in source, (
        "the helper creates a Google Cloud project, which is what it exists "
        "not to do")


def test_an_existing_client_id_stops_it(tmp_path):
    """`.env` is the idempotence. Set means done."""
    (tmp_path / ".env").write_text(
        "GMAIL_OAUTH_CLIENT_ID=already-there.apps.googleusercontent.com\n")

    done = _run([], cwd=tmp_path)

    assert done.returncode == 0
    assert "already set" in done.stdout
    assert "console.cloud.google.com" not in done.stdout, (
        "it walked through setup for a provider already configured")


def test_a_blank_value_is_not_configured(tmp_path):
    """`.env.example` ships the keys with empty values, and copying it must not
    read as done."""
    (tmp_path / ".env").write_text("GMAIL_OAUTH_CLIENT_ID=\n")

    done = _run([], cwd=tmp_path, env={"GMAIL_OAUTH_CLIENT_ID": ""})

    assert "already set" not in done.stdout


def test_it_says_what_it_cannot_do(tmp_path):
    """Google exposes no API for creating a Desktop app OAuth client. A helper
    that hides that leaves the operator waiting for something to happen."""
    source = SCRIPT.read_text()
    assert "no API" in source or "publishes no" in source


def test_stitch_is_supported_too(tmp_path):
    """The same Google story, and the table lists both."""
    (tmp_path / ".env").write_text(
        "STITCH_OAUTH_CLIENT_ID=already-there.apps.googleusercontent.com\n")

    done = _run(["--provider", "stitch"], cwd=tmp_path)

    assert done.returncode == 0 and "already set" in done.stdout
