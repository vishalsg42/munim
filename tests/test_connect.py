"""OAuth is how a client gets connected once and never again.

These test the properties that make the flow safe, not that it runs: PKCE is
actually PKCE, a forged callback is refused, and the token lands scoped to one
client so a dozen grants for the same provider can coexist - which is the whole
point and the thing no provider's own login can do.
"""

import base64
import hashlib
import urllib.parse

import pytest

from munim.connect.oauth import PROVIDERS, OAuthConnector, _pkce
from munim.connect.token import TokenConnector


class FakeKeychain:
    def __init__(self):
        self.store = {}

    def get(self, client, provider):
        return self.store.get((client, provider))

    def set(self, client, provider, secret):
        self.store[(client, provider)] = secret


def test_the_challenge_is_the_sha256_of_the_verifier():
    """If this is wrong the flow still 'works' against a lax provider and the
    protection PKCE exists for is silently absent."""
    verifier, challenge = _pkce()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge  # base64url, unpadded, per RFC 7636


def test_each_flow_gets_a_fresh_verifier():
    assert _pkce()[0] != _pkce()[0]


def test_the_authorize_url_asks_for_s256_and_our_own_redirect():
    url = OAuthConnector(FakeKeychain()).authorize_url(
        "cloudflare", "client-123", "state-abc", "challenge-xyz")
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"] == "challenge-xyz"
    assert params["response_type"] == "code"
    assert params["redirect_uri"].startswith("http://localhost:")
    # The verifier itself must never appear in a URL the browser sees.
    assert "code_verifier" not in params


def test_cloudflare_asks_for_the_scopes_it_needs_and_no_more():
    url = OAuthConnector(FakeKeychain()).authorize_url("cloudflare", "c", "s", "ch")
    scope = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["scope"]
    assert "dns_records:edit" in scope   # writing DNS is the job
    assert "offline_access" in scope     # so the grant survives a restart
    assert "user:edit" not in scope      # never ask for account mutation


def test_a_provider_with_no_oauth_endpoint_is_absent_not_faked():
    """Resend publishes no authorization endpoint. D11: absent, not stubbed."""
    assert "resend" not in PROVIDERS
    with pytest.raises(ValueError, match="no OAuth"):
        OAuthConnector(FakeKeychain()).connect("acme", "resend", "id")


def test_a_token_is_stored_against_one_client_only():
    keychain = FakeKeychain()
    TokenConnector(keychain).connect("acme", "resend", "re_secret")
    assert keychain.get("acme", "resend") == "re_secret"
    # The same provider for another client is untouched: that separation is the
    # product.
    assert keychain.get("bharat", "resend") is None


def test_two_clients_hold_grants_for_the_same_provider_at_once():
    keychain = FakeKeychain()
    connector = TokenConnector(keychain)
    connector.connect("acme", "resend", "acme-key")
    connector.connect("bharat", "resend", "bharat-key")
    assert keychain.get("acme", "resend") == "acme-key"
    assert keychain.get("bharat", "resend") == "bharat-key"


def test_an_empty_credential_is_refused():
    with pytest.raises(ValueError):
        TokenConnector(FakeKeychain()).connect("acme", "resend", "   ")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_a_stray_request_does_not_cost_the_login(monkeypatch):
    """The listener has to survive traffic that is not the callback.

    Browsers speculatively fetch /favicon.ico and probe localhost ports. When
    the listener served exactly one request, the first of those consumed it and
    the operator's login failed with "no callback received" - having received
    one.
    """
    import contextlib
    import urllib.request

    from munim.connect import oauth

    def browser(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        with contextlib.suppress(Exception):  # 404, and correctly ignored
            urllib.request.urlopen(f"{oauth.REDIRECT_URI}/../favicon.ico", timeout=5)
        urllib.request.urlopen(
            f"{oauth.REDIRECT_URI}?code=abc&state={query['state']}", timeout=5
        ).read()

    monkeypatch.setattr(oauth.webbrowser, "open", browser)
    monkeypatch.setattr(oauth.httpx, "post",
                        lambda *a, **k: _FakeResponse({"access_token": "tok",
                                                       "team_id": "team_x"}))

    keychain = FakeKeychain()
    account = OAuthConnector(keychain).connect("Acme", "vercel", "cid", "secret",
                                               timeout=15)
    assert keychain.get("Acme", "vercel") == "tok"
    assert account == "team_x"


def test_vercel_uses_the_integration_install_flow_not_sign_in_with_vercel():
    """Two different Vercel systems, two different client id shapes.

    `https://vercel.com/oauth/authorize` belongs to "Sign in with Vercel" OAuth
    apps (`cl_...`). Handed an Integration's `oac_...` id it answers "The app ID
    is invalid", and even on success it returns identity claims rather than
    access to a team's projects, domains and environment variables.
    """
    url = OAuthConnector(FakeKeychain()).authorize_url(
        "vercel", "oac_abc", "state-abc", "challenge-xyz")
    assert url.startswith("https://vercel.com/integrations/")
    assert "/oauth/authorize" not in url
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    # The console holds the scopes and the slug names the app, so state is the
    # only thing that legitimately travels in this URL.
    assert params == {"state": "state-abc"}


def test_a_shipped_client_id_is_only_ever_for_a_public_client():
    """Munim ships client ids so a browser login needs no registration errand.

    That is only safe where the provider's flow is a public PKCE client, whose
    id is public by design. A provider that needs a secret cannot have one: the
    secret would have to ship too, and a secret in a public repository is not a
    default, it is a leak.
    """
    from munim.connect.oauth import SHIPPED_CLIENT_IDS

    for provider in SHIPPED_CLIENT_IDS:
        assert provider in PROVIDERS, f"{provider} ships an id but has no flow"
        assert not PROVIDERS[provider].needs_client_secret, (
            f"{provider} needs a client secret, so its id must not be shipped")


def test_the_environment_still_wins_over_a_shipped_id(monkeypatch):
    """Anyone who would rather see their own application name on the consent
    screen registers their own and sets it."""
    from munim import cli

    monkeypatch.setattr(cli, "SHIPPED_CLIENT_IDS", {"cloudflare": "shipped-id"})
    monkeypatch.delenv("CLOUDFLARE_OAUTH_CLIENT_ID", raising=False)
    assert cli._client_id("cloudflare")[0] == "shipped-id"

    monkeypatch.setenv("CLOUDFLARE_OAUTH_CLIENT_ID", "mine")
    assert cli._client_id("cloudflare")[0] == "mine"


def _flow(monkeypatch, keychain, *, extra_callback_params=""):
    """Drive a real connect() with the browser step faked."""
    import contextlib
    import urllib.request

    from munim.connect import oauth

    def browser(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        with contextlib.suppress(Exception):
            urllib.request.urlopen(
                f"{oauth.REDIRECT_URI}?code=abc&state={query['state']}"
                f"{extra_callback_params}", timeout=5).read()

    monkeypatch.setattr(oauth.webbrowser, "open", browser)
    monkeypatch.setattr(oauth.httpx, "post",
                        lambda *a, **k: _FakeResponse({"access_token": "tok"}))
    return OAuthConnector(keychain)


def test_a_response_from_the_wrong_issuer_is_discarded(monkeypatch):
    """RFC 9207. State proves the response answers our request; the issuer
    proves it came from the server we sent the user to. Holding a dozen grants
    across four providers, a response from the wrong issuer is a mix-up attack,
    and the code must never be exchanged."""
    keychain = FakeKeychain()
    connector = _flow(monkeypatch, keychain,
                      extra_callback_params="&iss=https://evil.example")

    with pytest.raises(ValueError, match="issuer mismatch"):
        connector.connect("Acme", "cloudflare", "cid", timeout=15)
    assert keychain.get("Acme", "cloudflare") is None, "a token was stored anyway"


def test_the_right_issuer_is_accepted(monkeypatch):
    keychain = FakeKeychain()
    connector = _flow(monkeypatch, keychain,
                      extra_callback_params="&iss=https://dash.cloudflare.com")
    connector.connect("Acme", "cloudflare", "cid", timeout=15)
    assert keychain.get("Acme", "cloudflare") == "tok"


def test_no_issuer_in_the_response_still_proceeds(monkeypatch):
    """RFC 9207 keys rejection on the server advertising the parameter. Absent
    and unadvertised means proceed, or every provider that has not adopted it
    yet would stop working."""
    keychain = FakeKeychain()
    connector = _flow(monkeypatch, keychain)
    connector.connect("Acme", "cloudflare", "cid", timeout=15)
    assert keychain.get("Acme", "cloudflare") == "tok"


# ---- a tool listing is not a session ------------------------------------
#
# `munim connect personal gmail` printed "Connected gmail for personal: 23
# tools." and `munim clients` said "nothing connected" about the same client on
# the next line. Both were reading honestly.
#
# Gmail's MCP server answers tools/list with 200 and no authentication, so a
# connect where the browser flow never completed still listed twenty-three
# tools and took that as success. The registration is seeded before the browser
# opens, so a token was the only thing missing and nothing looked at it.

def _registry_with(tmp_path, name="personal"):
    from munim.registry import ClientRecord, Registry
    registry = Registry(tmp_path / "registry.json")
    registry.add(ClientRecord(name=name))
    return registry


def test_a_connect_that_stored_no_token_is_not_a_connection(tmp_path, monkeypatch, capsys):
    from munim import cli

    registry = _registry_with(tmp_path)
    monkeypatch.setattr(cli, "_registry", lambda: registry)

    async def listed_tools_but_never_logged_in(client, provider, **kwargs):
        return ["one"] * 23, None

    from munim.remote import session as session_mod
    monkeypatch.setattr(session_mod, "connect_and_identify",
                        listed_tools_but_never_logged_in)

    class OnlyTheRegistration:
        def __init__(self, client, provider, keyring=None): pass
        def holds(self): return ["client"]          # seeded before the browser
        def account(self): return None
        def remember_account(self, account): pass
        def forget(self): return []
        def move_to(self, other): pass

    from munim.remote import storage as storage_mod
    monkeypatch.setattr(storage_mod, "KeychainTokenStorage", OnlyTheRegistration)

    code = cli.connect_via_mcp("personal", "gmail")
    said = capsys.readouterr().err

    assert code == 2, "reported success with no token stored"
    assert "nothing is connected" in said
    assert "23 tools" not in said, "counted tools it could read without logging in"


def test_a_connect_that_stored_a_token_still_succeeds(tmp_path, monkeypatch, capsys):
    """The guard must not refuse a real login."""
    from munim import cli

    registry = _registry_with(tmp_path)
    monkeypatch.setattr(cli, "_registry", lambda: registry)

    async def logged_in(client, provider, **kwargs):
        return ["one"] * 23, None

    from munim.remote import session as session_mod
    monkeypatch.setattr(session_mod, "connect_and_identify", logged_in)

    class ARealSession:
        def __init__(self, client, provider, keyring=None): pass
        def holds(self): return ["client", "tokens"]
        def account(self): return None
        def remember_account(self, account): pass
        def forget(self): return []
        def move_to(self, other): pass

    from munim.remote import storage as storage_mod
    monkeypatch.setattr(storage_mod, "KeychainTokenStorage", ARealSession)

    code = cli.connect_via_mcp("personal", "gmail")
    said = capsys.readouterr().err

    assert code == 0
    assert "23 tools" in said
