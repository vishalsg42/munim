"""The Strands agent has to be reachable from the MCP surface.

It was not. `check` ran the deterministic checks itself and returned the JSON,
so `launch` had no callers anywhere outside its own package and `explain` never
executed. The README's architecture diagram showed a diagnosis step that no
code path could reach, and every demonstration was dnspython in a wrapper.

Nothing about the tool's output would have revealed it, which is why it is
pinned here.
"""

import pytest

import munim.agent.launch as agent_module
from munim.registry import ClientRecord, Registry
from munim.server import CROSS_CLIENT, MUTATING, build_server


class _Keychain:
    def __init__(self): self.store = {}
    def get(self, c, p): return self.store.get((c, p))
    def set(self, c, p, s): self.store[(c, p)] = s


def _server(tmp_path):
    registry = Registry(tmp_path / "registry.json")
    registry.add(ClientRecord(name="acme", domain="neverssl.com"))
    return build_server(backend=_Keychain(), registry=registry,
                        runs_dir=tmp_path / "runs",
                        reports_dir=tmp_path / "reports"), registry


@pytest.fixture(autouse=True)
def _canned_checks(monkeypatch):
    """The wiring is what is under test, not the catalogue. Live lookups made
    these three tests take 27 seconds and depend on someone else's DNS."""
    from munim.checks.dns import CheckResult

    async def failing(domain, **kwargs):
        return [
            CheckResult("dkim_present", "fail", "No DKIM record.",
                        "Your mail is not signed.", resolver="1.1.1.1"),
            CheckResult("mx_present", "pass", "MX records present.",
                        "Mail can be delivered.", resolver="1.1.1.1"),
        ]

    async def none(domain, **kwargs):
        return []

    monkeypatch.setattr(agent_module, "run_all_async", failing)
    monkeypatch.setattr(agent_module, "run_reachability_async", none)


class _FakeAgent:
    """Stands in for Strands. Records that it was asked."""
    asked = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def invoke_async(self, prompt):
        _FakeAgent.asked.append(prompt)
        return "Your mail is not signed, so receivers cannot prove it is you."


async def test_check_runs_the_agent_when_something_failed(tmp_path, monkeypatch):
    _FakeAgent.asked = []
    monkeypatch.setattr(agent_module, "build_model", lambda: (object(), "fake"))
    monkeypatch.setattr(agent_module, "Agent", _FakeAgent)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})

    assert _FakeAgent.asked, "check completed without ever invoking the agent"
    prompt = _FakeAgent.asked[0]
    assert "neverssl.com" in prompt
    assert "acme" in prompt
    # The agent is given the deterministic findings, not asked to decide them.
    assert "Failing checks:" in prompt


async def test_the_agents_explanation_reaches_the_run_log(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "build_model", lambda: (object(), "fake"))
    monkeypatch.setattr(agent_module, "Agent", _FakeAgent)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})

    from munim.runlog import all_runs, RunLog
    runs = all_runs(tmp_path / "runs")
    events = list(RunLog(runs[-1], tmp_path / "runs").read())
    stages = {e.stage for e in events}
    assert "diagnose" in stages, f"no diagnosis in the run: {sorted(stages)}"
    assert any("receivers cannot prove" in e.human_text for e in events)


async def test_a_missing_model_costs_the_explanation_not_the_findings(tmp_path):
    """A fresh clone has no key. The checks must still land."""
    server, _ = _server(tmp_path)
    result = await server.call_tool("check", {"target": "acme"})
    payload = result[1] if isinstance(result, tuple) else result
    text = str(payload)
    assert "dkim_present" in text, text[:400]

    from munim.runlog import all_runs, RunLog
    runs = all_runs(tmp_path / "runs")
    events = list(RunLog(runs[-1], tmp_path / "runs").read())
    assert any(e.kind == "escalated" for e in events), \
        "a missing model host has to be said out loud"
    assert any(e.kind == "finding" for e in events), \
        "the deterministic findings must survive the model being absent"


def test_the_agent_is_built_with_printing_turned_off():
    """Strands streams tokens to stdout by default and the MCP server writes
    JSON-RPC to the same stdout with nothing in between. The default handler
    interleaves prose with the protocol and kills the connection.

    Asserted on the construction call rather than by capturing output, because
    whether the corruption shows up depends on timing: the first run of this
    over real stdio came back clean and was still wrong.
    """
    import inspect

    source = inspect.getsource(agent_module.explain)
    assert "callback_handler=None" in source, \
        "Agent must be constructed with callback_handler=None"


async def test_the_agent_gets_provider_tools_for_connected_providers(tmp_path, monkeypatch):
    """Built and unreachable is this project's recurring fault: the whole
    Strands agent was that way this morning. A toolset module nothing calls is
    the same bug waiting."""
    import munim.remote.storage as storage_mod
    import munim.remote.toolsets as toolsets_mod

    connected = {("acme", "cloudflare")}
    monkeypatch.setattr(
        storage_mod.KeychainTokenStorage, "_read",
        lambda self, kind: {"access_token": "t"} if (self._client, self._provider) in connected else None)

    built = []
    monkeypatch.setattr(toolsets_mod, "toolset_for",
                        lambda c, p, **k: built.append((c, p)) or _Stub(p))
    monkeypatch.setattr(agent_module, "build_model", lambda: (object(), "fake"))

    captured = {}

    class Recording(_FakeAgent):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(agent_module, "Agent", Recording)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})

    assert built == [("acme", "cloudflare")], \
        "only the connected provider should have a toolset built"
    names = [getattr(t, "_prefix", None) for t in captured["tools"]]
    assert "cloudflare" in names, f"the agent did not receive it: {names}"


async def test_an_unconnected_provider_does_not_open_a_browser(tmp_path, monkeypatch):
    """Building a toolset for a provider the client has not connected would
    start an OAuth flow in the middle of a diagnosis."""
    import munim.remote.storage as storage_mod
    import munim.remote.toolsets as toolsets_mod

    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "_read",
                        lambda self, kind: None)
    built = []
    monkeypatch.setattr(toolsets_mod, "toolset_for",
                        lambda c, p, **k: built.append((c, p)) or _Stub(p))
    monkeypatch.setattr(agent_module, "build_model", lambda: (object(), "fake"))
    monkeypatch.setattr(agent_module, "Agent", _FakeAgent)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})
    assert built == [], "a toolset was built for a provider with no session"


class _Stub:
    def __init__(self, prefix):
        self._prefix = prefix


async def test_work_on_client_is_given_that_client_and_no_other(tmp_path, monkeypatch):
    """"Write within" has to be a property of what the agent holds, not a rule
    it is asked to follow. A request needing a second account should have
    nothing to reach with."""
    import munim.agent.within as within

    monkeypatch.setattr(within, "connected_providers", lambda cid, backend=None: ["cloudflare"])
    built = []
    monkeypatch.setattr(within, "toolset_for",
                        lambda cid, provider, **kw: built.append((cid, kw.get("label")))
                        or _Stub(provider))
    monkeypatch.setattr(within, "build_model", lambda: (object(), "fake"))

    captured = {}

    class Recording(_FakeAgent):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(within, "Agent", Recording)

    server, registry = _server(tmp_path)
    await server.call_tool("work_on_client",
                           {"client": "acme", "request": "list the zones"})

    acme = registry.get("acme")
    assert built == [(acme.id, "acme")], "built a toolset for somebody else"
    assert len(captured["tools"]) == 1, "the agent was given more than one client"


async def test_a_client_with_nothing_connected_is_told_so(tmp_path, monkeypatch):
    """Rather than an agent with no tools quietly inventing an answer."""
    import munim.agent.within as within

    monkeypatch.setattr(within, "connected_providers", lambda cid, backend=None: [])
    server, _ = _server(tmp_path)
    result = await server.call_tool("work_on_client",
                                    {"client": "acme", "request": "anything"})
    text = str(result)
    assert "no provider connected" in text
    assert "munim connect" in text, "a refusal with no next step is a complaint"


async def test_working_on_one_client_is_declared_mutating(tmp_path):
    server, _ = _server(tmp_path)
    tools = {t.name: t for t in await server.list_tools()}
    assert "work_on_client" in MUTATING
    assert "client" in tools["work_on_client"].inputSchema.get("required", [])
    assert "work_on_client" not in CROSS_CLIENT, \
        "a tool that can write must never be allowed to span clients"
