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
from munim.agent.dmarc import strengthened
from munim.agent.spf import merge_spf, within_lookup_limit
from munim.container import Container, UnknownCredential
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
    # What could not be planned, and why, when the rest of the plan still
    # stands. Distinct from `blocked`, which means nothing here can be applied:
    # a client with no Resend session can still have their DMARC policy raised,
    # and refusing the whole plan over the half that needs a credential is what
    # left a diagnosable fault unfixable (#56).
    skipped: list[str] = field(default_factory=list)

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


async def _dmarc_change(cloudflare: Cloudflare, zone: str,
                        domain: str) -> list[Change]:
    """Raise a published DMARC policy, or nothing.

    Derived from what is in the zone rather than from a provider, which is the
    point: no mail provider publishes a DMARC record, so this was the one fault
    the catalogue could see and the plan could never touch.

    Never creates one. A DMARC record needs an `rua` for the reports, nobody
    has told Munim which mailbox that is, and publishing enforcement with
    nowhere to send failures is worse than publishing nothing. `dmarc_present`
    keeps reporting that as a fault, correctly, and it is a fault a person
    resolves.
    """
    name = f"_dmarc.{domain}"
    published = await cloudflare.records(zone, type="TXT", name=name)
    for record in published:
        raised = strengthened(record.content)
        if raised:
            return [Change(
                "DMARC", "TXT", name, raised, "update", [record.content],
                "raises the policy from monitoring to quarantine, keeping "
                "every other tag. A person has to approve it: mail that was "
                "failing authentication silently starts being quarantined.")]
    return []


async def plan(container: Container, domain: str, log: RunLog) -> MailPlan:
    """What setting up mail for this domain would change. Touches no DNS."""
    client = container.client
    resend = Resend(container, log)
    cloudflare = Cloudflare(container, log)

    log.append(client=client, stage="mail", kind="stage_start",
               human_text=f"Working out what {domain} needs")

    zone = await cloudflare.zone_id(domain)

    changes: list[Change] = []
    blocked = ""
    skipped: list[str] = []

    # Resend supplies DKIM, SPF and MX and has no opinion about DMARC, so a
    # missing Resend session used to end the plan before the DMARC record was
    # ever looked at. The two halves are separate now: what Resend knows, and
    # what is already published.
    wanted: list[dict] = []
    try:
        sending, _ = await resend.ensure_domain(domain)
        wanted = Resend.cloudflare_records(sending)
    except UnknownCredential as missing:
        # `container.label` and not `client`, which is the id credentials are
        # filed under. A fix line that tells somebody to type
        # `munim connect "c_0123..."` is Munim's bookkeeping leaking into an
        # instruction, and it is the third time that has happened here.
        skipped.append(
            f"{missing}. DKIM, SPF and MX come from Resend, so those are not "
            f"in this plan. Connect it with: "
            f"munim connect \"{container.label}\" resend --token")

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

    changes.extend(await _dmarc_change(cloudflare, zone, domain))

    if not changes and skipped:
        # Nothing to apply and a reason worth repeating where `apply` and
        # `plan_repair` both already look.
        blocked = " ".join(skipped)

    made = MailPlan(plan_id=new_run_id(), client=client, domain=domain,
                    changes=changes, blocked=blocked, skipped=skipped)
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
