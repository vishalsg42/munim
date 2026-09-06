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


# ---- where to refresh, which the SDK only learns from a 401 --------------
#
# Recording the expiry made the refresh branch reachable. It reaches a URL no
# provider serves: `_refresh_token` reads `context.oauth_metadata`, and the only
# place in the SDK that assigns it is the branch that runs *after* a 401. So on
# any stored-token path it is None and the refresh falls back to
# `<mcp host>/token`. Resend answers that with 404 and its real endpoint is
# `api.resend.com/oauth/token`, which is one browser login per expiry.

import json


RESOURCE = json.dumps({"resource": "https://mcp.resend.com/mcp",
                       "authorization_servers": ["https://api.resend.com"]})

SERVER = json.dumps({
    "issuer": "https://api.resend.com",
    "authorization_endpoint": "https://api.resend.com/oauth/authorize",
    "token_endpoint": "https://api.resend.com/oauth/token",
    "response_types_supported": ["code"],
})


def expired(ring, provider="resend", **over):
    """A stored session whose access token died an hour ago."""
    store = KeychainTokenStorage("c_1", provider, ring)
    fields = {"expires_in": 3600, "refresh_token": "r"}
    fields.update(over)
    raw = {"access_token": "a", "token_type": "Bearer",
           ISSUED_AT: time.time() - 7200, **fields}
    ring.set_password(f"munim-mcp:{provider}:tokens", "c_1", json.dumps(raw))
    store.seed_client_info("id", "secret", "http://127.0.0.1:8976/callback")
    return store


class Answers(httpx.AsyncBaseTransport):
    """A transport that replies from a table and records what was asked."""

    def __init__(self, table):
        self.table = table
        self.asked = []

    async def handle_async_request(self, request):
        self.asked.append(request)
        body, status = self.table.get(str(request.url), ("", 404))
        return httpx.Response(status, content=body,
                              headers={"content-type": "application/json"})


def answering(monkeypatch, table):
    """Point the discovery client at `table` without touching the auth flow."""
    transport = Answers(table)
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return transport


PRM_ROOT = "https://mcp.resend.com/.well-known/oauth-protected-resource"
PRM_PATH = PRM_ROOT + "/mcp"
ASM = "https://api.resend.com/.well-known/oauth-authorization-server"
FOUND = {PRM_PATH: (RESOURCE, 200), ASM: (SERVER, 200)}


async def test_the_refresh_goes_where_discovery_said(monkeypatch):
    """The bug, in one assertion. Today this posts to mcp.resend.com/token,
    which is a 404, and a rejected refresh means a browser."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    request = await auth._refresh_token()

    assert str(request.url) == "https://api.resend.com/oauth/token", \
        "the refresh went to the MCP host, which does not serve that endpoint"
    assert b"grant_type=refresh_token" in request.content


async def test_the_lookup_happens_once_not_once_per_refresh(monkeypatch):
    """`oauth_metadata is None` is the memo. Without it every expired request
    pays for the same two documents again."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    asked = answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    await auth._refresh_token()
    spent = len(asked.asked)
    await auth._refresh_token()

    assert len(asked.asked) == spent, "the second refresh looked it up again"


async def test_the_path_based_document_is_tried_before_the_root(monkeypatch):
    """Supabase publishes only the path-based one. Root-first would find
    nothing there and the refresh would stay broken for it."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    asked = answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    await auth._refresh_token()

    assert str(asked.asked[0].url) == PRM_PATH


async def test_a_lookup_that_finds_nothing_leaves_the_refresh_as_it_was(
        monkeypatch):
    """A provider that publishes no metadata must be no worse off than today,
    and must not raise out of the auth flow."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    answering(monkeypatch, {})            # every well-known 404s
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    request = await auth._refresh_token()

    assert str(request.url) == "https://mcp.resend.com/token", \
        "a failed lookup should fall back, not invent an endpoint"


async def test_junk_metadata_is_ignored_rather_than_fatal(monkeypatch):
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    answering(monkeypatch, {PRM_PATH: ("not json at all", 200),
                            ASM: ("{}", 200)})
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    request = await auth._refresh_token()

    assert str(request.url) == "https://mcp.resend.com/token"


async def test_a_resource_speaking_for_another_server_is_not_adopted(
        monkeypatch):
    """The refresh carries the refresh token, and for a confidential client the
    secret too. Whatever `authorization_servers` names is where those go, so a
    document claiming another resource is refused rather than followed."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    elsewhere = json.dumps({"resource": "https://evil.test/",
                            "authorization_servers": ["https://evil.test"]})
    answering(monkeypatch, {PRM_PATH: (elsewhere, 200), ASM: (SERVER, 200)})
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    request = await auth._refresh_token()

    assert "evil.test" not in str(request.url), \
        "a refresh token was about to be sent to a host that just asked for it"


async def test_the_lookup_carries_no_bearer_token(monkeypatch):
    """These go to a different host than the access token was minted for."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    asked = answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    await auth._refresh_token()

    for request in asked.asked:
        assert "authorization" not in request.headers, \
            f"{request.url} was sent an access token it has no business seeing"


async def test_a_confidential_client_still_sends_its_secret(monkeypatch):
    """Supabase is confidential. Changing where the refresh goes must not
    change what it proves, and losing the secret would fail silently."""
    from munim.remote.session import auth_for

    ring = Ring()
    store = expired(ring, provider="supabase")
    store.seed_client_info("id", "secret", "http://127.0.0.1:8976/callback")
    supa_prm = "https://mcp.supabase.com/.well-known/oauth-protected-resource/mcp"
    resource = json.dumps({"resource": "https://mcp.supabase.com/mcp",
                           "authorization_servers": ["https://api.supabase.com"]})
    server = SERVER.replace("api.resend.com", "api.supabase.com")
    answering(monkeypatch, {
        supa_prm: (resource, 200),
        "https://api.supabase.com/.well-known/oauth-authorization-server":
            (server, 200)})
    auth = auth_for("c_1", "supabase", keyring=ring, allow_login=False)
    await auth._initialize()

    request = await auth._refresh_token()

    assert str(request.url) == "https://api.supabase.com/oauth/token"
    assert b"client_secret" in request.content, \
        "the refresh moved host and left its proof of identity behind"


async def test_a_valid_token_is_never_looked_up(monkeypatch):
    """The gate is `super()`'s, not ours: a fresh token never reaches a
    refresh, so it must never reach a lookup either."""
    from munim.remote.session import auth_for

    ring = Ring()
    store = KeychainTokenStorage("c_1", "resend", ring)
    await store.set_tokens(token())
    store.seed_client_info("id", "secret", "http://127.0.0.1:8976/callback")
    asked = answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    flow = auth.async_auth_flow(httpx.Request("GET", "https://mcp.resend.com/mcp"))
    await flow.__anext__()
    await flow.aclose()

    assert asked.asked == [], "a live session paid for a lookup it did not need"


async def test_a_first_connection_looks_nothing_up(monkeypatch):
    """No tokens means `can_refresh_token()` is False, so connecting is
    untouched by any of this."""
    from munim.remote.session import auth_for

    ring = Ring()
    asked = answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    assert auth.context.can_refresh_token() is False
    assert asked.asked == []


# ---- one refresher at a time, across processes ---------------------------
#
# These providers rotate: spending a refresh token invalidates it. Munim runs as
# a long-lived MCP server and as a CLI over one store, so two of them reading
# the same token and both posting it means one is accepted and one is rejected,
# and a rejected refresh is answered with a browser login.
#
# Theoretical until the endpoint fix above, because no refresh ever succeeded,
# so nothing ever rotated. Making them work is what makes them collide.

import asyncio as _asyncio


async def test_a_second_process_waits_rather_than_spending_the_same_token(
        monkeypatch, tmp_path):
    """The lock is a file, so this holds it the way another process would:
    from a separate open file description that knows nothing about ours."""
    from munim import vault

    monkeypatch.setenv("MUNIM_CREDENTIALS", str(tmp_path / "credentials.json"))
    theirs, ours = vault.Single("refresh-resend-c_1"), vault.Single("refresh-resend-c_1")

    assert await theirs.hold(0.2) is True
    assert await ours.hold(0.2) is False, \
        "two refreshers held the same session at once"

    theirs.release()
    assert await ours.hold(0.5) is True, "the lock was never handed back"
    ours.release()


async def test_waiting_does_not_block_the_probes_running_beside_it(
        monkeypatch, tmp_path):
    """`check_all` gathers every provider on one loop. A synchronous flock
    would stall all of them into their own timeouts while one waited."""
    from munim import vault

    monkeypatch.setenv("MUNIM_CREDENTIALS", str(tmp_path / "credentials.json"))
    theirs = vault.Single("refresh-resend-c_1")
    await theirs.hold(0.2)

    ticks = 0

    async def beside():
        nonlocal ticks
        while True:
            await _asyncio.sleep(0.01)
            ticks += 1

    other = _asyncio.ensure_future(beside())
    await vault.Single("refresh-resend-c_1").hold(0.3)
    other.cancel()
    theirs.release()

    assert ticks > 5, f"the loop was blocked while waiting: {ticks} ticks"


async def test_the_refresh_takes_the_lock_and_gives_it_back(monkeypatch):
    """Held across the POST and the write that follows it, and no longer."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    await auth._refresh_token()
    assert auth._holding is not None, "the refresh went out unserialised"

    await auth._handle_refresh_response(
        httpx.Response(200, json={"access_token": "b", "token_type": "Bearer",
                                  "expires_in": 900, "refresh_token": "r2"},
                       request=httpx.Request("POST", "https://api.resend.com/oauth/token")))
    assert auth._holding is None, "the next process would wait forever"


async def test_a_rejected_refresh_still_gives_the_lock_back(monkeypatch):
    """The failure path is the one that matters: a refresh that fails is
    followed by a browser login, and holding the lock through that would stop
    every other process renewing until this one finished signing in."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring)
    answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()

    await auth._refresh_token()
    await auth._handle_refresh_response(
        httpx.Response(400, json={"error": "invalid_grant"},
                       request=httpx.Request("POST", "https://api.resend.com/oauth/token")))

    assert auth._holding is None


async def test_the_refresh_uses_the_token_the_other_process_left_behind(
        monkeypatch):
    """The whole point. Waiting and then spending the token we read before the
    wait would rotate one the provider has already invalidated."""
    from munim.remote.session import auth_for

    ring = Ring()
    expired(ring, refresh_token="spent")
    answering(monkeypatch, FOUND)
    auth = auth_for("c_1", "resend", keyring=ring, allow_login=False)
    await auth._initialize()
    assert auth.context.current_tokens.refresh_token == "spent"

    # What the process we are waiting behind writes before it lets go.
    store = KeychainTokenStorage("c_1", "resend", ring)
    await store.set_tokens(token(access_token="theirs", refresh_token="fresh"))

    request = await auth._refresh_token()

    assert b"refresh_token=fresh" in request.content, \
        "the refresh spent a token another process had already invalidated"
