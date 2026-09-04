"""Providers that identify a client by their own endpoint.

Zoho issues a per-installation URL of the shape
`https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message`. The hex in the path
is the credential, so there is no OAuth, nothing to open a browser for, and one
address per client rather than one per provider.

That makes the URL a secret, and the two things that follow are what these pin:
it belongs in the keychain rather than in servers.json, which is a list of
servers and gets shared; and it must never be printed whole, because a terminal
gets pasted into a bug report.
"""

import pytest

from munim.remote.servers import RemoteServer
from munim.remote.session import NoRemoteServer, endpoint_for
from munim.remote.storage import KeychainTokenStorage

SECRET_URL = "https://zohoall-60075079101.zohomcp.in/mcp/113ec6dfc90b8a99b056a67548706c05/message"


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


@pytest.fixture
def zoho(monkeypatch):
    import munim.remote.servers as mod
    monkeypatch.setitem(mod.SERVERS, "zoho", RemoteServer(
        provider="zoho", url="", public_client=False, auth="url",
        note="confirmed: the path carries the credential"))


def test_the_endpoint_comes_from_the_keychain_not_the_server_table(zoho):
    ring = Ring()
    KeychainTokenStorage("c_1", "zoho", ring).remember_endpoint(SECRET_URL)
    assert endpoint_for("c_1", "zoho", ring) == SECRET_URL


def test_two_clients_keep_different_endpoints(zoho):
    """The whole multi-account property, in the shape this provider uses."""
    ring = Ring()
    KeychainTokenStorage("c_1", "zoho", ring).remember_endpoint(SECRET_URL)
    KeychainTokenStorage("c_2", "zoho", ring).remember_endpoint(
        "https://zohoall-999.zohomcp.in/mcp/deadbeef/message")
    assert endpoint_for("c_1", "zoho", ring) != endpoint_for("c_2", "zoho", ring)


def test_a_client_with_no_endpoint_is_told_how_to_add_one(zoho):
    with pytest.raises(NoRemoteServer, match="--url"):
        endpoint_for("c_nobody", "zoho", Ring())


def test_a_normal_provider_still_uses_the_server_address():
    assert endpoint_for("c_1", "cloudflare", Ring()) == "https://mcp.cloudflare.com/mcp"


def test_the_secret_path_is_never_printed():
    """A terminal gets pasted into a bug report."""
    from munim.cli import _redacted

    shown = _redacted(SECRET_URL)
    assert "113ec6dfc90b8a99b056a67548706c05" not in shown
    assert "zohoall-60075079101.zohomcp.in" in shown, \
        "redacting the host too would make it useless"


def test_the_endpoint_follows_a_rename(zoho):
    """Renaming a client must not orphan a credential that is a URL any more
    than one that is a token."""
    ring = Ring()
    store = KeychainTokenStorage("c_old", "zoho", ring)
    store.remember_endpoint(SECRET_URL)
    store.move_to("c_new")
    assert KeychainTokenStorage("c_new", "zoho", ring).endpoint() == SECRET_URL
    assert KeychainTokenStorage("c_old", "zoho", ring).endpoint() is None


class _Session:
    """A session that says which account it is, the way a provider would."""
    def __init__(self, account):
        self._account = account

    async def call_tool(self, name, args):
        import types
        text = f'[{{"id": "x", "name": "{self._account}"}}]'
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=text)])


async def test_a_session_on_another_account_is_refused():
    """The failure this exists for, and it happened on a real machine.

    A browser opened for one client while Chrome was signed in to a different
    provider account, and the authorisation went there. The client id was still
    right and the stored name was still right, so nothing about the record
    looked wrong: only the token had moved. Checked on every session rather
    than at connect, because connect is not when it goes wrong.
    """
    from munim.remote.session import WrongAccount, _verify_account

    ring = Ring()
    KeychainTokenStorage("c_1", "cloudflare", ring).remember_account("Theirs")

    with pytest.raises(WrongAccount, match="Theirs"):
        await _verify_account(_Session("Somebody Else"), "c_1", "cloudflare", ring)


async def test_the_right_account_passes():
    from munim.remote.session import _verify_account

    ring = Ring()
    KeychainTokenStorage("c_1", "cloudflare", ring).remember_account("Theirs")
    await _verify_account(_Session("Theirs"), "c_1", "cloudflare", ring)


async def test_a_first_session_records_the_account_it_landed_on():
    """Nothing to compare against yet, so there is nothing to refuse. Recording
    it is what makes the next session checkable."""
    from munim.remote.session import _verify_account

    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    assert store.account() is None

    await _verify_account(_Session("Theirs"), "c_1", "cloudflare", ring)
    assert store.account() == "Theirs"


async def test_the_refusal_says_how_to_fix_it():
    from munim.remote.session import WrongAccount, _verify_account

    ring = Ring()
    KeychainTokenStorage("c_1", "cloudflare", ring).remember_account("Theirs")
    with pytest.raises(WrongAccount) as caught:
        await _verify_account(_Session("Wrong"), "c_1", "cloudflare", ring)
    said = str(caught.value)
    assert "Nothing was read or changed" in said
    assert "munim connect" in said


async def test_connecting_is_allowed_to_change_the_account():
    """The guard must not block its own remedy.

    Being bound to the wrong account is fixed by connecting again, and if that
    path is verified against the account it is trying to replace, it refuses
    forever. Connecting is the one moment the answer is allowed to change,
    because it is the moment the operator is saying what it should be.
    """
    import inspect

    from munim.remote.session import connect_and_identify

    source = inspect.getsource(connect_and_identify)
    assert "verify=False" in source, \
        "connecting goes through the guard and cannot rebind a wrong account"


def test_forgetting_a_session_removes_everything_about_it():
    """A registration left behind is a client the provider still knows, and a
    remembered account left behind would be compared against the next session
    and refuse it."""
    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    ring.set_password(store._service("tokens"), "c_1", '{"access_token": "t"}')
    ring.set_password(store._service("client"), "c_1", '{"client_id": "x"}')
    store.remember_account("Theirs")
    store.remember_endpoint("https://x.test/mcp/secret/message")

    gone = store.forget()

    assert set(gone) == {"tokens", "client", "account", "endpoint"}
    assert store._read("tokens") is None
    assert store.account() is None
    assert store.endpoint() is None


def test_forgetting_what_was_never_there_removes_nothing():
    assert KeychainTokenStorage("c_nobody", "cloudflare", Ring()).forget() == []
