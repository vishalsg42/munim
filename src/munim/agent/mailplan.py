"""Mail setup as a plan you can read, then a plan you can apply.

`set_up_mail` takes an `approve` callback and calls it mid-flight. That works
from Python and cannot cross an MCP tool boundary: a tool call returns once, so
there is nowhere for a question to go. The consequence was that the repair
existed and no tool could reach it, which an external reviewer found before we
did.

Split in two. `plan` reads what is there and says what would change. `apply`
takes a plan the operator has seen and carries it out. Approval stops being a
callback and becomes the gap between two calls, which is the only shape that
survives the boundary.

One honesty note, because it would otherwise be a surprise: planning creates
the sending domain in Resend if it does not exist. Resend does not publish the
DKIM and SPF values a plan is made of until the domain exists, so there is no
reading them first. That write lands in the operator's own Resend account, adds
nothing to anyone's DNS, and is idempotent. Every change to a client's live
records is in `apply` and nowhere else.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from munim.adapters.cloudflare import Cloudflare
from munim.adapters.resend import Resend
from munim.agent.spf import merge_spf, within_lookup_limit
from munim.container import Container
from munim.runlog import RunLog, new_run_id

PLANS_DIR = Path.home() / ".munim" / "plans"


@dataclass
class Change:
    """One record, and what would happen to it."""
    purpose: str
    type: str
    name: str
    content: str
    action: str          # create | update | merge | unchanged
    current: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def needs_a_person(self) -> bool:
        """Creating a record nobody put there is not a judgement call.
        Replacing or combining one somebody did is."""
        return self.action in ("update", "merge")


@dataclass
class MailPlan:
    plan_id: str
    client: str
    domain: str
    changes: list[Change]
    blocked: str = ""

    @property
    def needs_approval(self) -> list[Change]:
        return [c for c in self.changes if c.needs_a_person]

    def to_dict(self) -> dict:
        return {**asdict(self), "needs_approval": len(self.needs_approval)}


def _save(plan: MailPlan) -> Path:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLANS_DIR / f"{plan.plan_id}.json"
    path.write_text(json.dumps({**asdict(plan),
                                "made_at": datetime.now(timezone.utc).isoformat()},
                               indent=2))
    return path


def load(plan_id: str) -> MailPlan:
    path = PLANS_DIR / f"{plan_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no plan {plan_id!r}. Make one with plan_mail_setup.")
    raw = json.loads(path.read_text())
    raw.pop("made_at", None)
    raw["changes"] = [Change(**c) for c in raw["changes"]]
    return MailPlan(**raw)


async def plan(container: Container, domain: str, log: RunLog) -> MailPlan:
    """What setting up mail for this domain would change. Touches no DNS."""
    client = container.client
    resend = Resend(container, log)
    cloudflare = Cloudflare(container, log)

    log.append(client=client, stage="mail", kind="stage_start",
               human_text=f"Working out what {domain} needs")

    sending, _ = await resend.ensure_domain(domain)
    zone = await cloudflare.zone_id(domain)
    wanted = Resend.cloudflare_records(sending)

    changes: list[Change] = []
    blocked = ""

    for record in wanted:
        existing = [r for r in await cloudflare.records(
            zone, type=record["type"], name=record["name"])]
        contents = [r.content for r in existing]

        if record["purpose"] == "SPF" and record["type"] == "TXT":
            policies = [c for c in contents if c.lower().startswith("v=spf1")]
            if not policies:
                action, note = "create", ""
            elif policies == [record["content"]]:
                action, note = "unchanged", ""
            else:
                merged = merge_spf(policies + [record["content"]])
                if not within_lookup_limit(merged.merged):
                    blocked = (
                        f"Combining these sender policies would need "
                        f"{merged.lookups} DNS lookups and the limit is 10, so "
                        f"the merged policy would fail too. Someone has to "
                        f"decide which senders to drop.")
                    action, note = "merge", blocked
                else:
                    action = "merge"
                    note = (f"combines {len(policies) + 1} policies, keeping "
                            f"{len(merged.senders)} senders")
                    record = {**record, "content": merged.merged}
            changes.append(Change(record["purpose"], record["type"], record["name"],
                                  record["content"], action, policies, note))
            continue

        if not existing:
            action = "create"
        elif contents == [record["content"]]:
            action = "unchanged"
        else:
            action = "update"
        changes.append(Change(record["purpose"], record["type"], record["name"],
                              record["content"], action, contents))

    made = MailPlan(plan_id=new_run_id(), client=client, domain=domain,
                    changes=changes, blocked=blocked)
    _save(made)

    log.append(client=client, stage="mail", kind="stage_done",
               human_text=(f"{sum(1 for c in changes if c.action != 'unchanged')} "
                           f"of {len(changes)} records would change"),
               detail={"plan_id": made.plan_id,
                       "needs_approval": len(made.needs_approval)})
    return made


class NotApproved(Exception):
    """The plan changes something a person put there and nobody said yes."""


async def apply(container: Container, made: MailPlan, log: RunLog, *,
                approved: bool = False) -> dict:
    """Carry out a plan the operator has seen.

    `approved` is the gap between two tool calls, which is what a callback
    could never be across an MCP boundary. It is required only when the plan
    would replace or combine a record somebody put there on purpose; creating
    one that does not exist is not a judgement call.
    """
    # Before anything, including a read. A refusal that has already opened a
    # session has already done something.
    if made.blocked:
        raise NotApproved(made.blocked)
    if made.needs_approval and not approved:
        raise NotApproved(
            f"{len(made.needs_approval)} of these change records that are "
            f"already there: "
            + "; ".join(f"{c.purpose} {c.name}" for c in made.needs_approval)
            + ". Re-run with approved=true once the operator has agreed."
        )

    client = container.client
    cloudflare = Cloudflare(container, log)
    zone = await cloudflare.zone_id(made.domain)
    published, unchanged = [], []

    log.append(client=client, stage="mail", kind="stage_start",
               human_text=f"Applying the plan for {made.domain}",
               detail={"plan_id": made.plan_id})

    for change in made.changes:
        if change.action == "unchanged":
            unchanged.append(f"{change.purpose} {change.name}")
            continue
        if change.action == "merge":
            await cloudflare.merge_spf(zone, change.name, change.content)
        else:
            await cloudflare.upsert(
                zone, type=change.type, name=change.name,
                content=change.content,
                # A DKIM CNAME behind Cloudflare's proxy is rewritten and stops
                # verifying, which is the second item in the check catalogue.
                proxied=False)
        published.append(f"{change.purpose} {change.name}")

    verification = await Resend(container, log).verify(
        (await Resend(container, log).find(made.domain)).id)

    log.append(client=client, stage="mail", kind="stage_done",
               human_text=("Email is set up. It can take a few minutes for other "
                           "mail servers to see it."),
               detail={"plan_id": made.plan_id, "published": len(published),
                       "status": verification})
    return {"plan_id": made.plan_id, "domain": made.domain,
            "published": published, "unchanged": unchanged,
            "verification": verification}
