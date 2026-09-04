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
from munim.server import build_server


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
