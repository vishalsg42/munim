"""The tools that change something, and the reason the model cannot approve.

Everything the repair node can do to a client's account is in this file. There
are three tools and no others: read a record as it stands, work out what would
change, and carry that out. No provider MCP toolsets, no raw HTTP, no escape
hatch. The whole route to somebody's live DNS is `mailplan`, which computes a
diff, refuses before the network when a person has to decide, and is the only
repair path in this project with tests behind it.

**The two writing tools take no arguments at all**, and that is the guarantee
rather than a style. If `apply_repair(plan_id)` existed, the model could name
the plan id of a change approved earlier, sitting in `~/.munim/plans/`, and
inherit somebody's answer about a different domain. With no parameters, the only
influence the model has over the write is whether to call it, and calling it is
what raises the question rather than answering it.

Said once, plainly, because it is the sentence the design is for:

    The model chooses whether to act, never on what, and never whether it was
    allowed to.
"""

import asyncio
from dataclasses import dataclass, field

from strands import tool

from munim import approval
from munim.agent import mailplan
from munim.checks.dns import query
from munim.container import Container, UnknownCredential
from munim.runlog import RunLog

SYSTEM = """You are repairing one client's email setup, and only that one.

Work in this order and do not skip it:

  1. Call plan_repair once. It reads what is published now and works out what
     would change. It changes nothing.
  2. Say, in plain words, what would change and what is there today. Somebody
     who does not know DNS has to be able to follow it.
  3. Call apply_repair once to carry the plan out.

apply_repair may stop and wait for a person. That is normal and it is not an
error: replacing a record somebody already published is their decision, not
yours. If it comes back saying nobody approved it, say so and stop. Do not look
for another way to make the change.

You have no other way to change anything, by design. If the fault is not one
these tools address, say which one it is and that it needs a person.

Be brief. No preamble."""


@dataclass
class RepairRun:
    """Everything one repair knows about itself.

    One instance per run, handed to the graph as `invocation_state` and captured
    in the tool closures, so the edge conditions and the tools read the same
    object. Nothing depends on how Strands forwards keyword arguments into a
    tool, which is the part that would break quietly on an SDK upgrade.
    """

    run_id: str
    client: str        # the label a person reads
    client_id: str     # the identity credentials are filed under
    domain: str
    log: RunLog
    container: Container | None = None
    results: list = field(default_factory=list)
    plan: mailplan.MailPlan | None = None
    applied: bool = False

    @property
    def can_write(self) -> bool:
        """Whether a repair could even be attempted for this client.

        `container.can_reach` rather than `container.has`, and the difference
        is the whole of this edge. `has` answers about the pasted-key store
        alone, so a client connected by OAuth to both providers, whose repair
        now runs over those sessions, was refused here on a precondition that
        had stopped being true. An edge that guards against the wrong thing is
        worse than no edge: it refuses quietly and correctly-looking.
        """
        if self.container is None:
            return False
        return all(self.container.can_reach(p) for p in ("cloudflare", "resend"))

    def why_not(self) -> str:
        """Why a repair cannot run, in words, or empty when it can."""
        if self.container is None:
            return "no credentials are loaded for this client"
        missing = [p for p in ("cloudflare", "resend")
                   if not self.container.can_reach(p)]
        if missing:
            names = " and ".join(missing)
            return (f"{self.client} is not connected to {names}, so there is "
                    f"nothing to repair through. Connect with: munim connect "
                    f'"{self.client}" {missing[0]}')
        return ""


def tools_for(run: RepairRun) -> dict:
    """The three tools, closed over one run. Nothing else reaches an account.

    Returned by name so the reading one can be handed to the nodes that may
    only read, without defining it twice or handing them the writing ones.
    """

    @tool
    async def show_current(name: str, record_type: str) -> str:
        """Read a DNS record as it is published right now.

        Args:
            name: the fully qualified name, e.g. acme.example or _dmarc.acme.example
            record_type: TXT, MX, NS, A, AAAA or CAA
        """
        answers = await asyncio.to_thread(query, name, record_type.upper())
        return "\n".join(answers) if answers else "(nothing published)"

    @tool
    async def plan_repair() -> str:
        """Work out what would change to fix this domain's mail.

        Reads what is published and returns each record with its current value
        beside the value it would become. Changes no client DNS. Takes no
        arguments: it plans for the domain this run is about and no other.
        """
        if run.container is None:
            return "No credentials are loaded for this client, so nothing can be planned."
        try:
            made = await mailplan.plan(run.container, run.domain, run.log)
        except UnknownCredential as missing:
            return f"Cannot plan: {missing}"
        run.plan = made

        if made.blocked:
            return f"Nothing can be applied: {made.blocked}"
        if not made.changes:
            return "Nothing to change; the records are already correct."

        lines = [f"plan {made.plan_id} for {made.domain}:"]
        for change in made.changes:
            now = ", ".join(change.current) if change.current else "(nothing published)"
            lines.append(f"- {change.purpose} {change.type} {change.name} "
                         f"[{change.action}]\n    now:  {now}\n"
                         f"    next: {change.content}")
        waiting = len(made.needs_approval)
        if waiting:
            lines.append(f"{waiting} of these would replace a record somebody "
                         f"already published, so a person has to approve it.")
        return "\n".join(lines)

    @tool
    async def apply_repair() -> str:
        """Carry out the plan you just made.

        Takes no arguments, on purpose: it applies the plan from this run and
        cannot be pointed at another. If the plan would replace a record that
        already exists, this stops and waits for a person, and you will be told
        what they decided.
        """
        if run.plan is None or run.container is None:
            # Both are unreachable in practice, because `plan_repair` refuses
            # without a container and leaves `plan` unset. Stated rather than
            # relied on: "cannot happen" is how a write into the wrong account
            # gets written.
            return "There is no plan yet. Call plan_repair first."

        # Read the answer rather than being handed one. The gate hook has
        # already stopped this call and asked, so by the time the body runs the
        # decision is on disk. Re-reading it here rather than trusting the hook
        # is deliberate: a hook that failed to register must not silently become
        # an approval, and this is the check that would notice.
        decided = approval.read(run.run_id, run.plan.plan_id)
        approved = bool(decided and decided.approved)

        try:
            done = await mailplan.apply(run.container, run.plan, run.log,
                                        approved=approved)
        except mailplan.NotApproved as why:
            return (f"Not applied. {why} Approve it in the control room, or "
                    f"call apply_mail_setup with approved=true.")

        run.applied = True
        published = done.get("published") or []
        unchanged = done.get("unchanged") or []
        return (f"Published {len(published)}: {', '.join(published) or 'nothing'}."
                + (f" Left alone: {', '.join(unchanged)}." if unchanged else ""))

    return {"show_current": show_current, "plan_repair": plan_repair,
            "apply_repair": apply_repair}


def repair_tools(run: RepairRun) -> list:
    """Everything the repair node gets. Three tools, and no fourth."""
    return list(tools_for(run).values())


def read_tools(run: RepairRun) -> list:
    """What a node that may only read gets. One tool, and it reads DNS."""
    return [tools_for(run)["show_current"]]


# The names the gate stops, and the names a test pins. An allowlist that is only
# a comment is not an allowlist.
WRITES = frozenset({"apply_repair"})
NAMES = frozenset({"show_current", "plan_repair", "apply_repair"})
