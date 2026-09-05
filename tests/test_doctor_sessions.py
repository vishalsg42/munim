"""doctor said "Working" while two sessions were dead.

Stored credentials say nothing about whether they still work. `connections()`
tests only that a token blob or an endpoint exists, so `list_clients`,
`client_status` and `doctor` all reported two expired sessions as connected, and
the failure surfaced only when something tried to use one.

Nothing local can tell the difference. OAuth grants a token and says nothing
more; the only authority on whether a credential still works is the party that
issued it. So this check leaves the machine, and the cost of that is why the
probes run concurrently.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from munim import doctor, health
from munim.registry import ClientRecord, Registry
from munim.remote.session import NeedsLogin, NoRemoteServer


@pytest.fixture
def two_clients(tmp_path, monkeypatch):
    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme"))
    reg.add(ClientRecord(name="Ivy & Fern"))
    return reg


def sessions_are(monkeypatch, held, behaviour):
    """`held` is what is stored; `behaviour` decides what opening one does."""
    monkeypatch.setattr(health, "connections",
                        lambda cid, backend=None: ([], list(held)))

    @asynccontextmanager
    async def fake(client, provider, **kwargs):
        outcome = behaviour(client, provider)
        if isinstance(outcome, Exception):
            raise outcome

        class Session:
            async def list_tools(self):
                # The real one returns an object with `.tools`, not a bare
                # list. A double narrower than the thing it replaces hides
                # exactly the breakage it is meant to catch.
                return SimpleNamespace(tools=[])
        yield Session()

    monkeypatch.setattr("munim.remote.session.session_for", fake)


def test_a_dead_session_is_reported_with_the_command_that_fixes_it(
        two_clients, monkeypatch):
    sessions_are(monkeypatch, ["cloudflare"],
                 lambda c, p: NeedsLogin("expired"))

    found = doctor._sessions(two_clients)

    assert len(found) == 2, "one finding per dead session, not one for all"
    assert all(f.status == doctor.WARN for f in found)
    assert any("Acme" in f.detail for f in found)
    assert all("munim connect" in f.fix for f in found)


def test_live_sessions_report_ok_and_say_how_many_were_checked(
        two_clients, monkeypatch):
    sessions_are(monkeypatch, ["cloudflare", "vercel"], lambda c, p: None)

    found = doctor._sessions(two_clients)

    assert len(found) == 1
    assert found[0].status == doctor.OK
    assert "4" in found[0].detail, "two clients times two providers"


def test_only_the_dead_ones_are_listed(two_clients, monkeypatch):
    """A report that names working sessions alongside broken ones buries the point."""
    sessions_are(monkeypatch, ["cloudflare", "vercel"],
                 lambda c, p: NeedsLogin("x") if p == "vercel" else None)

    found = doctor._sessions(two_clients)

    assert len(found) == 2
    assert all("vercel" in f.detail for f in found)
    assert not any("cloudflare" in f.detail for f in found)


def test_being_offline_is_not_reported_as_an_expired_session(
        two_clients, monkeypatch):
    """Telling somebody to reconnect when their wifi is off sends them
    through a browser login for nothing."""
    sessions_are(monkeypatch, ["cloudflare"],
                 lambda c, p: OSError("Name or service not known"))

    found = doctor._sessions(two_clients)

    assert all("expired" not in f.detail for f in found)
    assert any("could not be reached" in f.detail for f in found)


def test_a_provider_with_no_mcp_server_is_not_a_problem(two_clients, monkeypatch):
    sessions_are(monkeypatch, ["cloudflare"],
                 lambda c, p: NoRemoteServer("no server"))

    found = doctor._sessions(two_clients)

    assert len(found) == 1
    assert found[0].status == doctor.OK


def test_nothing_connected_means_nothing_to_say(tmp_path, monkeypatch):
    """A fresh install must not grow a Sessions line it cannot act on."""
    reg = Registry(tmp_path / "r.json")
    monkeypatch.setattr(health, "connections", lambda cid, backend=None: ([], []))

    assert doctor._sessions(reg) == []


def test_an_unreadable_credential_store_does_not_crash_the_report(
        two_clients, monkeypatch):
    """`_keychain` already reports that, and one broken check must not take
    the whole report down with it."""
    def explode(cid, backend=None):
        raise RuntimeError("credentials unreadable")

    monkeypatch.setattr(health, "connections", explode)

    assert doctor._sessions(two_clients) == []


def test_the_probes_run_together_rather_than_one_after_another(
        two_clients, monkeypatch):
    """Serially this grows with every client. The whole point is that it does not."""
    import asyncio
    import time

    monkeypatch.setattr(health, "connections",
                        lambda cid, backend=None: ([], ["cloudflare", "vercel"]))

    @asynccontextmanager
    async def slow(client, provider, **kwargs):
        await asyncio.sleep(0.2)

        class Session:
            async def list_tools(self):
                return []
        yield Session()

    monkeypatch.setattr("munim.remote.session.session_for", slow)

    started = time.perf_counter()
    doctor._sessions(two_clients)      # four probes of 0.2s each
    took = time.perf_counter() - started

    assert took < 0.6, f"four 0.2s probes took {took:.2f}s, so they ran serially"


def test_a_hanging_provider_is_given_up_on(two_clients, monkeypatch):
    """A report that waits forever on one provider is worse than an incomplete one."""
    import asyncio

    monkeypatch.setattr(health, "TIMEOUT", 0.1)
    monkeypatch.setattr(health, "connections",
                        lambda cid, backend=None: ([], ["cloudflare"]))

    @asynccontextmanager
    async def never(client, provider, **kwargs):
        await asyncio.sleep(30)
        yield None

    monkeypatch.setattr("munim.remote.session.session_for", never)

    found = doctor._sessions(two_clients)

    assert all(f.status == doctor.WARN for f in found)
    assert any("no answer" in f.detail for f in found)
