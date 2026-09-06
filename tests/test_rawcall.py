"""The one tool whose only boundary is code in this repository.

Every other tool is bounded by a schema somebody else wrote. This one sends a
client's live credential at a URL the caller supplies, and `base_url` does not
contain it: httpx honours an absolute URL over the base and takes the
`Authorization` header along. So the refusals are the feature, and they are
tested harder than the happy path.
"""

import httpx
import pytest

from munim.container import Container, UnsupportedProvider
from munim.remote.rawcall import UnsafePath, call, check_path


class Keys:
    def __init__(self, secret="sk-live"): self.secret = secret
    def get(self, client, provider): return self.secret
    def set(self, client, provider, secret): self.secret = secret


# ---- the refusals ------------------------------------------------------


@pytest.mark.parametrize("path", [
    "https://evil.test/x",
    "http://evil.test/x",
    "HTTPS://evil.test/x",          # a string test on "https://" misses this
    "https://api.vercel.com/x",     # even the right host, because it is a URL
])
def test_an_absolute_url_is_refused(path):
    """The one that matters. httpx hands an absolute URL straight through and
    the client's bearer token goes with it, in cleartext if the scheme is http."""
    with pytest.raises(UnsafePath, match="absolute URL"):
        check_path("vercel", path)


def test_httpx_really_does_let_an_absolute_url_escape():
    """The premise, asserted rather than trusted, because the guard above is
    only necessary if this stays true and httpx is pinned with no upper bound."""
    built = httpx.AsyncClient(base_url="https://api.vercel.com").build_request(
        "GET", "https://evil.test/x")
    assert built.url.host == "evil.test", \
        "httpx now contains absolute URLs; the guard can be reconsidered"


def test_something_that_looks_like_a_host_is_refused():
    with pytest.raises(UnsafePath, match="looks like a host"):
        check_path("vercel", "//evil.test/x")


def test_a_path_must_start_with_a_slash():
    with pytest.raises(UnsafePath, match="must start with"):
        check_path("vercel", "v9/projects")


def test_an_empty_path_is_refused():
    with pytest.raises(UnsafePath):
        check_path("vercel", "   ")


def test_a_provider_with_no_api_profile_is_refused():
    """Inventing a base URL for the other eight would be guessing."""
    with pytest.raises(UnsupportedProvider, match="supabase"):
        check_path("supabase", "/v1/projects")


def test_an_ordinary_path_is_allowed():
    assert check_path("vercel", "/v9/projects") == "/v9/projects"
    assert check_path("cloudflare", "/zones") == "/zones"


def test_traversal_stays_on_the_provider():
    """Not a host escape, and worth pinning: it normalises rather than
    escaping, so the credential cannot leave even by this route."""
    built = httpx.AsyncClient(base_url="https://api.vercel.com").build_request(
        "GET", check_path("vercel", "/v9/../../x"))
    assert built.url.host == "api.vercel.com"


# ---- the call ----------------------------------------------------------


class Recorder(httpx.AsyncBaseTransport):
    def __init__(self, status=200, payload=b'{"ok": true}'):
        self.seen = []
        self.status, self.payload = status, payload

    async def handle_async_request(self, request):
        self.seen.append(request)
        return httpx.Response(self.status, content=self.payload,
                              headers={"content-type": "application/json"})


def _boxed(monkeypatch, transport):
    box = Container("c_1", Keys())
    real = httpx.AsyncClient

    def client(*a, **k):
        k["transport"] = transport
        return real(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return box


class Log:
    def __init__(self): self.events = []
    def append(self, **kw): self.events.append(kw)


async def test_a_get_reaches_the_provider_with_the_credential(monkeypatch):
    seen = Recorder()
    box = _boxed(monkeypatch, seen)

    result = await call(box, "vercel", "/v9/projects")

    assert result["status"] == 200 and result["result"] == {"ok": True}
    assert str(seen.seen[0].url) == "https://api.vercel.com/v9/projects"
    assert seen.seen[0].headers["authorization"] == "Bearer sk-live"


async def test_every_call_is_a_mutation_in_the_log_whatever_the_method(
        monkeypatch):
    """"Read-only by default" would really be "GET by default", and an HTTP
    verb is a convention, not an annotation. `passthrough` only claims
    `observation` when the provider said `readOnlyHint`."""
    box = _boxed(monkeypatch, Recorder())
    log = Log()

    await call(box, "vercel", "/v9/projects", log=log)

    assert [e["kind"] for e in log.events] == ["mutation"]


async def test_the_response_body_is_never_written_to_the_log(monkeypatch):
    """A raw environment endpoint returns the secret values the Vercel adapter
    deliberately drops (D6). The log says what was asked, not what came back."""
    secret = b'{"envs": [{"key": "STRIPE_KEY", "value": "sk_live_swordfish"}]}'
    box = _boxed(monkeypatch, Recorder(payload=secret))
    log = Log()

    result = await call(box, "vercel", "/v9/projects/p/env", log=log)

    assert "sk_live_swordfish" in str(result["result"]), \
        "the caller asked for it and should get it"
    assert "swordfish" not in str(log.events), \
        "a secret reached the run log"


async def test_the_request_body_is_recorded_so_a_change_can_be_traced(
        monkeypatch):
    box = _boxed(monkeypatch, Recorder())
    log = Log()

    await call(box, "vercel", "/v9/projects/p/env", method="POST",
               body={"key": "FEATURE_FLAG", "value": "on"}, log=log)

    assert "FEATURE_FLAG" in log.events[0]["detail"]["body"]
    assert log.events[0]["detail"]["method"] == "POST"


async def test_a_provider_error_is_returned_rather_than_raised(monkeypatch):
    box = _boxed(monkeypatch, Recorder(status=403, payload=b'{"error": "no"}'))

    result = await call(box, "vercel", "/v9/projects")

    assert result["failed"] is True and result["status"] == 403
    assert result["result"] == {"error": "no"}


async def test_an_unknown_method_is_refused_before_anything_is_sent(monkeypatch):
    seen = Recorder()
    box = _boxed(monkeypatch, seen)

    with pytest.raises(ValueError, match="not an HTTP method"):
        await call(box, "vercel", "/v9/projects", method="TRACE")
    assert seen.seen == []


async def test_a_non_json_answer_comes_back_as_text(monkeypatch):
    box = _boxed(monkeypatch, Recorder(payload=b"<html>nope</html>"))

    result = await call(box, "cloudflare", "/zones")

    assert "nope" in result["result"]


# ---- the session token, where the provider's REST API takes it ----------


class Sessions:
    """A vault holding one MCP session and no pasted key."""

    def __init__(self, provider="vercel", token="sess-token"):
        import json
        self.store = {
            (f"munim-mcp:{provider}:tokens", "c_1"): json.dumps(
                {"access_token": token, "expires_in": 3600}),
        }

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


class NoKeys:
    def get(self, client, provider): return None
    def set(self, client, provider, secret): pass


def test_vercel_borrows_the_session_token_because_its_api_takes_it():
    """Measured, not assumed: a stored session token returned 200 from
    Vercel's REST API. Asking for a second credential there would be
    bureaucracy, and it is the exact gap that blocked an operator."""
    box = Container("c_1", NoKeys(), keyring=Sessions())

    assert box._credential("vercel") == "sess-token"


def test_resend_does_not_borrow_it_because_its_api_refuses():
    """Same shape of credential, 403 from Resend. A blanket fallback would turn
    a clear refusal into a confusing rejection from the provider."""
    from munim.container import UnknownCredential

    box = Container("c_1", NoKeys(), keyring=Sessions(provider="resend"))

    with pytest.raises(UnknownCredential, match="REST API"):
        box._credential("resend")


def test_a_pasted_key_still_wins_where_one_exists():
    """The borrow is a fallback, not a preference: a key the operator pasted
    is the one they meant."""
    box = Container("c_1", Keys("pasted"), keyring=Sessions())

    assert box._credential("vercel") == "pasted"


async def test_freshen_renews_a_stale_token_and_leaves_a_live_one_alone(
        monkeypatch, tmp_path):
    """Nothing synchronous can refresh a token: the SDK only does it inside a
    session. `freshen` opens one, which is enough, and skips when it need not."""
    import time

    from munim.remote import session as session_mod

    opened = []

    class Fake:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    def fake_session_for(client, provider, **kw):
        opened.append(provider)
        return Fake()

    monkeypatch.setattr(session_mod, "session_for", fake_session_for)

    class Store:
        def __init__(self, when): self.when = when
        def expires_at(self): return self.when

    monkeypatch.setattr("munim.remote.storage.KeychainTokenStorage",
                        lambda c, p, k=None: Store(time.time() + 3600))
    await session_mod.freshen("c_1", "vercel")
    assert opened == [], "a live token was refreshed for nothing"

    monkeypatch.setattr("munim.remote.storage.KeychainTokenStorage",
                        lambda c, p, k=None: Store(time.time() - 10))
    await session_mod.freshen("c_1", "vercel")
    assert opened == ["vercel"], "a stale token was not renewed"


async def test_freshen_never_raises(monkeypatch):
    """Best effort. It exists to improve the odds for the call that follows,
    and that call reports its own failure perfectly well."""
    from munim.remote import session as session_mod

    def explode(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr("munim.remote.storage.KeychainTokenStorage", explode)
    await session_mod.freshen("c_1", "vercel")
