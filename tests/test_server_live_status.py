"""`list_clients` and `client_status` report what opens, not what is filed.

Both used `reachable()`, which tests only whether a credential is stored. Two
dead sessions therefore read as connected to the coding agent for a day, and
the failure surfaced only when something tried to use one. `doctor` and the
navigable view were fixed first; these two are the surface an agent actually
reads, so they mattered most and were fixed last.
"""

import json

import pytest

from munim import health, server as server_module
from munim.container import KeychainBackend
from munim.registry import ClientRecord, Registry


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


@pytest.fixture
def estate(tmp_path, monkeypatch):
    ring = Ring()
    monkeypatch.setattr("munim.remote.storage.vault", ring)
    monkeypatch.setattr("munim.container.vault", ring)

    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme", domain="acme.test"))

    built = server_module.build_server(
        backend=KeychainBackend(), registry=reg, runs_dir=tmp_path / "runs",
        reports_dir=tmp_path / "reports")
    return built, reg


def result(returned):
    """FastMCP hands back (content, structured) for a list return and content
    alone for a dict one. Both shapes carry the same JSON."""
    if isinstance(returned, tuple) and len(returned) == 2:
        return returned[1]["result"]
    content = returned[0] if isinstance(returned, (list, tuple)) else returned
    return json.loads(content[0].text if isinstance(content, list)
                      else content.text)


def stored(monkeypatch, providers, keys=()):
    """What is filed, split the way the real code splits it.

    `reachable()` is API keys **plus** MCP sessions; `health._stored` walks the
    sessions half only. The first version of this helper handed both the same
    list, so the two universes could never diverge and the bug where a pasted
    API key vanished from every answer was invisible to every test here.
    """
    keys = list(keys)
    # Signatures match the real ones, including the keyring the server now
    # threads through so a status reads the same store it was built with. A
    # double that is narrower than what it replaces turns a real call into a
    # TypeError that looks like the test's fault.
    monkeypatch.setattr(server_module, "reachable",
                        lambda cid, backend=None, keyring=None:
                        sorted({*providers, *keys}))
    monkeypatch.setattr(server_module, "connections",
                        lambda cid, backend=None, keyring=None:
                        (keys, list(providers)))
    monkeypatch.setattr(health, "connections",
                        lambda cid, backend=None, keyring=None:
                        (keys, list(providers)))


def probed(monkeypatch, **states):
    async def fake(client_id, name, provider, keyring=None):
        return health.Status(name, provider, states[provider],
                             "the session expired"
                             if states[provider] == health.EXPIRED else "")
    monkeypatch.setattr(health, "check", fake)


async def test_an_api_key_is_not_reported_as_connected_to_nothing(
        estate, monkeypatch):
    """A pasted key has no session to open, so no probe covers it.

    It used to fall out of `connected`, `needs_login` and `unreachable` alike
    while `checked: true` claimed the answer had been verified, which is a
    worse lie than the one this whole surface was changed to fix.
    """
    built, _ = estate
    stored(monkeypatch, [], keys=["resend"])

    row = result(await built.call_tool("list_clients", {}))[0]

    assert row["stored"] == ["resend"]
    assert "resend" in row["not_checked"], \
        "a credential nothing probed must be named, not silently dropped"
    assert row["connected"] == []
    covered = set(row["connected"]) | set(row["needs_login"]) \
        | set(row["unreachable"]) | set(row["not_checked"])
    assert covered == set(row["stored"]), "a stored credential vanished"


async def test_a_key_and_a_session_are_reported_side_by_side(
        estate, monkeypatch):
    built, _ = estate
    stored(monkeypatch, ["cloudflare"], keys=["resend"])
    probed(monkeypatch, cloudflare=health.LIVE)

    row = result(await built.call_tool("list_clients", {}))[0]

    assert row["connected"] == ["cloudflare"]
    assert row["not_checked"] == ["resend"]


async def test_a_stored_but_dead_session_is_not_reported_connected(
        estate, monkeypatch):
    """The bug, stated once. `cloudflare` has a credential and will not open."""
    built, _ = estate
    stored(monkeypatch, ["cloudflare", "vercel"])
    probed(monkeypatch, cloudflare=health.EXPIRED, vercel=health.LIVE)

    row = result(await built.call_tool("list_clients", {}))[0]

    assert row["connected"] == ["vercel"]
    assert row["needs_login"] == ["cloudflare"]
    assert row["stored"] == ["cloudflare", "vercel"], \
        "the credential still exists and disconnect still acts on it"


async def test_unreachable_is_kept_apart_from_needs_login(estate, monkeypatch):
    """Reconnecting does not fix a network that is down."""
    built, _ = estate
    stored(monkeypatch, ["cloudflare"])
    probed(monkeypatch, cloudflare=health.UNREACHABLE)

    row = result(await built.call_tool("list_clients", {}))[0]

    assert row["unreachable"] == ["cloudflare"]
    assert row["needs_login"] == []
    assert row["connected"] == []


async def test_client_status_answers_the_same_way(estate, monkeypatch):
    built, _ = estate
    stored(monkeypatch, ["cloudflare"])
    probed(monkeypatch, cloudflare=health.EXPIRED)

    got = result(await built.call_tool("client_status", {"client": "Acme"}))

    assert got["connected"] == []
    assert got["needs_login"] == ["cloudflare"]
    assert got["checked"] is True


async def test_check_false_skips_the_network_and_says_so(estate, monkeypatch):
    """An agent that only wants the inventory should not pay for a round trip,
    and must not be told the answer was verified when it was not."""
    built, _ = estate
    stored(monkeypatch, ["cloudflare"])

    async def explode(*a, **k):
        raise AssertionError("check=false still probed the provider")
    monkeypatch.setattr(health, "check", explode)

    row = result(await built.call_tool("list_clients", {"check": False}))[0]
    assert row["checked"] is False
    assert row["stored"] == ["cloudflare"]
    assert "connected" not in row, \
        "an unverified answer must not use the word that claims verification"

    got = result(await built.call_tool(
        "client_status", {"client": "Acme", "check": False}))
    assert got["checked"] is False


async def test_a_client_with_nothing_stored_probes_nothing(estate, monkeypatch):
    built, _ = estate
    stored(monkeypatch, [])

    async def explode(*a, **k):
        raise AssertionError("probed a client with no credentials")
    monkeypatch.setattr(health, "check", explode)

    row = result(await built.call_tool("list_clients", {}))[0]
    assert row["connected"] == [] and row["stored"] == []


async def test_neither_tool_returns_a_credential(estate, monkeypatch):
    """The rule that has held since the first commit."""
    built, _ = estate
    stored(monkeypatch, ["cloudflare"])
    probed(monkeypatch, cloudflare=health.LIVE)

    text = str(await built.call_tool("client_status", {"client": "Acme"}))
    assert "token" not in text.lower()
