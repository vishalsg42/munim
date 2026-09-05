"""Forwarding a provider's tools, and what has to stay true while doing it.

The passthrough softened the strongest isolation claim Munim makes. It used to
be structural: a sub-agent built with one client's toolsets has nothing to reach
a second account with. Now it is per call, and a per-call guarantee is only as
good as two things, both asserted here: that a call resolves exactly one
client's credentials, and that every call is recorded with what it did.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from munim.remote import passthrough
from munim.remote.passthrough import UnknownTool, call_tool, tools_for
from munim.remote.session import NeedsLogin, NoRemoteServer, session_for
from munim.runlog import RunLog, new_run_id


def annotated(read_only=None, destructive=False):
    if read_only is None:
        return None
    return SimpleNamespace(readOnlyHint=read_only, destructiveHint=destructive)


def tool(name, *, read_only=None, destructive=False, does="", schema=None):
    return SimpleNamespace(
        name=name, description=does,
        annotations=annotated(read_only, destructive),
        inputSchema=schema or {"type": "object"},
    )


class FakeSession:
    """One provider's MCP server, and a note of who opened it."""

    def __init__(self, tools, opened_as, answer=None, fails=False):
        self._tools = tools
        self.opened_as = opened_as
        self._answer = answer if answer is not None else {"ok": True}
        self._fails = fails
        self.called = []

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.called.append((name, arguments))
        # An MCP result: a text block holding JSON, which is what every
        # provider Munim talks to actually returns.
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._answer))],
            structuredContent=None, isError=self._fails)


def fake_sessions(monkeypatch, per_client, opened):
    """Point the passthrough at fakes, one per client, recording who was asked."""

    @asynccontextmanager
    async def fake(client, provider, **kwargs):
        opened.append((client, provider))
        if client not in per_client:
            raise NeedsLogin(f"{client} is not connected to {provider}. "
                             f"Run: munim connect")
        session = per_client[client]
        session.opened_as = client
        yield session

    monkeypatch.setattr(passthrough, "session_for", fake)
    return opened


# ---- one call touches one client ---------------------------------------


async def test_a_call_reaches_only_the_named_clients_session(monkeypatch):
    """The whole per-call guarantee, stated as a test.

    Two clients are connected to the same provider. Calling for one must open
    that one's session and no other. This is what replaced "the sub-agent
    physically holds one client's tools", so it is asserted rather than assumed.
    """
    opened = []
    balaji = FakeSession([tool("execute")], "c_balaji", answer={"zone": "balaji"})
    kloud = FakeSession([tool("execute")], "c_kloud", answer={"zone": "kloud"})
    fake_sessions(monkeypatch, {"c_balaji": balaji, "c_kloud": kloud}, opened)

    result = await call_tool("c_balaji", "cloudflare", "execute", {"code": "x"})

    assert opened == [("c_balaji", "cloudflare")]
    assert result["result"] == {"zone": "balaji"}
    assert balaji.called == [("execute", {"code": "x"})]
    assert kloud.called == [], "the other client's session was opened"


async def test_an_unconnected_client_refuses_rather_than_falling_through(monkeypatch):
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession([tool("execute")], "x")},
                  opened)

    with pytest.raises(NeedsLogin):
        await call_tool("c_nobody", "cloudflare", "execute", {})


async def test_an_unknown_provider_is_refused_before_any_session_opens():
    """No session, no credential lookup, and the message names the real ones."""
    with pytest.raises(NoRemoteServer) as caught:
        await call_tool("c_balaji", "cloudfare", "execute", {})

    assert "cloudflare" in str(caught.value), "the message should name what exists"


# ---- never a surprise login -------------------------------------------


async def test_the_passthrough_never_opens_a_browser():
    """Same guarantee as tests/test_no_surprise_login.py, one layer up.

    A tool call is the least attended place in this system: it runs inside a
    coding agent, in response to a model's decision, with nobody looking at a
    terminal. A consent screen appearing there is worse than a failure.
    """
    class Ring:
        def get_password(self, a, b): return None
        def set_password(self, a, b, c): pass
        def delete_password(self, a, b): pass

    with pytest.raises(NeedsLogin, match="munim connect"):
        await call_tool("c_never_connected", "cloudflare", "execute", {},
                        backend=Ring())

    with pytest.raises(NeedsLogin, match="munim connect"):
        await tools_for("c_never_connected", "cloudflare", backend=Ring())


async def test_session_for_is_asked_not_to_allow_a_login(monkeypatch):
    """Belt and braces: the refusal above depends on this argument being passed."""
    seen = {}

    @asynccontextmanager
    async def fake(client, provider, **kwargs):
        seen.update(kwargs)
        yield FakeSession([tool("execute")], client)

    monkeypatch.setattr(passthrough, "session_for", fake)
    await call_tool("c_balaji", "cloudflare", "execute", {})

    assert seen["allow_login"] is False


# ---- a wrong tool name is an answer, not a crash ----------------------


async def test_a_tool_that_does_not_exist_names_the_ones_that_do(monkeypatch):
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession(
        [tool("docs"), tool("search"), tool("execute")], "c_balaji")}, opened)

    with pytest.raises(UnknownTool) as caught:
        await call_tool("c_balaji", "cloudflare", "exec", {})

    message = str(caught.value)
    assert "exec" in message
    for name in ("docs", "search", "execute"):
        assert name in message


# ---- arguments are forwarded, not reshaped ---------------------------


async def test_arguments_pass_through_untouched(monkeypatch):
    """Reshaping arguments would be the parameter-modelling this replaced.

    Cloudflare's `execute` takes a JavaScript string and Vercel's tools take
    nested objects. Anything that normalised, flattened or validated these
    would put Munim back in the business of knowing each provider's schema.
    """
    opened = []
    session = FakeSession([tool("deploy_to_vercel")], "c_balaji")
    fake_sessions(monkeypatch, {"c_balaji": session}, opened)

    arguments = {"project": {"name": "site", "env": [{"k": "A", "v": "1"}]},
                 "code": "await fetch('https://api')", "force": True,
                 "count": 3, "nothing": None}
    await call_tool("c_balaji", "vercel", "deploy_to_vercel", dict(arguments))

    assert session.called == [("deploy_to_vercel", arguments)]


async def test_no_arguments_is_an_empty_object_not_none(monkeypatch):
    opened = []
    session = FakeSession([tool("list_projects")], "c_balaji")
    fake_sessions(monkeypatch, {"c_balaji": session}, opened)

    await call_tool("c_balaji", "vercel", "list_projects")

    assert session.called == [("list_projects", {})]


# ---- the run log is the audit trail ----------------------------------


async def test_every_call_lands_in_the_run_log(tmp_path, monkeypatch):
    """The compensating control for the softer isolation guarantee.

    If this record is not there, the trade D31 makes is not paid for: the log
    is the only place a person can see that one call touched one account.
    """
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession(
        [tool("execute")], "c_balaji", answer={"changed": 1})}, opened)

    log = RunLog(new_run_id(), tmp_path)
    await call_tool("c_balaji", "cloudflare", "execute",
                    {"code": "zones.update()"}, log=log)

    events = list(log.read())
    assert len(events) == 1
    event = events[0]
    assert event.client == "c_balaji"
    assert event.detail["provider"] == "cloudflare"
    assert event.detail["tool"] == "execute"
    assert event.detail["arguments"] == {"code": "zones.update()"}
    assert event.detail["failed"] is False


async def test_a_read_only_tool_is_an_observation_and_anything_else_a_mutation(
        tmp_path, monkeypatch):
    """Unannotated counts as a mutation.

    A call that might have changed something belongs in the same list as one
    that did. Cloudflare's `execute` is exactly this case: it can read and it
    can write, so it carries no read-only hint.
    """
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession([
        tool("search", read_only=True),
        tool("execute"),
        tool("delete_zone", read_only=True, destructive=True),
    ], "c_balaji")}, opened)

    log = RunLog(new_run_id(), tmp_path)
    for name in ("search", "execute", "delete_zone"):
        await call_tool("c_balaji", "cloudflare", name, {}, log=log)

    kinds = [e.kind for e in log.read()]
    assert kinds == ["observation", "mutation", "mutation"]


async def test_a_failed_call_is_still_recorded(tmp_path, monkeypatch):
    """An attempt that was refused is a thing that happened to the account."""
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession(
        [tool("execute")], "c_balaji", answer={"error": "no"}, fails=True)},
        opened)

    log = RunLog(new_run_id(), tmp_path)
    result = await call_tool("c_balaji", "cloudflare", "execute", {"code": "x"},
                             log=log)

    assert result["failed"] is True, "a refusal comes back, it does not raise"
    events = list(log.read())
    assert len(events) == 1
    assert events[0].detail["failed"] is True


async def test_a_huge_result_is_clipped_in_the_log_but_not_in_the_answer(
        tmp_path, monkeypatch):
    """The log is an audit trail, not a copy of the provider's database."""
    opened = []
    big = {"rows": ["x" * 100 for _ in range(200)]}
    fake_sessions(monkeypatch, {"c_balaji": FakeSession(
        [tool("execute")], "c_balaji", answer=big)}, opened)

    log = RunLog(new_run_id(), tmp_path)
    result = await call_tool("c_balaji", "cloudflare", "execute", {}, log=log)

    assert result["result"] == big, "the caller gets the whole thing"
    logged = list(log.read())[0].detail["result"]
    assert "truncated" in logged
    assert logged["full_length"] > passthrough.LOGGED_RESULT


async def test_a_call_without_a_log_still_works(monkeypatch):
    """The CLI always passes one; a direct caller need not be forced to."""
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession([tool("docs")], "x")},
                  opened)

    result = await call_tool("c_balaji", "cloudflare", "docs", {})
    assert result["tool"] == "docs"


# ---- listing ----------------------------------------------------------


async def test_listing_reports_what_the_provider_says_about_each_tool(monkeypatch):
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession([
        tool("search", read_only=True, does="Search the docs"),
        tool("execute", does="Run JavaScript",
             schema={"type": "object", "properties": {"code": {"type": "string"}}}),
        tool("delete_zone", read_only=True, destructive=True),
    ], "c_balaji")}, opened)

    listed = await tools_for("c_balaji", "cloudflare")

    by_name = {t["tool"]: t for t in listed}
    assert by_name["search"]["read_only"] is True
    assert by_name["search"]["does"] == "Search the docs"
    assert by_name["execute"]["arguments"]["properties"] == {
        "code": {"type": "string"}}
    # Read-only and destructive at once is a contradiction the provider
    # published. Munim believes the destructive half.
    assert by_name["delete_zone"]["read_only"] is False


async def test_an_unannotated_tool_reports_null_not_false(monkeypatch):
    """Three states, because two would assert something the provider never said.

    `toolsets._is_read_only` collapses unknown to False, correctly, because it
    decides what a cross-client agent may hold and default-deny is right there.
    Nothing is being decided here, so the unknown stays visible.
    """
    opened = []
    fake_sessions(monkeypatch, {"c_balaji": FakeSession(
        [tool("execute")], "c_balaji")}, opened)

    listed = await tools_for("c_balaji", "cloudflare")
    assert listed[0]["read_only"] is None


async def test_listing_an_unknown_provider_names_the_real_ones():
    with pytest.raises(NoRemoteServer, match="cloudflare"):
        await tools_for("c_balaji", "not-a-provider")


def test_known_providers_is_more_than_the_three_the_mail_tools_use():
    """The passthrough reaches everything in servers.py the day it lands."""
    from munim.server import PROVIDERS

    known = passthrough.known_providers()
    assert set(PROVIDERS) <= set(known)
    assert len(known) > len(PROVIDERS)
    for provider in ("supabase", "linear", "notion", "sentry"):
        assert provider in known


# ---- the MCP surface --------------------------------------------------


async def test_call_provider_tool_is_declared_mutating_and_takes_a_client():
    """It writes, so it must name an account. That is D5 and the build enforces it."""
    from munim.server import CROSS_CLIENT, MUTATING, build_server

    assert "call_provider_tool" in MUTATING
    assert "call_provider_tool" not in CROSS_CLIENT

    tools = {t.name: t for t in await build_server().list_tools()}
    assert "client" in tools["call_provider_tool"].inputSchema["properties"]
    assert "client" in tools["list_provider_tools"].inputSchema["properties"]


async def test_the_passthrough_says_nothing_about_model_hosts():
    """The reason this exists. No settings, no agents check, no model import."""
    from pathlib import Path

    source = Path(passthrough.__file__).read_text()
    for forbidden in ("agents_off", "build_model", "strands", "settings.ai"):
        assert forbidden not in source, \
            f"{forbidden} in the passthrough puts a model back in this path"
