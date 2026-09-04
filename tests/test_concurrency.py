"""Two clients checked at the same time must not see each other's answers.

`run_all_async` used to swap the module-level `query` for a closure over its
own cache and restore it in a `finally`. That is safe only while nothing
between the swap and the restore suspends. Under two event loops, or after
anyone adds an await inside, the restore puts back another task's closure and
the global stays poisoned: every later caller is served a different client's
DNS. That is the one failure this project exists to prevent, so it is pinned
here rather than left to review.
"""

import asyncio

import pytest

from munim.checks import dns as checks


def _cache(domain: str, txt: str, selector: str = "resend"):
    """Every record the prefetch fetches, so nothing falls through to the wire."""
    empty = {
        (domain, "MX"): [], (domain, "NS"): [], (domain, "A"): [],
        (domain, "AAAA"): [], (domain, "CAA"): [],
        (f"_dmarc.{domain}", "TXT"): [],
        (f"{selector}._domainkey.{domain}", "TXT"): [],
    }
    return {(domain, "TXT"): [txt], **empty}


@pytest.fixture
def interleaved(monkeypatch):
    """A prefetch that guarantees both tasks are inside it at the same time."""
    async def fake_prefetch(domain, selector="resend", ns="1.1.1.1"):
        await asyncio.sleep(0.02)
        return _cache(domain, f"v=spf1 include:{domain} -all", selector)

    monkeypatch.setattr(checks, "prefetch", fake_prefetch)


async def test_two_domains_checked_at_once_keep_their_own_answers(interleaved):
    a, b = await asyncio.gather(
        checks.run_all_async("acme.example"),
        checks.run_all_async("beta.example"),
    )
    said = lambda results: next(r for r in results if r.check == "spf_lookups")

    # Each domain's SPF record names itself. A crossover shows up as one
    # domain's evidence carrying the other's name.
    assert "acme.example" in str(said(a).evidence)
    assert "beta.example" not in str(said(a).evidence)
    assert "beta.example" in str(said(b).evidence)
    assert "acme.example" not in str(said(b).evidence)


async def test_the_module_level_query_is_never_reassigned(interleaved):
    """The old restore-in-finally left the global holding a stale cache after
    concurrent use, so every later caller got one client's answers."""
    before = checks.query
    await asyncio.gather(
        checks.run_all_async("acme.example"),
        checks.run_all_async("beta.example"),
    )
    assert checks.query is before


async def test_the_cache_does_not_leak_out_of_the_run(interleaved):
    """Outside a run there is no task-local cache, so nothing is served from
    a previous client's answers."""
    await checks.run_all_async("acme.example")
    assert checks._prefetched.get() is None
