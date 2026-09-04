"""doctor has to mention the providers that need an application.

It said "Everything is set up" on a machine where Gmail and Stitch could not be
connected at all: both authenticate against accounts.google.com, which publishes
no registration endpoint, so each needs an application registered by hand, and
neither had one.

The cause is the same shape as the supabase bug fixed earlier: doctor iterated
the application-route providers in connect/oauth.py rather than the providers in
the server table whose auth kind is `app`. Two lists describing overlapping
things, and the one doctor read did not contain the answer.
"""

import os

from munim.doctor import _oauth_apps
from munim.remote.servers import SERVERS


def _lines(monkeypatch, **env):
    for provider in SERVERS:
        for suffix in ("_OAUTH_CLIENT_ID", "_OAUTH_CLIENT_SECRET"):
            monkeypatch.delenv(f"{provider.upper()}{suffix}", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return {f.what: f for f in _oauth_apps()}


def test_a_provider_needing_an_application_is_reported(monkeypatch):
    found = _lines(monkeypatch)

    assert "Login: gmail" in found, (
        "doctor never mentions gmail, which cannot be connected without an "
        "application registered by hand")
    assert found["Login: gmail"].status != "ok"


def test_the_fix_names_the_helper(monkeypatch):
    """Telling somebody to go and register an application without saying that
    two of the three steps are scripted is worse than saying nothing."""
    found = _lines(monkeypatch)

    assert "setup_google_oauth" in (found["Login: gmail"].fix or "")


def test_once_registered_it_reads_as_ready(monkeypatch):
    found = _lines(monkeypatch,
                   GMAIL_OAUTH_CLIENT_ID="an-id.apps.googleusercontent.com",
                   GMAIL_OAUTH_CLIENT_SECRET="a-secret")

    assert found["Login: gmail"].status == "ok"


def test_every_app_provider_is_covered(monkeypatch):
    """Not just gmail. Anything the table says needs an application."""
    found = _lines(monkeypatch)
    for provider, server in SERVERS.items():
        if server.auth == "app":
            assert f"Login: {provider}" in found, f"{provider} is unreported"
