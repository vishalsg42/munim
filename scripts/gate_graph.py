"""Day-one gate: can a Strands graph stop and wait for a person, then carry on?

The repair work depends on five things being true at once, and every one of them
is a claim about the SDK rather than about this codebase. Being wrong about any
of them is worth knowing on day one rather than on the day the video is shot,
which is the same reason `gate_strands.py` exists.

What is being proved, in the order it has to hold:

  1. A tool that takes **no arguments at all** builds, and its input schema is
     empty. That is the whole approval guarantee: if the model cannot name a
     plan, it cannot inherit a decision made about a different one.
  2. A two-node graph builds with a conditional edge whose predicate reads
     `invocation_state` rather than the model's prose.
  3. An interrupt raised from `BeforeToolCallEvent` pauses the node instead of
     failing it, and `invoke_async` **returns** a result carrying the interrupt.
  4. Resuming with an `interruptResponse` lands back inside the paused tool call
     and the tool actually runs.
  5. Refusing sets `cancel_tool`, and the tool does not run.

It also measures the thing nobody documents: whether the human's thinking time
is charged against the graph's own timeouts. If it is, a five minute wait for a
person is not possible and the whole approach has to change.

Run it with a real model host, because the round trip includes the model
re-issuing the same tool call after the pause, and a fake model cannot prove
that. Reuses the host fallback from `gate_strands.py` for the same reason it
exists there: Bedrock is blocked account-wide for some entrants.
"""

import asyncio
import sys
import time

from munim.env import load as load_env
from strands import Agent, tool
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import BeforeToolCallEvent
from strands.multiagent import GraphBuilder

load_env()

# What the fake operator says when the graph stops and asks. Set per run.
ANSWER = "approve"

# Set by the tool when it actually executes, which is the only honest proof it
# ran. A model saying it applied something is not evidence.
PUBLISHED: list[str] = []


@tool
async def apply_repair() -> str:
    """Carry out the repair that was planned. Takes no arguments on purpose."""
    PUBLISHED.append("applied")
    return "Published 1 record."


@tool
async def look_up(name: str) -> str:
    """Look up a DNS record so you have evidence before deciding."""
    return f"{name} has one SPF record and no DKIM record."


class ApprovalGate(HookProvider):
    """Stops the write and asks a person. The tool body never runs unapproved.

    Registered on the repair **agent**, not on the graph. Tool call events fire
    on the Agent's own registry; a graph only ever fires node and invocation
    events, and `HookRegistry.add_callback` validates nothing, so registering
    this in the wrong place would be silent rather than an error.
    """

    def __init__(self) -> None:
        self.asked = 0

    def register_hooks(self, registry: HookRegistry, **_) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        if event.tool_use["name"] != "apply_repair":
            return
        self.asked += 1
        # Raises the first time. Returns the person's answer on the resume,
        # because the graph replays the same tool call with the same id.
        answer = event.interrupt("approve_the_change",
                                 reason={"what": "one SPF record"})
        if answer != "approve":
            event.cancel_tool = "the operator did not approve this change"


def build(model, gate):
    """Two nodes, one conditional edge that never reads the model's words."""
    triage = Agent(model=model, tools=[look_up], callback_handler=None,
                   system_prompt="Look up the domain, then say in one sentence "
                                 "what is wrong. Do not repair anything.")
    repair = Agent(model=model, tools=[apply_repair], callback_handler=None,
                   hooks=[gate],
                   system_prompt="Call apply_repair once to fix what triage "
                                 "found, then say what you did in one line.")

    builder = GraphBuilder()
    builder.add_node(triage, "triage")
    builder.add_node(repair, "repair")
    builder.add_edge("triage", "repair", condition=repairable)
    builder.set_entry_point("triage")
    builder.set_max_node_executions(6)
    builder.set_node_timeout(120)
    builder.set_execution_timeout(600)
    return builder.build()


def repairable(state, *, invocation_state=None, **_) -> bool:
    """The edge predicate. Deterministic evidence, never the model's prose."""
    return bool((invocation_state or {}).get("run", {}).get("failures"))


async def run(model, label) -> int:
    gate = ApprovalGate()
    graph = build(model, gate)
    task = ("Domain: example.test\nBusiness: The Bakery\n\n"
            "Failing checks:\n- dkim_present: no DKIM record is published\n\n"
            "Diagnose it, then repair it.")
    state = {"run": {"failures": ["dkim_present"]}}

    # ---- 1. the zero-argument tool -------------------------------------
    schema = apply_repair.tool_spec["inputSchema"]["json"]
    props = schema.get("properties") or {}
    if props:
        print(f"  FAIL: apply_repair exposes parameters: {sorted(props)}")
        return 1
    print("  ok   a tool with no arguments builds, and its schema is empty")

    # ---- 2 and 3. the pause --------------------------------------------
    began = time.monotonic()
    first = await graph.invoke_async(task, state)
    if not first.interrupts:
        print(f"  FAIL: the graph ran to completion without stopping to ask. "
              f"status={first.status}, gate asked {gate.asked} time(s)")
        return 1
    if PUBLISHED:
        print("  FAIL: the write happened before anyone approved it")
        return 1
    print(f"  ok   the graph stopped and asked, and returned a result "
          f"({len(first.interrupts)} interrupt) rather than raising")

    # ---- the question nobody documents ---------------------------------
    thinking = 3.0
    await asyncio.sleep(thinking)

    # ---- 4. the resume --------------------------------------------------
    answers = [{"interruptResponse": {"interruptId": i.id, "response": ANSWER}}
               for i in first.interrupts]
    second = await graph.invoke_async(answers, state)
    elapsed = time.monotonic() - began

    if ANSWER == "approve":
        if not PUBLISHED:
            print(f"  FAIL: approved, but the tool never ran. "
                  f"status={second.status}")
            return 1
        print("  ok   approving resumed the graph inside the paused tool call")
    else:
        if PUBLISHED:
            print("  FAIL: refused, and the write happened anyway")
            return 1
        print("  ok   refusing cancelled the tool and published nothing")

    # `execution_timeout` is 600 and the node timeout 120. If the human's wait
    # were charged against either, a real five minute pause would be impossible.
    print(f"  ok   {thinking:.0f}s of thinking time did not end the run "
          f"(total wall clock {elapsed:.1f}s, node timeout 120s)")
    print(f"GATE PASSED via {label}")
    return 0


def main() -> int:
    from gate_strands import try_anthropic, try_bedrock, try_gemini

    global ANSWER
    if "--refuse" in sys.argv:
        ANSWER = "reject"
        print("running the refusal path")

    failures = []
    for make in (try_bedrock, try_gemini, try_anthropic):
        try:
            model, label = make()
        except Exception as exc:
            failures.append(f"{make.__name__}: {exc}")
            continue
        try:
            return asyncio.run(run(model, label))
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")

    print("GATE FAILED. Every model host was tried:")
    for line in failures:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    sys.exit(main())
