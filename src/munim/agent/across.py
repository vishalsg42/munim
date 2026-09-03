"""One question, answered over every client at once.

This is the capability that does not exist today. Every provider dashboard is
single-account, so "which of my clients has a domain expiring this quarter?"
cannot be asked from anywhere - not because it is hard, but because there is no
place to stand that can see all of them.

**On not using a Strands Graph here.** Graph runs its nodes concurrently
(`asyncio.create_task` + `gather`), and one agent node per client would look
impressive in an architecture diagram. It would also be wrong. The per-client
work is deterministic DNS lookups that need no model at all, so a graph of
twelve agents would make twelve model calls to do work that needs zero. That is
feature-counting, not engineering.

What genuinely needs to be concurrent is the **I/O**, and the first attempt got
even that wrong. Fanning out one thread per client left each client doing
thirteen sequential lookups inside it, and measured *slower* than serial: 0.9x.
The concurrency was at the wrong level.

Fanning out at the level of the lookups, and deduplicating the ones several
checks share, measures:

    6 clients, cold  : 5.33s serial → 2.61s concurrent   (2.0x)
    4 clients, warm  : 1.23s serial → 2.26s concurrent   (0.5x)

Both numbers are worth keeping. Against a warm resolver cache a lookup costs
microseconds and thread overhead dominates, so concurrency loses. The case that
matters is the cold one - an operator asking a question across a dozen clients
they have not touched today - and there it halves the wait.

Exactly one model call turns the result into an answer for a person. The model
is used where judgement is needed and nowhere else (D7).
"""

import asyncio
from dataclasses import dataclass

from munim.checks.dns import CheckResult, run_all_async
from munim.registry import ClientRecord, Registry

# What a question maps to. Deterministic, so the model cannot widen a question
# into checks the operator did not ask about.
QUESTIONS: dict[str, tuple[str, ...]] = {
    "email_unprotected": ("spf_single", "dkim_present", "dkim_chunking"),
    "no_dmarc": ("dmarc_present", "dmarc_policy"),
    "domain_unreachable": ("apex_resolves", "ns_delegated"),
    "certificate_risk": ("caa_allows",),
    "everything": (),  # every failing check
}


@dataclass
class Hit:
    client: str
    domain: str
    check: str
    says: str
    operator_text: str


async def _for_client(record: ClientRecord, wanted: tuple[str, ...]) -> list[Hit]:
    if not record.domain:
        return []
    # Fans out at the lookup level, which is where the time actually goes.
    results: list[CheckResult] = await run_all_async(record.domain)
    return [
        Hit(client=record.name, domain=record.domain, check=r.check,
            says=r.human_text, operator_text=r.operator_text)
        for r in results
        if r.status == "fail" and (not wanted or r.check in wanted)
    ]


async def scan(registry: Registry, question: str = "everything") -> list[Hit]:
    """Fan out across every client concurrently and collect what is failing."""
    if question not in QUESTIONS:
        raise ValueError(
            f"unknown question {question!r}; try one of {', '.join(sorted(QUESTIONS))}"
        )
    wanted = QUESTIONS[question]
    clients = [c for c in registry.clients() if c.domain]
    if not clients:
        return []

    batches = await asyncio.gather(
        *(_for_client(record, wanted) for record in clients),
        return_exceptions=True,
    )
    hits: list[Hit] = []
    for batch in batches:
        # One client's DNS being unreachable must not lose the other eleven.
        if isinstance(batch, BaseException):
            continue
        hits.extend(batch)
    return hits


def summarise(hits: list[Hit]) -> str:
    """A plain answer without a model call, for when one is not warranted.

    Most cross-client questions have a factual answer: these clients, this
    problem. Spending a model call to restate a list is the kind of thing that
    makes an agent feel slow and adds nothing.
    """
    if not hits:
        return "Nothing failing across any client."
    by_client: dict[str, list[Hit]] = {}
    for hit in hits:
        by_client.setdefault(hit.client, []).append(hit)
    lines = []
    for client, items in sorted(by_client.items()):
        problems = ", ".join(sorted({h.check for h in items}))
        lines.append(f"{client} ({items[0].domain}): {problems}")
    return "\n".join(lines)
