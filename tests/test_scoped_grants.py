"""Ask each provider for what Munim uses, not for everything it offers.

Nothing set a scope on the MCP path, so the request carried whatever the
provider advertised. Connecting Supabase asked for database:write,
storage:write, edge_functions:write, environment:write and secrets:read, for a
tool that had never written to Supabase at all. Gmail is where that stops being
untidy and becomes indefensible: its advertised set includes
https://mail.google.com/, which is read, send and delete on the whole mailbox.

A tool whose pitch is credential isolation asking for everything on offer
undercuts the pitch.
"""

import pytest

from munim.remote.servers import SERVERS


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c


def test_gmail_does_not_ask_for_the_whole_mailbox():
    """https://mail.google.com/ is read, send and delete on everything. Munim
    reads mail setup; it does not need to be able to empty an inbox."""
    scopes = SERVERS["gmail"].scopes
    assert scopes, "gmail asks for whatever Google advertises"
    assert "https://mail.google.com/" not in scopes


def test_the_mcp_route_sets_no_scope_and_that_is_deliberate(monkeypatch):
    """This asserted the opposite and passed, which was worse than no test.

    It inspected client_metadata.scope after auth_for built it and before the
    flow ran. The flow then discards it: the MCP spec defines a Scope Selection
    Strategy and the SDK implements it in mcp/client/auth/utils.py, taking the
    scope from the WWW-Authenticate challenge, else the resource's
    scopes_supported, else the authorization server's.

    Measured against the real thing: Vercel's resource advertises only
    "openid", so the authorize URL carried scope=openid no matter what was set
    here, and the session came back with no refresh token.

    So the assertion is that nothing is set, because setting it would read as a
    narrowing that is not happening.
    """
    from munim.remote.session import auth_for

    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "an-id.apps.googleusercontent.com")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "a-secret")

    auth = auth_for("c_x", "gmail", label="Acme", backend=Ring())

    assert auth.context.client_metadata.scope is None


def test_the_application_route_does_honour_them():
    """The route that builds its own authorize URL, so the ask is ours."""
    from munim.connect.oauth import PROVIDERS

    spec = PROVIDERS.get("cloudflare")
    assert spec is not None and spec.scopes
    assert "offline_access" in spec.scopes, (
        "the app route controls scope, so it is the one place a missing "
        "offline_access is our fault rather than the provider's")


def test_an_unscoped_provider_sends_none():
    """Absent means "whatever you advertise", which is right for a provider
    whose scopes have not been reviewed yet. It must not become an empty
    string, which some servers read as "no access at all"."""
    from munim.remote.session import auth_for

    assert not SERVERS["linear"].scopes, "linear now has scopes; pick another"
    auth = auth_for("c_x", "linear", label="Acme", backend=Ring())

    assert auth.context.client_metadata.scope is None


def test_every_scope_asked_for_is_one_the_provider_offers():
    """A scope the server does not recognise is a rejected authorisation, and
    it fails at the consent screen in front of the operator."""
    advertised = {
        "gmail": {
            "https://mail.google.com/",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.metadata",
        },
    }
    for provider, offered in advertised.items():
        asked = set(SERVERS[provider].scopes)
        assert asked <= offered, (
            f"{provider} asks for {sorted(asked - offered)}, which it does not offer")


def test_vercel_is_recorded_from_what_registration_does():
    """It is a public client, and every document says otherwise.

    mcp.vercel.com advertises token_endpoint_auth_methods_supported ['none'];
    vercel.com advertises ['client_secret_basic', 'client_secret_post', ...];
    and the protected resource names vercel.com, so RFC 9728 points at the
    document that is wrong in practice.

    Registering against either endpoint returns HTTP 201 with
    token_endpoint_auth_method 'none' and no secret. This assertion exists
    because the entry was changed to confidential once on the strength of the
    metadata, and the suite caught it.
    """
    assert SERVERS["vercel"].public_client is True


def test_narrowing_never_costs_the_refresh_token():
    """The trap in scoping a provider down.

    Vercel narrowed to "openid", which is the only scope its resource document
    advertises, and the session that came back had no refresh token: an hour of
    life and then a full browser login to recover. Its authorization server
    advertises offline_access even though the resource does not.

    Cloudflare never hit this because it sends no scope list and its server
    grants offline_access by default. So the failure only appears once somebody
    starts narrowing, which is exactly when nobody is looking for it.
    """
    for provider in ("vercel",):
        scopes = SERVERS[provider].scopes
        assert "offline_access" in scopes, (
            f"{provider} narrows its scopes but drops offline_access, so its "
            f"session cannot refresh")


def test_gmail_is_exempt_because_google_does_it_differently():
    """Google issues refresh tokens from access_type=offline, a request
    parameter, not from an offline_access scope. Asking for the scope would be
    asking for one Google does not define."""
    assert "offline_access" not in SERVERS["gmail"].scopes
