"""Two clients, one provider, no collision.

This is the property the whole multi-account claim rests on. A coding agent
holds one account per provider because one client id shares one token store.
A registration and a token set per client is what removes that, and if these
ever share a key the failure is silent: a call made as the wrong client, which
is the exact fault D5 exists to prevent.
"""

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from munim.remote.servers import SERVERS, server_for
from munim.remote.storage import KeychainTokenStorage


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret


def _token(value: str) -> OAuthToken:
    return OAuthToken(access_token=value, token_type="Bearer")


def _client_info(client_id: str) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=["http://localhost:8976/oauth/callback"],
    )


async def test_two_clients_hold_separate_tokens_for_one_provider():
    ring = FakeKeyring()
    a = KeychainTokenStorage("Balaji Roofings", "cloudflare", ring)
    b = KeychainTokenStorage("Kloudfirst", "cloudflare", ring)

    await a.set_tokens(_token("token-for-balaji"))
    await b.set_tokens(_token("token-for-kloudfirst"))

    assert (await a.get_tokens()).access_token == "token-for-balaji"
    assert (await b.get_tokens()).access_token == "token-for-kloudfirst"


async def test_two_clients_hold_separate_registrations():
    """Each client is its own registered application, which is why the provider
    has nothing to clobber."""
    ring = FakeKeyring()
    a = KeychainTokenStorage("Balaji Roofings", "cloudflare", ring)
    b = KeychainTokenStorage("Kloudfirst", "cloudflare", ring)

    await a.set_client_info(_client_info("client-id-a"))
    await b.set_client_info(_client_info("client-id-b"))

    assert (await a.get_client_info()).client_id == "client-id-a"
    assert (await b.get_client_info()).client_id == "client-id-b"


async def test_one_client_across_providers_does_not_collide():
    ring = FakeKeyring()
    cf = KeychainTokenStorage("Balaji Roofings", "cloudflare", ring)
    vc = KeychainTokenStorage("Balaji Roofings", "vercel", ring)

    await cf.set_tokens(_token("cloudflare-token"))
    await vc.set_tokens(_token("vercel-token"))

    assert (await cf.get_tokens()).access_token == "cloudflare-token"
    assert (await vc.get_tokens()).access_token == "vercel-token"


async def test_nothing_is_returned_before_anything_is_stored():
    ring = FakeKeyring()
    store = KeychainTokenStorage("Nobody", "cloudflare", ring)
    assert await store.get_tokens() is None
    assert await store.get_client_info() is None


def test_a_provider_without_an_mcp_server_is_absent_not_guessed():
    """Supabase has no entry. D11: absent, rather than a plausible URL."""
    assert server_for("supabase") is None
    assert server_for("cloudflare").url == "https://mcp.cloudflare.com/mcp"


def test_every_recorded_server_says_whether_it_needs_a_secret():
    """Because that decides whether registration can be silent, and a wrong
    answer here means a secret in a config file."""
    for provider, server in SERVERS.items():
        assert isinstance(server.public_client, bool), provider
        assert server.note, f"{provider} records no evidence for its entry"
        if server.auth == "url":
            # No single address: each installation gets its own and the path
            # carries the credential, so the URL is per client and lives in the
            # keychain rather than in this table.
            assert server.url == "", (
                f"{provider} identifies clients by their own endpoint, so a "
                f"shared URL here would be one client's secret in the source")
        else:
            assert server.url.startswith("https://"), provider


def test_the_consent_screen_names_the_client():
    """The account picker is the one step only a person can get right, so the
    application name they see has to say which client they are connecting."""
    from munim.remote.session import auth_for

    auth = auth_for("Balaji Roofings", "cloudflare", backend=FakeKeyring())
    assert auth.context.client_metadata.client_name == "Munim (Balaji Roofings)"


def test_every_provider_registers_as_a_public_client():
    """Measured, not read. All three return HTTP 201 with
    token_endpoint_auth_method `none` and no secret.

    Vercel is the reason this is asserted rather than assumed: its authorization
    server metadata omits `none` from token_endpoint_auth_methods_supported, so
    this code asked for client_secret_post and was handed a public client
    anyway. The metadata understates it, and only registering finds that out.
    """
    from munim.remote.session import auth_for

    for provider in ("cloudflare", "vercel", "resend"):
        auth = auth_for("X", provider, backend=FakeKeyring())
        assert auth.context.client_metadata.token_endpoint_auth_method == "none", provider


def test_a_provider_that_did_need_a_secret_would_ask_for_one():
    """None do today. The path stays because the next one might, and because a
    provider silently downgrading to a public client is a change worth noticing
    rather than a branch worth deleting."""
    import munim.remote.servers as servers_mod
    from munim.remote.servers import RemoteServer
    from munim.remote.session import auth_for

    confidential = RemoteServer(provider="acme", url="https://mcp.acme.example",
                                public_client=False, note="hypothetical")
    original = dict(servers_mod.SERVERS)
    servers_mod.SERVERS["acme"] = confidential
    try:
        auth = auth_for("X", "acme", backend=FakeKeyring())
        assert auth.context.client_metadata.token_endpoint_auth_method == "client_secret_post"
    finally:
        servers_mod.SERVERS.clear()
        servers_mod.SERVERS.update(original)


def test_every_server_entry_records_how_it_was_verified():
    """`not yet exercised` sat in this file for a provider whose registration
    turned out to work. A note that records a guess reads exactly like one that
    records a measurement."""
    from munim.remote.servers import SERVERS

    for provider, server in SERVERS.items():
        assert "confirmed" in server.note, (
            f"{provider} records no confirmation, so its entry is a guess")


def test_a_provider_with_no_mcp_server_is_refused_at_construction():
    from munim.remote.session import NoRemoteServer, auth_for

    with pytest.raises(NoRemoteServer, match="cloudflare, resend, vercel"):
        auth_for("X", "supabase", backend=FakeKeyring())


def test_both_flows_agree_on_the_redirect():
    """Two OAuth paths now share one listener. If they disagreed on the URI,
    one of them would register a redirect the provider then refuses."""
    from munim.connect.callback import redirect_uri
    from munim.connect.oauth import REDIRECT_URI
    from munim.remote.session import auth_for

    remote = auth_for("X", "cloudflare", backend=FakeKeyring())
    assert REDIRECT_URI == redirect_uri()
    assert str(remote.context.client_metadata.redirect_uris[0]) == redirect_uri()


def _routes(argv, monkeypatch):
    """Which connect path the CLI chooses, without running either."""
    from munim import cli

    taken = {}
    monkeypatch.setattr(cli, "connect_via_mcp",
                        lambda c, p: taken.update(path="mcp") or 0)
    monkeypatch.setattr(cli, "connect", lambda c, p: taken.update(path="app") or 0)
    cli.main(argv)
    return taken["path"]


def test_a_provider_with_an_mcp_server_needs_no_setup_by_default(monkeypatch):
    """The default has to be the path that works from a clean clone. Sending
    someone to register an application when they do not have to was the
    friction this project set out to remove, and for a while it was ours."""
    assert _routes(["connect", "Acme", "cloudflare"], monkeypatch) == "mcp"
    assert _routes(["connect", "Acme", "resend"], monkeypatch) == "mcp"
    assert _routes(["connect", "Acme", "vercel"], monkeypatch) == "mcp"


def test_a_provider_without_one_falls_back_to_an_application(monkeypatch):
    assert _routes(["connect", "Acme", "supabase"], monkeypatch) == "app"


def test_via_app_opts_out(monkeypatch):
    """For anyone who wants their own application name on the consent screen."""
    assert _routes(["connect", "Acme", "cloudflare", "--via-app"], monkeypatch) == "app"


def test_token_entry_reaches_neither_path(monkeypatch, capsys):
    """`--token` stores a pasted key and returns before any login is chosen.
    Asserting it "routes to the app path" was wrong, and the routing carried a
    condition for it that could never be true."""
    from munim import cli

    taken = {}
    monkeypatch.setattr(cli, "connect_via_mcp",
                        lambda c, p: taken.update(path="mcp") or 0)
    monkeypatch.setattr(cli, "connect", lambda c, p: taken.update(path="app") or 0)
    monkeypatch.setattr("builtins.input", lambda: "")

    assert cli.main(["connect", "Acme", "cloudflare", "--token"]) == 2
    assert taken == {}, "a pasted key should not start a browser login"


def test_the_listener_waits_as_long_as_the_sdk_does():
    """Undercutting it means giving up while the browser is still on the
    provider's login page and reporting that no callback arrived."""
    import inspect

    from mcp.client.auth import OAuthClientProvider

    from munim.remote.session import LOGIN_TIMEOUT

    sdk = inspect.signature(OAuthClientProvider.__init__).parameters["timeout"].default
    assert LOGIN_TIMEOUT >= sdk, (
        f"the listener gives up after {LOGIN_TIMEOUT}s and the SDK waits {sdk}s")
