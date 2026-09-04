"""Setting up email for a client, across two companies.

This is the handoff. Resend emits DKIM, SPF and return-path records; Cloudflare
is where they have to be published. Two dashboards, two logins, and a dozen
values copied between them by eye, once per client.

Three things make it worth automating rather than checklisting:

  - **It fails invisibly.** A wrong A record means the site does not load and you
    know in minutes. A wrong DKIM record means nothing at all - the client's mail
    simply stops being trusted, and nobody finds out for weeks.
  - **The names change shape.** Resend returns them relative to the domain;
    Cloudflare wants them fully qualified. `resend._domainkey` published as-is is
    a record nobody can find.
  - **An existing SPF record turns an append into a fault.** If the domain
    already has one, adding Resend's beside it means receivers ignore both. That
    is a merge, and a merge is a judgement call.
"""

from dataclasses import dataclass, field

from munim.adapters.cloudflare import Cloudflare, CloudflareError
from munim.adapters.resend import Resend
from munim.agent.spf import merge_spf, within_lookup_limit
from munim.checks import dns as checks

# Reached through the module rather than imported by name. `from x import query`
# binds a reference at import time, so a caller that swaps the resolver - which
# run_all_async does to serve checks from one concurrent fetch - would be ignored
# here, and this file would go on making its own uncached lookups.
from munim.container import Container
from munim.runlog import RunLog


class NeedsAPerson(Exception):
    """The agent stopped because a person has to decide."""


@dataclass
class MailSetup:
    domain: str
    published: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    merged: str | None = None
    verification: str = ""


async def set_up_mail(container: Container, domain: str, log: RunLog, *,
                      approve=None) -> MailSetup:
    """Create the sending domain and publish what it asks for.

    `approve` is called before anything that changes a record already in place.
    Creating a record that does not exist is not a judgement call; replacing one
    that does is, because someone put it there on purpose.
    """
    client = container.client
    resend = Resend(container, log)
    cloudflare = Cloudflare(container, log)
    result = MailSetup(domain=domain)

    log.append(client=client, stage="mail", kind="stage_start",
               human_text=f"Setting up email for {domain}")

    sending, action = await resend.ensure_domain(domain)
    zone = await cloudflare.zone_id(domain)

    records = Resend.cloudflare_records(sending)
    log.append(client=client, stage="mail", kind="observation",
               human_text=f"{len(records)} records to publish, "
                          f"{'created' if action == 'created' else 'already set up'}",
               detail={"records": [r["purpose"] for r in records]})

    for record in records:
        is_spf = record["purpose"] == "SPF" and record["type"] == "TXT"
        if is_spf:
            outcome = await _publish_spf(cloudflare, zone, record, domain,
                                         log, client, approve, result)
        else:
            outcome = await _publish(cloudflare, zone, record, log, client)
        (result.published if outcome != "unchanged" else result.unchanged).append(
            f"{record['purpose']} {record['name']}")

    result.verification = await resend.verify(sending.id)
    log.append(client=client, stage="mail", kind="stage_done",
               human_text=("Email is set up. It can take a few minutes for other "
                           "mail servers to see it."),
               detail={"status": result.verification,
                       "published": len(result.published),
                       "unchanged": len(result.unchanged)})
    return result


async def _publish(cloudflare: Cloudflare, zone: str, record: dict,
                   log: RunLog, client: str) -> str:
    _, outcome = await cloudflare.upsert(
        zone, type=record["type"], name=record["name"],
        content=record["content"],
        # A DKIM CNAME behind Cloudflare's proxy is rewritten and stops
        # verifying, which is the second item in the check catalogue.
        proxied=False,
    )
    return outcome


async def _publish_spf(cloudflare: Cloudflare, zone: str, record: dict,
                       domain: str, log: RunLog, client: str,
                       approve, result: MailSetup) -> str:
    """Publishing SPF is where appending causes the fault we exist to catch."""
    # Read the records directly rather than through spf_single's detail: that
    # key is only populated on the failure path, so a domain with exactly ONE
    # existing policy looked like a domain with none, and this appended a second
    # - producing the duplicate-SPF fault this whole tool exists to detect.
    already = [t for t in checks.query(record["name"], "TXT")
               if t.lower().startswith("v=spf1")]
    existing = checks.spf_single(record["name"])

    if not already:
        return await _publish(cloudflare, zone, record, log, client)

    if len(already) == 1 and already[0] == record["content"]:
        return "unchanged"

    combined = merge_spf([*already, record["content"]])
    if not within_lookup_limit(combined.merged):
        raise NeedsAPerson(
            f"Combining the sender policies on {domain} would need "
            f"{combined.lookups} DNS lookups and the limit is 10, so the result "
            "would fail as well. Someone has to decide which senders to drop."
        )

    log.append(client=client, stage="mail", kind="finding",
               human_text=(f"This domain already has {len(already)} sender "
                           "polic" + ("ies" if len(already) > 1 else "y") +
                           ". Adding another does not combine them - receivers "
                           "would ignore all of them and your mail would "
                           "authenticate as none."),
               detail={"check": "spf_single", "evidence": existing.evidence,
                       "resolver": existing.resolver,
                       "operator_text": existing.operator_text})

    log.append(client=client, stage="mail", kind="awaiting_confirm",
               human_text=(f"Combine into one policy keeping all "
                           f"{len(combined.senders)} senders?"),
               detail={"check": "spf_single", "merged": combined.merged,
                       "senders": combined.senders, "replacing": already})

    if approve is None or not approve(combined.merged):
        raise NeedsAPerson("Waiting for approval before changing live DNS.")

    await cloudflare.merge_spf(zone, record["name"], combined.merged)
    result.merged = combined.merged

    after = checks.spf_single(record["name"])
    log.append(client=client, stage="mail",
               kind="resolved" if after.status == "pass" else "observation",
               human_text=("One sender policy now, covering every sender."
                           if after.status == "pass" else
                           "Written; other mail servers may take a few minutes "
                           "to see the change."),
               detail={"check": "spf_single", "evidence": after.evidence})
    return "merged"
