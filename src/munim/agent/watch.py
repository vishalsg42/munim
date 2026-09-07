"""The run log, written by the framework rather than by hand.

Every stage boundary in the repair graph is already a Strands lifecycle event.
Writing `log.append` calls beside each one re-derives something the SDK knows
and then drifts from it, which is how `stage="work"` came to exist in
`within.py` and never appear in the control room's rail.

Two registration points, and getting them the wrong way round fails silently
rather than loudly:

    node events   -> the **graph**  (GraphBuilder.set_hook_providers)
    tool events   -> each **agent** (Agent(hooks=[...]))

A graph fires only `MultiAgentInitializedEvent`, the two invocation events and
the two node events on its own registry. `BeforeToolCallEvent` is fired by the
tool executor on the Agent's registry. `HookRegistry.add_callback` validates
nothing, so a tool callback registered on a graph is accepted and never called.

What this cannot replace, and should not try to: the per-`CheckResult` entries
`run_checks` writes. Those come from deterministic code outside the graph and
there is no lifecycle event for them. The honest split is that the framework
reports the agent's work and `run_checks` reports the checks' work.
"""

import logging

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import (
    AfterNodeCallEvent,
    AfterToolCallEvent,
    BeforeNodeCallEvent,
)

from munim.agent.repair import WRITES

logger = logging.getLogger(__name__)


class RunLogHooks(HookProvider):
    """Node boundaries and tool calls, into the log the control room tails."""

    # Node ids are for the graph; stages are what the room's rail renders and
    # what every existing run in the log already uses. Keeping them separate
    # means a node can be renamed without invalidating three years of logs.
    STAGE = {"triage": "diagnose", "repair": "repair", "recheck": "recheck"}

    def __init__(self, run) -> None:
        self.run = run

    # ---- registered on the graph ----------------------------------------

    def register_hooks(self, registry: HookRegistry, **_) -> None:
        registry.add_callback(BeforeNodeCallEvent, self.before_node_call)
        registry.add_callback(AfterNodeCallEvent, self.after_node_call)

    def before_node_call(self, event: BeforeNodeCallEvent) -> None:
        stage = self.STAGE.get(event.node_id, event.node_id)
        self.run.log.append(
            client=self.run.client, stage=stage, kind="stage_start",
            human_text=_opening(event.node_id, self.run),
            detail={"node": event.node_id})

    def after_node_call(self, event: AfterNodeCallEvent) -> None:
        stage = self.STAGE.get(event.node_id, event.node_id)
        self.run.log.append(
            client=self.run.client, stage=stage, kind="stage_done",
            human_text=_said(event), detail={"node": event.node_id})

    # ---- registered on each node's agent ---------------------------------

    def tool_hooks(self) -> "ToolLogHooks":
        """The half that has to go on the Agent rather than the graph."""
        return ToolLogHooks(self.run)


class ToolLogHooks(HookProvider):
    """One entry per tool call, and the honest distinction between two kinds.

    A tool that changed something is a `mutation` and a tool that read
    something is an `observation`. The list of which is which is
    `repair.WRITES`, an allowlist rather than a guess from the tool's name, for
    the same reason `call_provider_tool` only claims `observation` when the
    provider itself said `readOnlyHint`.
    """

    def __init__(self, run) -> None:
        self.run = run

    def register_hooks(self, registry: HookRegistry, **_) -> None:
        registry.add_callback(AfterToolCallEvent, self.after_tool_call)

    def after_tool_call(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use.get("name", "a tool")
        # A cancelled tool did not run, so it changed nothing, whatever it is
        # normally capable of. Recording it as a mutation would put a write in
        # the log that never happened.
        cancelled = getattr(event, "cancel_tool", None)
        changed = name in WRITES and not cancelled
        self.run.log.append(
            client=self.run.client,
            stage="repair" if name in WRITES else "diagnose",
            kind="mutation" if changed else "observation",
            human_text=_tool_line(name, cancelled),
            detail={"tool": name, **({"cancelled": str(cancelled)}
                                     if cancelled else {})})


def _opening(node_id: str, run) -> str:
    return {
        "triage": f"Working out what is wrong with {run.domain}",
        "repair": f"Repairing {run.domain}",
        "recheck": f"Checking whether the change to {run.domain} took",
    }.get(node_id, f"{node_id} for {run.client}")


def _said(event: AfterNodeCallEvent) -> str:
    """What the node answered.

    `AfterNodeCallEvent` carries no result, only the node id and the source, so
    the text has to be fetched from the graph's own state. A node that failed or
    was cancelled is not in `results` at all, which is why this is guarded
    rather than indexed.
    """
    # `event.source` is typed as `MultiAgentBase`, which declares no `state`;
    # only `Graph` has one. Reached through getattr so the guard is the thing
    # doing the work rather than an assumption about the concrete class.
    state = getattr(event.source, "state", None)
    results = getattr(state, "results", None) or {}
    result = results.get(event.node_id)
    if result is None:
        return "(no answer recorded)"
    return str(result).strip()[:400] or "(said nothing)"


def _tool_line(name: str, cancelled) -> str:
    if cancelled:
        return f"{name} was stopped: {cancelled}"
    return {
        "show_current": "Read a record as it is published now",
        "plan_repair": "Worked out what would change",
        "apply_repair": "Carried out the plan",
        "look_up": "Looked up a DNS record",
    }.get(name, f"Called {name}")
