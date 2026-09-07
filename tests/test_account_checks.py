"""The one question that generalises across all eleven providers.

The other check families are per-thing: thirteen about DNS, three about Vercel
hosting. Writing a third family per provider does not scale and would not
finish, and most of what the other eight expose has no deterministic question
worth asking.

This is the question that does generalise. It is the same for every provider,
only the provider can answer it, and `health.check` already asks it. What was
missing was treating the answer as a check result rather than a connection
status, so it lands in the run log, the report and the room beside everything
else.

The distinction these tests are really about is three states rather than two.
"They rejected the credential" and "we could not reach them" are different
facts, and reporting the second as the first sends an operator to reconnect an
account that was fine. That is the exact failure `connected.py` was written
about, and it would be a shame to reintroduce it one layer up.
"""

import asyncio

import pytest

from munim import health
from munim.checks.accounts import name_for, run_accounts_async


def _status(provider, state, detail="", tools=0):
    return health.Status(client="Acme Ltd", provider=provider, state=state,
                         detail=detail, tools=tools)


@pytest.fixture
def answers(monkeypatch):
    """Whatever each provider is going to say, keyed by provider."""
    said = {}

    async def fake_check(client_id, name, provider, keyring=None):
        answer = said[provider]
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return await answer()
        return answer

    monkeypatch.setattr(health, "check", fake_check)
    return said


async def test_a_live_account_passes(answers):
    answers["cloudflare"] = _status("cloudflare", health.LIVE, tools=3)

    results = await run_accounts_async("c_1", "Acme Ltd", ["cloudflare"])

    assert [r.check for r in results] == ["account_cloudflare"]
    assert results[0].status == "pass"
    assert results[0].detail["tools"] == 3


async def test_an_expired_session_fails_and_says_what_it_costs(answers):
    """The finding worth having. An expired Sentry connection means nobody has
    seen an error from the client's site since it expired, and nothing else in
    this project would have told you."""
    answers["sentry"] = _status("sentry", health.EXPIRED, "token rejected")

    results = await run_accounts_async("c_1", "Acme Ltd", ["sentry"])

    assert results[0].status == "fail"
    assert "expired" in results[0].human_text
    assert results[0].detail["fix"] == 'munim connect "Acme Ltd" sentry'


async def test_unreachable_is_a_skip_and_never_a_failure(answers):
    """The one that matters. A flaky network is not a dead credential, and
    telling an operator to reconnect a working account wastes their time and
    their client's."""
    answers["notion"] = _status("notion", health.UNREACHABLE, "timed out")

    results = await run_accounts_async("c_1", "Acme Ltd", ["notion"])

    assert results[0].status == "skip"
    assert "does not mean anything is wrong" in results[0].human_text
    assert results[0].detail["reason"] == "unreachable"


async def test_a_client_with_no_sessions_produces_nothing(answers):
    assert await run_accounts_async("c_1", "Acme Ltd", []) == []


async def test_every_connected_provider_gets_exactly_one_result(answers):
    for provider in ("cloudflare", "vercel", "resend", "linear"):
        answers[provider] = _status(provider, health.LIVE)

    results = await run_accounts_async(
        "c_1", "Acme Ltd", ["resend", "cloudflare", "linear", "vercel"])

    assert [r.check for r in results] == [
        name_for(p) for p in ("cloudflare", "linear", "resend", "vercel")], \
        "results must be in a stable order, not whichever answered first"


async def test_one_provider_throwing_does_not_lose_the_others(answers):
    """`health.check` already catches broadly, so reaching the exception path
    means something further out went wrong. Nine providers answering must not
    be thrown away because a tenth did something unexpected."""
    answers["cloudflare"] = _status("cloudflare", health.LIVE)
    answers["vercel"] = RuntimeError("something unexpected")

    results = await run_accounts_async("c_1", "Acme Ltd",
                                       ["cloudflare", "vercel"])

    assert len(results) == 2
    assert results[0].status == "pass"
    assert results[1].status == "skip"
    assert results[1].detail["reason"] == "unreachable"


async def test_a_provider_that_never_answers_does_not_hang_the_check(answers):
    """These run on every check. One provider hanging must bound the family
    rather than the whole run, which is the same reasoning `health.check_all`
    already applies across clients."""
    async def never():
        await asyncio.sleep(60)

    answers["zoho"] = never
    answers["cloudflare"] = _status("cloudflare", health.LIVE)

    results = await run_accounts_async("c_1", "Acme Ltd",
                                       ["cloudflare", "zoho"], timeout=0.2)

    assert len(results) == 2
    assert {r.status for r in results} == {"skip"}
    assert all(r.detail["reason"] == "unreachable" for r in results)


async def test_the_probes_run_together_rather_than_one_after_another(answers):
    """Serially this is one round trip after another and grows with every
    provider a client connects."""
    async def slow():
        await asyncio.sleep(0.15)
        return _status("x", health.LIVE)

    for provider in ("cloudflare", "vercel", "resend", "linear", "notion"):
        answers[provider] = slow

    began = asyncio.get_running_loop().time()
    await run_accounts_async("c_1", "Acme Ltd",
                             ["cloudflare", "vercel", "resend", "linear",
                              "notion"])
    took = asyncio.get_running_loop().time() - began

    assert took < 0.5, f"five 0.15s probes took {took:.2f}s, so they ran serially"


async def test_the_check_name_says_which_provider_it_is_about():
    """One family, eleven members, and a reader has to be able to tell them
    apart in a report that also contains thirteen DNS checks."""
    assert name_for("sentry") == "account_sentry"
    assert name_for("cloudflare") == "account_cloudflare"


async def test_these_are_not_chips(answers):
    """Stated as a test because it is a design decision that would otherwise
    be undone by someone being helpful.

    The room's chip grid is a fixed four-column layout whose whole value is
    that nothing moves between renders: cells light in place. Eleven chips that
    appear or not depending on what a client connected would break that, so
    these render in the log stream instead.
    """
    import pathlib
    import re

    reducer = (pathlib.Path(__file__).parent.parent / "src" / "munim" /
               "room" / "static" / "reduce.mjs").read_text(encoding="utf-8")
    chips = set(re.findall(r'"([a-z_]+)"',
                           reducer.split("export const CHECKS = [", 1)[1]
                           .split("]", 1)[0]))

    assert not any(c.startswith("account_") for c in chips), \
        "account checks became chips; the grid is fixed-width on purpose"
