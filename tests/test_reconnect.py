"""Reconnect has to be a login, and it must not cost you the session.

Two reports, one after the other, and the second is the interesting one.

First: choosing Reconnect in `munim clients` "just refreshes the screen" and
never shows the OAuth URL. Opening a session is not authenticating. The MCP SDK
runs the browser flow only when storage hands it no usable token, so
reconnecting a provider whose session still worked opened it, succeeded, and
asked nobody anything.

Then, after the obvious fix of deleting the token first: *"when I haven't
completed the reconnect, why was it removed from the list? Until I have
completed it fully, then only it should be replaced."*

Exactly right, and the first fix had already proved it the hard way. Deleting
first means every failure path has to put it back, and one was missed:
`KeyboardInterrupt` is a BaseException, so a restore under `except Exception`
never ran. Closing the browser and pressing Ctrl+C disconnected the account
being repaired.

So nothing is deleted. The token is *hidden* from the one reader that decides
whether to log in, and every other read and every write goes to the real store.
A login that completes overwrites it; one that does not writes nothing.
"""

import json

import pytest

from munim.remote.storage import (SERVICE, KeychainTokenStorage,
                                  SessionNeedingLogin)


class Ring:
    """The vault, as far as one session is concerned."""

    def __init__(self):
        self.store = {}
        self.deleted = []

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret

    def delete_password(self, service, account):
        self.deleted.append((service, account))
        self.store.pop((service, account), None)


@pytest.fixture
def ring():
    r = Ring()
    r.set_password(f"{SERVICE}:cloudflare:tokens", "c_1",
                   json.dumps({"access_token": "live", "token_type": "Bearer"}))
    r.set_password(f"{SERVICE}:cloudflare:client", "c_1",
                   json.dumps({"client_id": "abc"}))
    r.set_password(f"{SERVICE}:cloudflare:account", "c_1",
                   json.dumps({"account": "a@b.test"}))
    return r


# ---- the view, which is the whole mechanism -------------------------------


def test_the_token_looks_absent_so_a_login_is_required(ring):
    view = SessionNeedingLogin("c_1", "cloudflare", ring)

    assert view.get_password(f"{SERVICE}:cloudflare:tokens", "c_1") is None


def test_but_it_is_still_there(ring):
    """The point. Nothing is deleted, so there is nothing to put back."""
    SessionNeedingLogin("c_1", "cloudflare", ring)

    assert ring.store[(f"{SERVICE}:cloudflare:tokens", "c_1")]
    assert ring.deleted == []


def test_the_registration_and_the_account_still_read(ring):
    """Only the token is hidden. Hiding the registration would ask the provider
    to register Munim again; hiding the account would drop the guard that
    checks this login is the account the client is bound to (D26)."""
    view = SessionNeedingLogin("c_1", "cloudflare", ring)

    assert view.get_password(f"{SERVICE}:cloudflare:client", "c_1")
    assert view.get_password(f"{SERVICE}:cloudflare:account", "c_1")


def test_another_client_is_not_affected(ring):
    """One reconnect must not look like a mass logout to anything else reading
    the store while it happens."""
    ring.set_password(f"{SERVICE}:cloudflare:tokens", "c_2", "someone else")
    view = SessionNeedingLogin("c_1", "cloudflare", ring)

    assert view.get_password(f"{SERVICE}:cloudflare:tokens", "c_2") == "someone else"


def test_another_provider_is_not_affected(ring):
    ring.set_password(f"{SERVICE}:vercel:tokens", "c_1", "vercel token")
    view = SessionNeedingLogin("c_1", "cloudflare", ring)

    assert view.get_password(f"{SERVICE}:vercel:tokens", "c_1") == "vercel token"


def test_a_completed_login_writes_through(ring):
    """The new token has to land in the real store, or the reconnect would
    succeed and change nothing."""
    view = SessionNeedingLogin("c_1", "cloudflare", ring)

    landed = json.dumps({"access_token": "the new one", "token_type": "Bearer"})
    view.set_password(f"{SERVICE}:cloudflare:tokens", "c_1", landed)

    assert (KeychainTokenStorage("c_1", "cloudflare", ring)
            ._read("tokens")["access_token"]) == "the new one"


# ---- the command ----------------------------------------------------------


def _registry_with(tmp_path, name="Acme Ltd"):
    from munim.registry import ClientRecord, Registry

    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name=name))
    return reg


def test_connecting_an_already_connected_provider_asks_for_a_login(monkeypatch,
                                                                   tmp_path):
    """`munim connect` printed "Opening your browser to log in", opened none,
    and reported success. There was no way to re-authenticate at all."""
    import munim.cli as cli

    monkeypatch.setattr(cli, "_registry", lambda: _registry_with(tmp_path))
    monkeypatch.setattr("munim.remote.identity.can_name_itself", lambda p: True)
    seen = {}

    async def logged_in(client, provider, *, label=None, **kwargs):
        seen["keyring"] = kwargs.get("keyring")
        return ["a_tool"], None

    monkeypatch.setattr("munim.remote.session.connect_and_identify", logged_in)

    cli.connect_via_mcp("Acme Ltd", "cloudflare")

    assert isinstance(seen["keyring"], SessionNeedingLogin), \
        "it connected with the ordinary store, so a live token was reused"


def test_cancelling_leaves_the_session_exactly_where_it_was(monkeypatch,
                                                            tmp_path, capsys):
    """The reported failure. Closing the browser and pressing Ctrl+C removed
    the account from the list, because the token had been deleted up front and
    `except Exception` does not catch a KeyboardInterrupt."""
    import munim.cli as cli

    monkeypatch.setattr(cli, "_registry", lambda: _registry_with(tmp_path))
    monkeypatch.setattr("munim.remote.identity.can_name_itself", lambda p: True)
    touched = []

    async def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr("munim.remote.session.connect_and_identify", interrupted)
    monkeypatch.setattr("munim.remote.storage.KeychainTokenStorage.forget",
                        lambda self: touched.append("forgot") or [])

    code = cli.connect_via_mcp("Acme Ltd", "cloudflare")

    assert code == cli.CANCELLED
    assert touched == [], "cancelling removed the session"
    assert "untouched" in capsys.readouterr().err


def test_a_first_connection_does_not_go_through_the_view(monkeypatch, tmp_path):
    """Connecting without naming a client authorises first and names after, so
    there is no session to protect and nothing to hide."""
    import munim.cli as cli

    monkeypatch.setattr(cli, "_registry", lambda: _registry_with(tmp_path))
    monkeypatch.setattr("munim.remote.identity.can_name_itself", lambda p: True)
    monkeypatch.setattr(cli, "adopt_provisional", lambda *a, **k: None)
    seen = {}

    async def logged_in(client, provider, *, label=None, **kwargs):
        seen["keyring"] = kwargs.get("keyring")
        return [], None

    monkeypatch.setattr("munim.remote.session.connect_and_identify", logged_in)
    monkeypatch.setattr("munim.remote.storage.KeychainTokenStorage.forget",
                        lambda self: [])

    cli.connect_via_mcp(None, "cloudflare")

    assert seen["keyring"] is None


# ---- the screen -----------------------------------------------------------


def test_the_screen_delegates_the_login_rather_than_repeating_it():
    """`connect_via_mcp` owns both halves: forcing the login, and leaving the
    old session alone if it does not happen. Repeating either in `browse` would
    be a second place to get it wrong."""
    import inspect

    import munim.browse as browse

    source = inspect.getsource(browse._reconnect)

    assert "connect_via_mcp" in source
    assert "take_tokens" not in source and "forget" not in source


# ---- and no command ends in a stack trace ---------------------------------


def test_cancelling_is_not_a_traceback(monkeypatch, capsys):
    """Backing out is a normal thing to do. A tool that prints sixty lines of
    asyncio internals when you do it teaches you not to."""
    import munim.cli as cli

    def interrupted(argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run", interrupted)

    code = cli.main([])

    assert code == cli.CANCELLED
    assert "Cancelled" in capsys.readouterr().err
