"""A one-hour token must not behave like a one-hour account.

Cloudflare and Vercel both grant `expires_in: 3600` with `offline_access` and a
refresh token, which should renew silently forever. Instead both sessions died
daily and demanded a browser.

The cause was not the provider. OAuth grants a *duration*; the SDK turns it into
an absolute time on the object it holds (`_TokenContext.update_token_expiry`),
and that object dies with the process. Nothing wrote the absolute time down, and
`_initialize` loads tokens from storage without setting it. Since

    not self.token_expiry_time or time.time() <= self.token_expiry_time

reads an unset expiry as valid, every fresh `munim` process believed a day-old
token, sent it, got a 401, and the SDK's 401 branch is a full authorization
rather than a refresh. The refresh token was never once used.
"""

import time

import httpx

import pytest
from mcp.shared.auth import OAuthToken

from munim.remote.storage import ISSUED_AT, KeychainTokenStorage


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


def token(**over):
    fields = {"access_token": "a", "token_type": "Bearer",
              "expires_in": 3600, "refresh_token": "r"}
    fields.update(over)
    return OAuthToken(**fields)


# ---- the store records when the token was issued ----------------------


async def test_storing_a_token_records_when_it_was_issued():
    """Without this there is nothing a later process could compute an age from."""
    store = KeychainTokenStorage("c_1", "cloudflare", Ring())
    before = time.time()
    await store.set_tokens(token())

    raw = store._read("tokens")
    assert ISSUED_AT in raw, "nothing recorded when this token was obtained"
    assert before <= raw[ISSUED_AT] <= time.time()


async def test_expires_at_is_the_issue_time_plus_the_granted_duration():
    store = KeychainTokenStorage("c_1", "cloudflare", Ring())
    await store.set_tokens(token(expires_in=3600))

    issued = store._read("tokens")[ISSUED_AT]
    assert store.expires_at() == pytest.approx(issued + 3600, abs=0.01)


async def test_the_bookkeeping_never_reaches_the_provider_model():
    """It rides in the same record and is popped back out, like `_seeded`."""
    store = KeychainTokenStorage("c_1", "cloudflare", Ring())
    await store.set_tokens(token())

    back = await store.get_tokens()
    assert back.access_token == "a"
    assert back.refresh_token == "r"
    assert not hasattr(back, ISSUED_AT)


async def test_a_token_stored_before_this_existed_reports_no_expiry():
    """Old records get the old behaviour rather than a guessed age.

    Inventing an issue time for a token whose age is genuinely unknown would
    either force a needless refresh or, worse, declare a live token dead.
    """
    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    await store.set_tokens(token())
    # Exactly what was on disk before the issue time was recorded.
    raw = store._read("tokens")
    raw.pop(ISSUED_AT)
    ring.set_password("munim-mcp:cloudflare:tokens", "c_1", __import__("json").dumps(raw))

    assert store.expires_at() is None


async def test_a_token_with_no_expires_in_reports_no_expiry():
    """Some grants omit it, and a duration that was never given cannot be added."""
    store = KeychainTokenStorage("c_1", "cloudflare", Ring())
    await store.set_tokens(token(expires_in=None))

    assert store.expires_at() is None


# ---- the client uses it, which is the half that was missing -----------


async def test_loading_tokens_restores_the_expiry_the_sdk_forgets():
    """`_initialize` sets current_tokens and not token_expiry_time. This is why."""
    from munim.remote.session import auth_for

    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    await store.set_tokens(token(expires_in=3600))

    auth = auth_for("c_1", "cloudflare", keyring=ring, allow_login=False)
    await auth._initialize()

    assert auth.context.token_expiry_time is not None, \
        "a fresh process cannot tell how old this token is"
    assert auth.context.token_expiry_time == pytest.approx(
        store.expires_at(), abs=0.01)


async def test_an_expired_token_is_reported_invalid_so_the_refresh_can_fire():
    """The whole bug in one assertion.

    `is_token_valid()` gates the refresh branch. It used to return True for a
    token stored a day ago, so the refresh never ran and a 401 sent the SDK to
    a browser login instead.
    """
    from munim.remote.session import auth_for

    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    await store.set_tokens(token(expires_in=3600))
    # Age it by a day, the way sleeping overnight does.
    raw = store._read("tokens")
    raw[ISSUED_AT] = time.time() - 86400
    ring.set_password("munim-mcp:cloudflare:tokens", "c_1", __import__("json").dumps(raw))

    # A real install has this from registration, and `can_refresh_token`
    # requires it alongside the refresh token itself.
    store.seed_client_info("id", "secret", "http://127.0.0.1:8976/callback")

    auth = auth_for("c_1", "cloudflare", keyring=ring, allow_login=False)
    await auth._initialize()

    assert auth.context.is_token_valid() is False
    assert auth.context.can_refresh_token() is True, \
        "there is a refresh token right here and it was never used"


async def test_a_fresh_token_is_still_valid_and_is_not_refreshed_needlessly():
    from munim.remote.session import auth_for

    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    await store.set_tokens(token(expires_in=3600))

    auth = auth_for("c_1", "cloudflare", keyring=ring, allow_login=False)
    await auth._initialize()

    assert auth.context.is_token_valid() is True


async def test_an_unknown_age_keeps_the_old_optimistic_behaviour():
    """A record written before the fix must not become permanently invalid."""
    from munim.remote.session import auth_for

    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    await store.set_tokens(token())
    raw = store._read("tokens")
    raw.pop(ISSUED_AT)
    ring.set_password("munim-mcp:cloudflare:tokens", "c_1", __import__("json").dumps(raw))

    auth = auth_for("c_1", "cloudflare", keyring=ring, allow_login=False)
    await auth._initialize()

    assert auth.context.token_expiry_time is None
    assert auth.context.is_token_valid() is True


# ---- several processes, one store, rotating refresh tokens ------------


async def test_a_request_re_reads_tokens_another_process_may_have_rotated():
    """Cloudflare rotates refresh tokens: using one invalidates it.

    Munim runs as a long-lived MCP server and as a CLI, so several processes
    share one store, each holding whatever it loaded at startup. When one
    refreshes, every other copy is dead on arrival, and the SDK answers a
    rejected refresh with a full browser authorization. That is the "authorize
    again, and again" this exists to stop.
    """
    from munim.remote.session import auth_for

    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    await store.set_tokens(token(access_token="first", refresh_token="r1"))
    store.seed_client_info("id", "secret", "http://127.0.0.1:8976/callback")

    auth = auth_for("c_1", "cloudflare", keyring=ring, allow_login=False)
    await auth._initialize()
    assert auth.context.current_tokens.access_token == "first"

    # Another process refreshes and rotates. Our copy is now stale.
    await store.set_tokens(token(access_token="second", refresh_token="r2"))

    flow = auth.async_auth_flow(httpx.Request("GET", "https://example.test"))
    await flow.__anext__()
    await flow.aclose()

    assert auth.context.current_tokens.access_token == "second", \
        "the request went out with a token another process had replaced"
    assert auth.context.current_tokens.refresh_token == "r2", \
        "a refresh would have used a token Cloudflare already invalidated"


async def test_the_expiry_is_re_read_along_with_the_tokens():
    """Adopting new tokens while keeping the old expiry would call a fresh
    token expired and refresh it for nothing, rotating again."""
    from munim.remote.session import auth_for

    ring = Ring()
    store = KeychainTokenStorage("c_1", "cloudflare", ring)
    await store.set_tokens(token())
    store.seed_client_info("id", "secret", "http://127.0.0.1:8976/callback")

    auth = auth_for("c_1", "cloudflare", keyring=ring, allow_login=False)
    await auth._initialize()
    aged = time.time() - 86400
    raw = store._read("tokens")
    raw[ISSUED_AT] = aged
    ring.set_password("munim-mcp:cloudflare:tokens", "c_1",
                      __import__("json").dumps(raw))
    auth.context.token_expiry_time = time.time() + 9999      # a stale belief

    flow = auth.async_auth_flow(httpx.Request("GET", "https://example.test"))
    await flow.__anext__()
    await flow.aclose()

    assert auth.context.token_expiry_time == pytest.approx(
        aged + 3600, abs=0.01), "the expiry came from memory, not the store"


async def test_nothing_is_re_read_before_the_first_initialize():
    """`_initialize` does the first load; doing it twice would be wasted IO."""
    from munim.remote.session import auth_for

    ring = Ring()
    auth = auth_for("c_1", "cloudflare", keyring=ring, allow_login=False)
    assert auth._initialized is False
    assert auth.context.current_tokens is None
