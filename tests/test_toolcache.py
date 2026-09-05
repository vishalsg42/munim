"""What a provider's tools were, last time anyone could ask.

Cloudflare and Vercel both return 401 on `initialize`, before `tools/list` is
reachable, so once a credential dies the list cannot be fetched again. It was
already known at connect time and thrown away, which made an expired session a
dead end.
"""

import time

from munim import toolcache


def some(name="execute"):
    return [{"tool": name, "does": "Run JavaScript", "read_only": None,
             "arguments": {"type": "object"}}]


def test_what_was_listed_comes_back():
    toolcache.remember("c_1", "cloudflare", some())

    tools, age = toolcache.recall("c_1", "cloudflare")
    assert tools == some()
    assert age < 5


def test_nothing_remembered_is_a_miss_not_an_error():
    assert toolcache.recall("c_nobody", "cloudflare") is None


def test_each_client_and_provider_is_remembered_separately():
    """The whole multi-account property would be worthless if one client's
    tools were served for another's."""
    toolcache.remember("c_1", "cloudflare", some("first"))
    toolcache.remember("c_2", "cloudflare", some("second"))
    toolcache.remember("c_1", "vercel", some("third"))

    assert toolcache.recall("c_1", "cloudflare")[0] == some("first")
    assert toolcache.recall("c_2", "cloudflare")[0] == some("second")
    assert toolcache.recall("c_1", "vercel")[0] == some("third")


def test_a_stale_enough_memory_stops_being_offered():
    """Not a correctness boundary, since a list can go stale in a minute. It
    is where "this is what it was" stops being useful to say."""
    toolcache.remember("c_1", "cloudflare", some())
    held = toolcache._load()
    held["c_1/cloudflare"]["at"] = time.time() - toolcache.STALE_AFTER - 10

    import json
    toolcache.path().write_text(json.dumps({"version": toolcache.VERSION,
                                            "entries": held}))
    assert toolcache.recall("c_1", "cloudflare") is None


def test_forget_drops_one_provider_or_a_whole_client():
    toolcache.remember("c_1", "cloudflare", some())
    toolcache.remember("c_1", "vercel", some())

    toolcache.forget("c_1", "cloudflare")
    assert toolcache.recall("c_1", "cloudflare") is None
    assert toolcache.recall("c_1", "vercel") is not None

    toolcache.forget("c_1")
    assert toolcache.recall("c_1", "vercel") is None


def test_an_unreadable_cache_is_a_miss_rather_than_a_crash():
    """Unlike the credential store there is nothing here worth refusing over."""
    toolcache.path().parent.mkdir(parents=True, exist_ok=True)
    toolcache.path().write_text("{ not json")

    assert toolcache.recall("c_1", "cloudflare") is None
    toolcache.remember("c_1", "cloudflare", some())
    assert toolcache.recall("c_1", "cloudflare")[0] == some()


def test_no_credential_can_reach_this_file():
    """It holds public metadata about a provider, not anything about the
    account, which is why it is a plain file next to the registry."""
    toolcache.remember("c_1", "cloudflare", some())
    text = toolcache.path().read_text()

    for secret in ("token", "secret", "Bearer", "refresh"):
        assert secret not in text


def test_age_reads_as_english():
    assert toolcache.age_in_words(10) == "just now"
    assert "minutes ago" in toolcache.age_in_words(600)
    assert "hours ago" in toolcache.age_in_words(7200)
    assert "days ago" in toolcache.age_in_words(200000)


async def test_a_successful_listing_is_remembered(monkeypatch):
    """The only moment the answer exists, since a dead session cannot be asked."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from munim.remote import passthrough

    @asynccontextmanager
    async def fake(client, provider, **kwargs):
        yield SimpleNamespace(list_tools=lambda: _listing())

    async def _listing():
        return SimpleNamespace(tools=[SimpleNamespace(
            name="execute", description="Run JS", annotations=None,
            inputSchema={"type": "object"})])

    monkeypatch.setattr(passthrough, "session_for", fake)
    await passthrough.tools_for("c_1", "cloudflare")

    tools, _ = toolcache.recall("c_1", "cloudflare")
    assert [t["tool"] for t in tools] == ["execute"]
