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
