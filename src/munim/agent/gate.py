"""The stop, and the second one behind it.

Two hook providers, kept apart from the logging one on purpose: these decide
things. Mixing "write down what happened" with "refuse to let this happen" in
one class makes the security property something you have to read a loop to
find, and makes it impossible to test one without the other.

`ApprovalGate` stops a write and asks a person. `WriteGuard` refuses to enter
the repair node at all when the conditions that let it be reached have stopped
being true.
"""

import logging

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import BeforeNodeCallEvent, BeforeToolCallEvent

from munim import approval, words
from munim.agent.model import agents_off
from munim.agent.repair import WRITES, RepairRun

logger = logging.getLogger(__name__)

# The word the person's answer becomes on the way back in. Anything else, and
# anything absent, is a refusal.
YES = "approve"


class ApprovalGate(HookProvider):
    """Stops before replacing a record somebody already published.

    Registered on the repair **agent**, never on the graph. Tool call events
    fire on an Agent's own registry; a graph fires only node and invocation
    events. `HookRegistry.add_callback` validates nothing, so registering this
    in the wrong place produces silence rather than an error, and silence here
    means every write goes through unapproved.

    The mechanism is Strands' own interrupt rather than a wait inside the tool.
    `event.interrupt(...)` raises the first time, the graph snapshots the node's
    messages and model state and returns a result carrying the interrupt, and
    on resume the same call returns the person's answer. Measured on 1.54.0: the
    person's thinking time is not charged against the node or execution timeout,
    so a five minute pause is actually possible.
    """

    def __init__(self, run: RepairRun) -> None:
        self.run = run
        self.asked = 0

    def register_hooks(self, registry: HookRegistry, **_) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        if event.tool_use["name"] not in WRITES:
            return
        plan = self.run.plan
        if plan is None:
            return          # nothing planned yet; the tool says so itself

        # Creating a record that is absent is not a judgement call; replacing
        # one somebody put there on purpose is. `Change.needs_a_person` already
        # draws that line and is already tested, so do not redraw it here.
        # Gating what the existing code deliberately does not gate would be
        # reversing a decision by accident.
        if not plan.needs_approval:
            return

        if self.asked == 0:
            self._ask(plan)
        self.asked += 1

        answer = event.interrupt("approve_dns_change", reason={
            "plan_id": plan.plan_id, "domain": plan.domain,
            "client": self.run.client,
            "changes": [c.purpose for c in plan.needs_approval]})

        if answer != YES:
            event.cancel_tool = (
                f"{self.run.client} did not approve replacing "
                f"{words.count(len(plan.needs_approval), 'record')} on {plan.domain}")

    def _ask(self, plan) -> None:
        """Post the question where a person can see it, once.

        Both halves matter. `approval.ask` is what the control room renders,
        and the run log entry is what makes the card appear at all: the room is
        a tail of that file and knows nothing else.
        """
        changes = [{"purpose": c.purpose, "type": c.type, "name": c.name,
                    "action": c.action, "current": list(c.current),
                    "content": c.content, "note": c.note}
                   for c in plan.needs_approval]
        approval.ask(self.run.run_id, plan.plan_id, client=self.run.client,
                     domain=plan.domain, changes=changes)
        waiting = len(changes)
        self.run.log.append(
            client=self.run.client, stage="repair", kind="awaiting_confirm",
            human_text=(f"{words.count(waiting, 'record')} on {plan.domain} already exist. "
                        f"Replacing them is {self.run.client}'s decision."),
            detail={"plan_id": plan.plan_id, "domain": plan.domain,
                    "changes": changes})


class WriteGuard(HookProvider):
    """Refuses to enter the repair node when it should no longer be entered.

    The edge condition and this ask the same question at different times, and
    the gap between them is real: agents can be switched off mid-run, a
    credential can be deleted, a container can go away. Small window, and the
    cost of being wrong is a write into somebody else's account.

    It is also the louder failure. An edge that does not traverse is silent, and
    a silent stop looks exactly like a hang. A cancelled node emits an event,
    lands in `state.failed_nodes`, and can be reported.

    **What cancelling actually does**, because the name suggests otherwise:
    `graph.py:1010` raises `RuntimeError` after yielding its cancel event, and
    that propagates all the way out of `stream_async`, so `invoke_async` never
    returns a result at all. The caller has to catch it and tell a deliberate
    refusal from a crash. `refused_in` below is how it tells.

    Not used for approval. At node entry no decision exists yet, so checking one
    here would either be vacuous or would gate the node's reading tools too.
    """

    MARK = "munim-refused:"

    def __init__(self, run: RepairRun, node_id: str = "repair") -> None:
        self.run = run
        self.node_id = node_id

    def register_hooks(self, registry: HookRegistry, **_) -> None:
        registry.add_callback(BeforeNodeCallEvent, self.before_node_call)

    def before_node_call(self, event: BeforeNodeCallEvent) -> None:
        if event.node_id != self.node_id:
            return
        why = self._why_not()
        if why:
            logger.info("refusing the repair node: %s", why)
            event.cancel_node = f"{self.MARK} {why}"

    def _why_not(self) -> str:
        # Re-read rather than trust what was true when the graph was built.
        if agents_off() is not None:
            return ("agents were switched off while this run was going, so "
                    "nothing further reached a model")
        return self.run.why_not()


def refused_in(error: Exception) -> str:
    """The reason, if this exception is our own refusal rather than a fault.

    `cancel_node` reaches the caller as a `RuntimeError` carrying the message,
    indistinguishable by type from a real failure. The marker is how a refusal
    that is working as designed avoids being reported as a crash.
    """
    text = str(error)
    if WriteGuard.MARK not in text:
        return ""
    return text.split(WriteGuard.MARK, 1)[1].strip()
