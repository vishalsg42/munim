"""A registration that issues a secret must remember how to send it.

Found by connecting Supabase for real. Registration succeeded, the operator
authorised, and the token exchange came back:

    Token exchange failed (422): {"message":"Required parameter: client_secret"}

The secret was there all along, 44 characters of it, sitting in the keychain.
What was missing was `token_endpoint_auth_method`: Munim asks for
`client_secret_post`, Supabase's registration response omits the field, and the
response is what gets stored. At token exchange the client reads a null auth
method, concludes it is a public client, and sends no secret.

RFC 7591 says the default when the field is absent is `client_secret_basic`, so
"absent" never means "public" for a client that was issued a secret. A stored
registration holding a secret and no method is the one combination that cannot
be right.

Cloudflare never caught this because it is a public client and has no secret to
forget.
"""

import json

import pytest
from mcp.shared.auth import OAuthClientInformationFull

from munim.remote.storage import KeychainTokenStorage


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


def _info(**kw):
    base = dict(client_id="an-id",
                redirect_uris=["http://localhost:8976/oauth/callback"])
    base.update(kw)
    return OAuthClientInformationFull(**base)


async def test_a_secret_without_a_method_is_stored_with_one():
    """The regression, in the shape Supabase actually returned it."""
    ring = Ring()
    store = KeychainTokenStorage("c_abc", "supabase", ring)

    await store.set_client_info(
        _info(client_secret="s" * 44, token_endpoint_auth_method=None))

    saved = store._read("client")
    assert saved["client_secret"] == "s" * 44
    assert saved["token_endpoint_auth_method"] is not None, (
        "a client with a secret and no auth method sends no secret")
    # Not client_secret_basic: that moves the secret into an Authorization
    # header and out of the body, which is the parameter Supabase requires.
    assert saved["token_endpoint_auth_method"] == "client_secret_post"


async def test_a_method_the_server_did_state_is_left_alone():
    """Only the absent case is filled in. A server that answers is obeyed."""
    ring = Ring()
    store = KeychainTokenStorage("c_abc", "supabase", ring)

    await store.set_client_info(
        _info(client_secret="s" * 44,
              token_endpoint_auth_method="client_secret_basic"))

    assert store._read("client")["token_endpoint_auth_method"] == "client_secret_basic"


async def test_a_public_client_stays_public():
    """No secret means nothing to send, and inventing a method would make a
    working public client start failing. Cloudflare is one of these."""
    ring = Ring()
    store = KeychainTokenStorage("c_abc", "cloudflare", ring)

    await store.set_client_info(_info(token_endpoint_auth_method="none"))

    saved = store._read("client")
    assert saved["token_endpoint_auth_method"] == "none"
    assert not saved.get("client_secret")


async def test_round_trips_back_as_a_usable_registration():
    """It has to survive the read as well as the write, because the read is
    what the token exchange actually uses."""
    ring = Ring()
    store = KeychainTokenStorage("c_abc", "supabase", ring)
    await store.set_client_info(
        _info(client_secret="s" * 44, token_endpoint_auth_method=None))

    back = await store.get_client_info()
    assert back.client_secret == "s" * 44
    assert back.token_endpoint_auth_method


async def test_the_caller_sees_the_correction_too():
    """The one that actually mattered.

    The SDK keeps the object it passes here and performs the token exchange
    with that instance, not with what was written to the keychain. Correcting a
    copy left the exchange still holding the null auth method, so the first
    connect after registration failed every time and only a second one worked.
    """
    ring = Ring()
    store = KeychainTokenStorage("c_abc", "supabase", ring)
    info = _info(client_secret="s" * 44, token_endpoint_auth_method=None)

    await store.set_client_info(info)

    assert info.token_endpoint_auth_method == "client_secret_post", (
        "the caller's own object was left with a null auth method")
