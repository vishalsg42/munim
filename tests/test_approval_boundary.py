"""The model may not approve its own change, and here is why it cannot.

Two claims hold this design up, and both are the kind that is easy to write in a
README and never be true in the code:

  1. Nothing the model can see takes an approval, so there is no token it can
     emit that approves anything.
  2. The only route the repair node has to somebody's DNS is `mailplan`, which
     diffs first and refuses before the network.

An earlier draft of this failed both. It gave the repair node the provider's own
write-capable toolsets alongside the gated tool, so the model could have called
`cloudflare_dns_update` and never touched the approval path at all, and it took
a `plan_id` argument, so the model could have named a plan approved earlier and
inherited somebody's answer about a different domain.

These tests exist so that cannot come back.
"""

import inspect
from pathlib import Path

import pytest

from munim import approval
from munim.agent import gate as gate_mod
from munim.agent import repair as repair_mod
from munim.agent.repair import RepairRun
from munim.runlog import RunLog, new_run_id


@pytest.fixture
def run(tmp_path):
    return RepairRun(run_id=new_run_id(), client="Acme Ltd", client_id="c_1",
                     domain="acme.example",
                     log=RunLog(new_run_id(), tmp_path / "runs"))


def _specs(tools):
    return {t.tool_spec["name"]: t.tool_spec for t in tools}


# ---- 1. what the model can say --------------------------------------------


def test_no_tool_the_model_sees_takes_an_approval(run):
    """The guarantee, asserted against the schema Strands actually generates
    rather than against the source, because the schema is what the model is
    shown and what it can fill in."""
    forbidden = ("approv", "confirm", "force", "override", "yes")

    for name, spec in _specs(repair_mod.repair_tools(run)).items():
        fields = (spec["inputSchema"]["json"].get("properties") or {}).keys()
        for field in fields:
            assert not any(word in field.lower() for word in forbidden), \
                f"{name} lets the model pass {field!r}"


def test_the_writing_tools_take_no_arguments_at_all(run):
    """Stronger than the check above and the reason it holds.

    A tool with no parameters cannot be pointed at a different plan, so it
    cannot inherit an approval given about a different domain. That property is
    the design; anything the model could name would be a way around it.
    """
    specs = _specs(repair_mod.repair_tools(run))

    for name in repair_mod.WRITES | {"plan_repair"}:
        fields = specs[name]["inputSchema"]["json"].get("properties") or {}
        assert fields == {}, f"{name} takes {sorted(fields)}"


# ---- 2. what the repair node can reach -------------------------------------


def test_the_repair_node_holds_exactly_three_tools(run):
    """Without this the allowlist is a comment.

    The failure it prevents is not subtle: hand this node the provider's own
    write toolsets and the model has a route to the same DNS that never passes
    the gate, and every claim above becomes decorative.
    """
    assert set(_specs(repair_mod.repair_tools(run))) == repair_mod.NAMES


def test_the_repair_node_is_never_given_provider_toolsets():
    """`build` shares read-only toolsets with the nodes that may only read.
    If they ever reach the repair node they arrive unfiltered, because
    `toolset_for` defaults to no filter, so this asserts where they go."""
    from munim.agent import graph as graph_mod

    source = inspect.getsource(graph_mod.build)
    fixing = source.split("fixing = Agent(", 1)[1].split(")", 1)[0]

    assert "repair_tools" in fixing, "the repair node lost its own tools"
    assert "toolsets" not in fixing and "reading" not in fixing, \
        "the repair node was given provider tools, which bypasses the gate"


def test_only_the_room_and_the_cli_record_decisions():
    """`approval.record` is the one function that turns a click into consent.
    Nothing under agent/ may call it: an agent that could record a decision
    could approve itself, and every other guarantee here would be theatre."""
    agent_dir = Path(repair_mod.__file__).parent
    offenders = [p.name for p in agent_dir.glob("*.py")
                 if "approval.record" in p.read_text(encoding="utf-8")]

    assert offenders == [], \
        f"these can record their own approval: {', '.join(offenders)}"


# ---- 3. the gate itself -----------------------------------------------------


class _Use(dict):
    pass


class _Event:
    """Enough of BeforeToolCallEvent to exercise the gate.

    `interrupt` is the real contract: raises the first time, returns the
    person's answer on the resume. Modelled rather than mocked away, because
    the two-phase behaviour is the whole mechanism.
    """

    def __init__(self, name, answer=None):
        self.tool_use = {"name": name}
        self.cancel_tool = None
        self._answer = answer
        self.asked = 0

    def interrupt(self, name, reason=None):
        self.asked += 1
        if self._answer is None:
            raise RuntimeError("would have interrupted")
        return self._answer


class _Change:
    def __init__(self, action="merge"):
        self.purpose, self.type, self.name = "SPF", "TXT", "acme.example"
        self.action, self.current, self.note = action, ["v=spf1 a ~all"], ""
        self.content = "v=spf1 a include:b ~all"

    @property
    def needs_a_person(self):
        return self.action in ("update", "merge")


class _Plan:
    def __init__(self, changes):
        self.plan_id, self.domain = "p1", "acme.example"
        self.changes = changes

    @property
    def needs_approval(self):
        return [c for c in self.changes if c.needs_a_person]


def test_a_change_that_replaces_something_stops_and_asks(run):
    run.plan = _Plan([_Change("merge")])
    guard = gate_mod.ApprovalGate(run)
    event = _Event("apply_repair")

    with pytest.raises(RuntimeError):
        guard.before_tool_call(event)

    assert event.asked == 1
    asked = approval.question(run.run_id, "p1")
    assert asked is not None, "the room was never told what to show"
    assert asked["changes"][0]["current"] == ["v=spf1 a ~all"]


def test_creating_a_record_that_is_absent_does_not_ask(run):
    """Not an oversight. `Change.needs_a_person` already draws this line and is
    already tested; gating what the existing code deliberately does not gate
    would reverse a decision by accident."""
    run.plan = _Plan([_Change("create")])
    guard = gate_mod.ApprovalGate(run)
    event = _Event("apply_repair")

    guard.before_tool_call(event)

    assert event.asked == 0
    assert event.cancel_tool is None


def test_a_refusal_cancels_the_tool(run):
    run.plan = _Plan([_Change("merge")])
    guard = gate_mod.ApprovalGate(run)
    event = _Event("apply_repair", answer="reject")

    guard.before_tool_call(event)

    assert event.cancel_tool, "a refusal did not stop the write"


def test_an_approval_lets_it_through(run):
    run.plan = _Plan([_Change("merge")])
    guard = gate_mod.ApprovalGate(run)
    event = _Event("apply_repair", answer=gate_mod.YES)

    guard.before_tool_call(event)

    assert event.cancel_tool is None


def test_a_reading_tool_is_not_gated(run):
    run.plan = _Plan([_Change("merge")])
    guard = gate_mod.ApprovalGate(run)
    event = _Event("show_current")

    guard.before_tool_call(event)

    assert event.asked == 0


def test_a_refusal_is_told_apart_from_a_crash():
    """`cancel_node` reaches the caller as a RuntimeError carrying its message,
    the same type a real fault arrives as. Without the marker a deliberate
    policy refusal would be reported to the operator as a traceback."""
    refusal = RuntimeError(f"{gate_mod.WriteGuard.MARK} no API key for resend")
    crash = RuntimeError("connection reset by peer")

    assert gate_mod.refused_in(refusal) == "no API key for resend"
    assert gate_mod.refused_in(crash) == ""
