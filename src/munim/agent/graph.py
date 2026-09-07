"""Three agents, two edges, and a boundary that is not a prompt.

`check` explains what is wrong. This repairs it, and the difference is that
something in somebody else's account changes, so the interesting part is not the
agents. It is what decides whether the repairing one is ever reached.

**The edge is the boundary.** The thirteen checks run before the graph, as they
always have, and the predicate on the `triage -> repair` edge reads those
results. It never reads what a model said. A model that is confident, wrong, or
talked into it cannot traverse an edge, because the edge is not listening to it.

That is the whole argument for a graph here rather than one agent with more
tools, and it is worth being precise about, because using more of an SDK is not
the same as using it well. In a `Swarm` the diagnosing model decides to hand off
to the repairing one. That is model-chosen control flow, and it is the one thing
this product must not have: D5 says reads may span clients and writes may not,
D7 says enumeration is deterministic and only judgement is model work. A swarm
would put the write boundary inside the model's discretion. A graph puts it in a
predicate over DNS answers.

The nodes hold different tools, and that is the isolation rather than an
instruction. `triage` physically cannot write: it holds read-only toolsets. The
repair node holds three tools, two of which take no arguments. Neither has to be
trusted to stay in its lane, because neither has the means to leave it.
"""

import logging

from strands import Agent
from strands.multiagent import GraphBuilder

from munim.agent import repair as repair_mod
from munim import approval, words
from munim.agent.gate import YES, ApprovalGate, WriteGuard, refused_in
from munim.agent.model import agents_off, build_model
from munim.agent.repair import RepairRun
from munim.agent.watch import RunLogHooks
from munim.checks.dns import is_platform_domain

logger = logging.getLogger(__name__)

# The failures a mail plan can actually produce a record for. Not a guess and
# not "anything that failed": `mailplan.plan` builds its changes from what
# Resend publishes for a sending domain, so routing a CAA or certificate
# failure into the repair node would arrive with one tool that sets up mail and
# nothing that addresses the fault. The model would then either say so, which
# wastes a node, or improvise, which is worse.
REPAIRABLE = frozenset({
    "spf_single", "spf_lookups", "dkim_present", "dkim_chunking",
    "dmarc_present", "mx_present",
})

TRIAGE = """You are looking at one client's web and email setup.

The checks have already run and their results are below. They are facts: you
cannot argue a failing check into passing, and you should not try.

Say what is wrong and what it means for the business, in words the owner could
act on. Use show_current when you need more evidence than the results give you.

Repair nothing. You have no tool that could, and the next step decides whether
a repair happens at all.

Be brief. No preamble."""

RECHECK = """The repair has been carried out. Say whether it took.

One thing to hold on to: DNS is not instant. A record written a moment ago may
not be visible to the resolver you are reading from yet, and that is not the
same as the repair having failed. If a record you expect is missing, say it has
not appeared yet rather than saying it did not work.

Be brief. No preamble."""


def mail_is_repairable(state, *, invocation_state=None, **_) -> bool:
    """Whether the repair node is reached. Deterministic, every term of it.

    Three questions, none of which a model answers: is there a failure this
    repair path can actually fix, does this client have the credentials the
    repair needs, and is this a domain anybody is allowed to change.
    """
    run = (invocation_state or {}).get("run")
    if run is None:
        return False
    if not run.can_write:
        return False
    # D20: a vercel.app or pages.dev name belongs to the platform. Nobody's
    # mail is served from it and nothing here should try to publish to it.
    if is_platform_domain(run.domain):
        return False
    return any(getattr(r, "status", "") == "fail"
               and getattr(r, "check", "") in REPAIRABLE
               for r in run.results)


def something_was_published(state, *, invocation_state=None, **_) -> bool:
    """Whether there is anything to re-check. Set by the tool that wrote it."""
    run = (invocation_state or {}).get("run")
    return bool(run is not None and run.applied)


def why_repair_was_skipped(run: RepairRun) -> str:
    """The sentence for a skipped repair, so the room shows a reason.

    An edge that does not traverse is silent, and in the rail a silent step is
    indistinguishable from one that hung. That was the whole complaint against
    the ghost stage cells, and re-introducing it one layer up would be worse,
    because here there really was a decision and it really had a reason.
    """
    if not run.can_write:
        return run.why_not()
    if is_platform_domain(run.domain):
        return (f"{run.domain} is a platform domain, so its DNS is not "
                f"{run.client}'s to change")
    repairable = [r for r in run.results
                  if getattr(r, "status", "") == "fail"
                  and getattr(r, "check", "") in REPAIRABLE]
    if not repairable:
        failing = [getattr(r, "check", "?") for r in run.results
                   if getattr(r, "status", "") == "fail"]
        if not failing:
            return "nothing is failing, so there is nothing to repair"
        return (f"nothing failing here is repairable by the mail setup path: "
                f"{', '.join(failing)}")
    return ""


def build(run: RepairRun, *, toolsets=None):
    """The graph. Returns `(graph, gate)`, because the caller needs the gate.

    `toolsets` are read-only provider tools for triage, built once by the caller
    and shared rather than rebuilt per node: an `MCPClient` opens and closes a
    session around each agent that holds it, so three nodes each building their
    own means every provider is connected three times per run.
    """
    model, label = build_model()
    logger.debug("building the repair graph on %s", label)

    reading = [*repair_mod.read_tools(run), *(toolsets or [])]

    watching = RunLogHooks(run)
    tools_watch = watching.tool_hooks()
    gate = ApprovalGate(run)

    triage = Agent(model=model, tools=reading, system_prompt=TRIAGE,
                   callback_handler=None, hooks=[tools_watch])
    fixing = Agent(model=model, tools=repair_mod.repair_tools(run),
                   system_prompt=repair_mod.SYSTEM, callback_handler=None,
                   hooks=[gate, tools_watch])
    rechecking = Agent(model=model, tools=reading, system_prompt=RECHECK,
                       callback_handler=None, hooks=[tools_watch])

    builder = GraphBuilder()
    builder.add_node(triage, "triage")
    builder.add_node(fixing, "repair")
    builder.add_node(rechecking, "recheck")
    builder.add_edge("triage", "repair", condition=mail_is_repairable)
    builder.add_edge("repair", "recheck", condition=something_was_published)
    builder.set_entry_point("triage")
    # Every Strands limit defaults to None, meaning no limit, and `build()`
    # warns when both the count and the timeout are unset. Six allows one full
    # pass plus a resume; the node timeout is generous because a node may be
    # waiting on a provider, and measured on 1.54.0 a person's thinking time is
    # not charged against either.
    builder.set_max_node_executions(6)
    builder.set_node_timeout(180)
    builder.set_execution_timeout(900)
    builder.set_hook_providers([watching, WriteGuard(run)])
    return builder.build(), gate


def task_for(run: RepairRun) -> str:
    """What the graph is asked. The findings travel as words for the model and
    as objects in `invocation_state` for the edges; these are the words."""
    failing = [r for r in run.results if getattr(r, "status", "") == "fail"]
    lines = "\n".join(
        f"- {getattr(r, 'check', '?')}: {getattr(r, 'human_text', '') or getattr(r, 'operator_text', '')}"
        for r in failing) or "- nothing is failing"
    return (f"Client: {run.client}\nDomain: {run.domain}\n\n"
            f"Failing checks:\n{lines}\n\n"
            f"Work out what is wrong, then repair what can be repaired.")


async def fix(domain: str, client: str, *, client_id: str, container,
              log, dkim_selector: str = "resend", toolsets=None,
              keyring=None, timeout: float | None = None) -> dict:
    """Check, repair what can be repaired, and wait for a person if asked.

    Every exit path writes `run_done`, and that is not tidiness. The control
    room decides a run is over by finding that event, and `_finished` treats a
    run without one as still going forever. A run that ends any other way pins
    the room to itself: every later request for the newest run resolves the
    stale one and replays it. One missing event would take the demo surface
    down permanently, so the writes are in a `finally`.
    """
    from munim.agent.launch import run_checks

    results = await run_checks(domain, client, log, dkim_selector,
                               container=container, client_id=client_id,
                               keyring=keyring)
    run = RepairRun(run_id=log.run_id, client=client, client_id=client_id,
                    domain=domain, log=log, container=container,
                    results=results)
    failures = [r for r in results if getattr(r, "status", "") == "fail"]
    out: dict = {"client": client, "domain": domain, "run_id": log.run_id,
                 "failing": [{"check": r.check, "says": r.human_text}
                             for r in failures],
                 "repaired": [], "awaiting": None, "approved_by": None}

    try:
        off = agents_off()
        if off is not None:
            # The deterministic half already ran and its findings stand. Only
            # the explaining and the repairing needed a model, exactly as
            # `check` degrades.
            log.append(client=client, stage="repair", kind="observation",
                       human_text="Agents are off, so nothing was repaired.",
                       detail={"agents": "off", "stage": "repair"})
            return {**out, **off}

        skipped = why_repair_was_skipped(run)
        if skipped:
            # Say why, rather than letting an untraversed edge read as a step
            # that hung. The room renders this as a dashed cell with a reason,
            # reusing the affordance built for agents being off.
            log.append(client=client, stage="repair", kind="observation",
                       human_text=f"Not repairing {domain}: {skipped}",
                       detail={"agents": "off", "stage": "repair",
                               "why": skipped})
            out["why"] = skipped

        graph, _gate = build(run, toolsets=toolsets)
        state = {"run": run}

        try:
            result = await graph.invoke_async(task_for(run), state)
        except RuntimeError as exc:
            refused = refused_in(exc)
            if not refused:
                raise
            # A refusal that reads as a crash is worse than no guard at all.
            log.append(client=client, stage="repair", kind="escalated",
                       human_text=f"Refused to repair {domain}: {refused}",
                       detail={"refused": refused})
            return {**out, "why": refused}

        while result.interrupts:
            plan = run.plan
            if plan is None:                      # cannot happen; do not hang
                break
            out["awaiting"] = {"plan_id": plan.plan_id, "domain": plan.domain}
            decided = await approval.wait_for(
                run.run_id, plan.plan_id,
                timeout=approval.WAIT if timeout is None else timeout)

            if decided is None:
                # Running out of time is a refusal that can be retried, never a
                # yes that arrived quietly. Resume so the graph cancels the tool
                # and finishes cleanly rather than being abandoned mid-node.
                log.append(client=client, stage="repair", kind="escalated",
                           human_text=("Nobody approved this in time, so "
                                       "nothing was changed."),
                           detail={"plan_id": plan.plan_id,
                                   "decision": "timed out"})
                out["why"] = (
                    f"{words.count(len(plan.needs_approval), 'record')} already exist "
                    f"and nobody approved replacing them.")
                out["or_call"] = (f'apply_mail_setup("{client}", '
                                  f'"{plan.plan_id}", approved=true)')
            elif not decided.approved:
                log.append(client=client, stage="repair", kind="escalated",
                           human_text=f"{client} did not approve the change.",
                           detail={"plan_id": plan.plan_id,
                                   "decision": "rejected"})
                out["approved_by"] = decided.by
            else:
                out["approved_by"] = decided.by

            answer = YES if (decided and decided.approved) else "reject"
            result = await graph.invoke_async(
                [{"interruptResponse": {"interruptId": i.id,
                                        "response": answer}}
                 for i in result.interrupts], state)

        out["awaiting"] = None if run.applied else out["awaiting"]
        out["said"] = str(result).strip()[:600]
        if run.applied and run.plan is not None:
            out["repaired"] = [f"{c.purpose} {c.name}"
                               for c in run.plan.changes
                               if c.action != "unchanged"]
        return out
    finally:
        log.append(client=client, stage="repair", kind="run_done",
                   human_text=f"Finished with {domain}.",
                   detail={"applied": run.applied,
                           "failures": [getattr(r, "check", "?")
                                        for r in failures]})
