"""Ask for offline_access, so a session outlives the hour.

Connecting Vercel produced a token with no refresh_token and expires_in 3600.
An hour later the cross-account probe found the session dead and there was
nothing to do but sign in again.

The cause is not Vercel's. Vercel documents that `offline_access` issues a
refresh token valid for 30 days with rotation, and its authorization server
advertises the scope. What happens is that the MCP scope selection strategy
takes the scope from the resource's `scopes_supported`, Vercel's resource
correctly omits `offline_access` there, and so it is never asked for.

MCP SEP-2207 ("OIDC-Flavored Refresh Token Guidance", Final) is about exactly
this: a resource SHOULD NOT advertise offline_access, and a client MAY add it
when the authorization server's metadata does. The Python SDK implements this
from 2.0.0. strands-agents pins mcp<2.0.0, so this is that rule applied here
until the pin lifts.
"""

from types import SimpleNamespace

from munim.remote.offline import with_offline_access


def _as(scopes):
    return SimpleNamespace(scopes_supported=scopes)


def test_offline_access_is_added_when_the_server_offers_it():
    """Vercel's shape: the resource says openid, the server also knows
    offline_access."""
    out = with_offline_access(
        "openid", _as(["openid", "email", "profile", "offline_access"]),
        grant_types=["authorization_code", "refresh_token"])

    assert out.split() == ["openid", "offline_access"]


def test_a_server_that_does_not_offer_it_is_left_alone():
    """Asking for a scope the server does not define is a rejected
    authorisation, in front of the operator at the consent screen."""
    out = with_offline_access(
        "openid", _as(["openid", "email"]),
        grant_types=["authorization_code", "refresh_token"])

    assert out == "openid"


def test_a_client_that_cannot_refresh_does_not_ask():
    """SEP-2207 gates on the client declaring the refresh_token grant. Asking
    for a refresh token you cannot exchange is asking for a longer-lived
    credential than you can use."""
    out = with_offline_access(
        "openid", _as(["openid", "offline_access"]),
        grant_types=["authorization_code"])

    assert out == "openid"


def test_it_is_not_added_twice():
    out = with_offline_access(
        "openid offline_access", _as(["openid", "offline_access"]),
        grant_types=["authorization_code", "refresh_token"])

    assert out.split().count("offline_access") == 1


def test_no_scope_stays_no_scope():
    """None means the strategy chose to omit the parameter. Turning that into
    a bare "offline_access" would narrow a request that was deliberately open."""
    out = with_offline_access(
        None, _as(["openid", "offline_access"]),
        grant_types=["authorization_code", "refresh_token"])

    assert out is None


def test_a_server_with_no_metadata_is_left_alone():
    assert with_offline_access("openid", None, grant_types=["refresh_token"]) == "openid"
