"""An application credential should not depend on which folder you are in.

Gmail and Stitch need an application registered by hand, and the id and secret
were read from the environment only. That means a file, and a file means a
location: the package installs to site-packages and the operator runs from
wherever they happen to be. `~/.munim/.env` fixed the discovery, and it is
still a file somebody has to create, edit and keep.

The keychain has no folder. It is also where Munim already puts every provider
credential, so an application credential living in a dotfile was the odd one
out rather than the rule.

The environment still wins, because CI sets these and a value already exported
is a deliberate act.
"""

import pytest

from munim.appcreds import forget, remember, resolve, stored


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


class Backend:
    """Matches KeychainBackend's shape: keyed by (client, provider)."""
    def __init__(self): self.s = {}
    def get(self, client, provider): return self.s.get((client, provider))
    def set(self, client, provider, secret): self.s[(client, provider)] = secret
    def forget(self, client, provider): return self.s.pop((client, provider), None) is not None


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for name in ("GMAIL", "STITCH", "ACME"):
        for suffix in ("_OAUTH_CLIENT_ID", "_OAUTH_CLIENT_SECRET"):
            monkeypatch.delenv(f"{name}{suffix}", raising=False)


def test_a_remembered_application_is_found_from_any_directory():
    """The whole point. No file, so no folder to be in the wrong one of."""
    backend = Backend()
    remember("gmail", "an-id.apps.googleusercontent.com", "a-secret", backend)

    assert resolve("gmail", backend) == (
        "an-id.apps.googleusercontent.com", "a-secret")


def test_the_environment_beats_the_keychain(monkeypatch):
    """CI exports these, and an exported value is a deliberate act."""
    backend = Backend()
    remember("gmail", "from-the-keychain", "keychain-secret", backend)
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "from-the-env")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "env-secret")

    assert resolve("gmail", backend) == ("from-the-env", "env-secret")


def test_nothing_anywhere_is_none_not_an_error():
    assert resolve("gmail", Backend()) is None


def test_an_id_with_no_secret_still_resolves():
    """Google's installed-app clients treat the secret as not confidential, and
    some providers issue none at all."""
    backend = Backend()
    remember("acme", "an-id", "", backend)

    assert resolve("acme", backend) == ("an-id", "")


def test_stored_reports_presence_and_never_the_secret():
    """`munim config list` prints this. A config command that echoes a secret
    puts it in the scrollback of whoever asked what was configured."""
    backend = Backend()
    remember("gmail", "an-id.apps.googleusercontent.com", "a-secret", backend)

    listed = stored(["gmail", "stitch"], backend)

    assert listed["gmail"]["client_id"] == "an-id.apps.googleusercontent.com"
    assert listed["gmail"]["secret"] is True
    assert "a-secret" not in repr(listed)
    assert listed["stitch"] is None


def test_forgetting_removes_both_halves():
    backend = Backend()
    remember("gmail", "an-id", "a-secret", backend)

    assert forget("gmail", backend) is True
    assert resolve("gmail", Backend()) is None
    assert forget("gmail", backend) is False


def test_the_session_uses_it(monkeypatch):
    """The point of all this: auth_for must find a keychain-stored application
    with nothing in the environment and no file anywhere.

    It seeds the token store rather than setting client_info, so that is what
    gets checked. Asserting on client_info passed nothing and failed loudly,
    which is the right way round.
    """
    import json

    from munim.remote.session import auth_for
    from munim.remote.storage import KeychainTokenStorage

    backend = Backend()
    remember("gmail", "an-id.apps.googleusercontent.com", "a-secret", backend)
    monkeypatch.setattr("munim.appcreds.default_backend", lambda: backend)

    ring = Ring()
    auth_for("c_x", "gmail", label="Acme", backend=ring)

    seeded = KeychainTokenStorage("c_x", "gmail", ring)._read("client")
    assert seeded["client_id"] == "an-id.apps.googleusercontent.com"
    assert seeded["client_secret"] == "a-secret"


def test_the_refusal_names_the_command_that_fixes_it(monkeypatch):
    """Telling somebody to set an environment variable is half an answer once
    the values can live in the keychain."""
    from munim.remote.session import NoRemoteServer, auth_for

    monkeypatch.setattr("munim.appcreds.default_backend", lambda: Backend())

    with pytest.raises(NoRemoteServer, match="munim config set"):
        auth_for("c_x", "gmail", label="Acme", backend=Ring())
