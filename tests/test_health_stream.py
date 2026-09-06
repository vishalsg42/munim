"""Probes pumped from the caller's own loop, rather than a background thread.

A thread probing while the main thread draws can write to the same stderr the
menu owns: the MCP SDK logs a traceback on any OAuth failure that is not a
plain NeedsLogin, and interpreter teardown can emit after the terminal has been
restored. Either corrupts the shell. So the loop lives in the Stream and the
menu decides when it runs.
"""

import asyncio

import pytest

from munim import health
from munim.registry import ClientRecord, Registry


@pytest.fixture
def two(tmp_path, monkeypatch):
    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme"))
    monkeypatch.setattr(health, "connections",
                        lambda cid, backend=None: ([], ["cloudflare", "vercel"]))
    return reg


def answers(monkeypatch, **timing):
    """Each provider answers after its own delay, so they land separately."""
    async def fake(client_id, name, provider, keyring=None):
        await asyncio.sleep(timing.get(provider, 0))
        return health.Status(name, provider, health.LIVE)
    monkeypatch.setattr(health, "check", fake)


def test_everything_starts_pending(two, monkeypatch):
    answers(monkeypatch)
    stream = health.Stream(two)

    assert [s.state for s in stream.statuses] == [health.PENDING] * 2
    assert not stream.settled
    stream.close()


def test_pending_is_not_live_and_offers_no_fix():
    waiting = health.Status("Acme", "cloudflare", health.PENDING)

    assert waiting.live is False
    assert waiting.settled is False
    assert waiting.fix == "", "nothing to reconnect: it has not been tried yet"


def test_results_land_one_at_a_time(two, monkeypatch):
    """The whole point. A single gather would give all-or-nothing."""
    answers(monkeypatch, cloudflare=0, vercel=0.25)
    stream = health.Stream(two)

    stream.pump(0.05)
    settled = [s.state for s in stream.statuses]
    assert health.LIVE in settled and health.PENDING in settled, \
        f"expected one of each while the slow one was still running: {settled}"

    while not stream.settled:
        stream.pump(0.1)
    assert [s.state for s in stream.statuses] == [health.LIVE] * 2


def test_pump_reports_whether_anything_changed(two, monkeypatch):
    answers(monkeypatch, cloudflare=0, vercel=10)
    stream = health.Stream(two)

    assert stream.pump(0.05) is True, "the first result should be a change"
    assert stream.pump(0.0) is False, "nothing new, so nothing to redraw"
    stream.close()


def test_a_probe_that_never_answers_is_given_up_on(two, monkeypatch):
    """Otherwise the menu polls forever waiting on one provider."""
    answers(monkeypatch, cloudflare=0, vercel=999)
    monkeypatch.setattr(health, "TIMEOUT", 0.0)
    stream = health.Stream(two)

    for _ in range(60):
        stream.pump(0.05)
        if stream.settled:
            break

    assert stream.settled, "the deadline never fired"
    assert any(s.state == health.UNREACHABLE for s in stream.statuses)


def test_the_row_set_never_changes_size(two, monkeypatch):
    """The seed and the probes share one work list. Two calls to _stored are
    two chances to disagree, and a row set that shrinks under a moving cursor
    is how a menu acts on the wrong thing."""
    answers(monkeypatch, cloudflare=0, vercel=0.1)
    stream = health.Stream(two)

    sizes = {len(stream.statuses)}
    while not stream.settled:
        stream.pump(0.05)
        sizes.add(len(stream.statuses))

    assert sizes == {2}


def test_nothing_stored_settles_immediately(tmp_path, monkeypatch):
    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme"))
    monkeypatch.setattr(health, "connections", lambda cid, backend=None: ([], []))

    stream = health.Stream(reg)
    assert stream.statuses == []
    assert stream.settled
    assert stream.pump() is False


def test_close_is_safe_before_anything_started(two, monkeypatch):
    answers(monkeypatch)
    health.Stream(two).close()


def test_the_settled_helpers_are_unchanged(two, monkeypatch):
    """doctor and the MCP tools want an answer, not a spinner."""
    answers(monkeypatch)

    found = health.check_all(two)
    assert [s.state for s in found] == [health.LIVE] * 2
    assert all(s.settled for s in found)


# ---- the two seams called "backend" are not the same thing -------------


async def test_a_programming_error_is_not_reported_as_an_unreachable_provider(
        two, monkeypatch):
    """The bug this narrowing exists for.

    `connections()` takes a CredentialBackend, with get/set/forget.
    `session_for` takes a vault-like store, with get_password/set_password.
    Threading the first into the second raised AttributeError on every probe,
    and a broad `except Exception` relabelled it "could not be reached", so
    doctor reported the network as down when nothing had been tried.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def broken(*a, **k):
        raise AttributeError("'KeychainBackend' object has no attribute "
                             "'get_password'")
        yield

    monkeypatch.setattr("munim.remote.session.session_for", broken)

    with pytest.raises(AttributeError):
        await health.check("c_1", "Acme", "cloudflare")


async def test_a_transport_failure_is_still_reported_rather_than_raised(
        two, monkeypatch):
    """Narrowing must not turn a provider being down into a crash."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def offline(*a, **k):
        raise OSError("Name or service not known")
        yield

    monkeypatch.setattr("munim.remote.session.session_for", offline)

    got = await health.check("c_1", "Acme", "cloudflare")
    assert got.state == health.UNREACHABLE


async def test_the_session_store_is_the_one_that_reaches_session_for(
        two, monkeypatch):
    """`keyring` goes to the session; `backend` only ever enumerates."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    seen = {}

    @asynccontextmanager
    async def spy(client, provider, **kwargs):
        seen.update(kwargs)
        yield SimpleNamespace(list_tools=_empty)

    async def _empty():
        return SimpleNamespace(tools=[])

    monkeypatch.setattr("munim.remote.session.session_for", spy)
    sentinel = object()
    await health.check("c_1", "Acme", "cloudflare", keyring=sentinel)

    assert seen["keyring"] is sentinel
