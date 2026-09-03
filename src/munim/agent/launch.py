"""The launch agent.

Division of labour, and the reason there is one (D7):

  The checks are deterministic. `munim.checks.dns` decides pass or fail from a
  DNS answer, and the model never touches that - it cannot invent a record or
  argue a failing check into passing.

  The agent does the part a rule engine is bad at: working out *why* something
  failed when the evidence is ambiguous, deciding whether a person is needed,
  and saying it to a business owner in words they can act on.

Everything it does is appended to the run log, which is what the terminal and
the control room both read.
"""

import asyncio
from dataclasses import asdict

from strands import Agent, tool

from munim.agent.model import build_model
from munim.checks.dns import CheckResult, query, run_all
from munim.runlog import RunLog, new_run_id

SYSTEM = """You are Munim, an agent that looks after small businesses' web and email setup.

You are given the results of deterministic checks. You never decide whether a
check passed - that is already settled, and you must not contradict it.

Your job, for each failure:
  1. Say what is actually wrong, in one sentence, to the business owner. They are
     not technical. Never use jargon without explaining it in the same sentence.
  2. Say what it costs them in practice. Be concrete: mail landing in spam,
     customers seeing a warning, invoices not arriving.
  3. Decide whether you can fix it yourself or whether a person must decide.
     Anything that changes a live record in someone else's account needs a person.

Use look_up when you need more evidence before explaining a failure. Do not
guess at a cause you have not looked at.

Be brief. No preamble, no apology, no restating the question."""


def _tools(domain: str, log: RunLog, client: str):
    @tool
    def look_up(name: str, record_type: str) -> str:
        """Look up a DNS record. Use this to gather evidence before diagnosing.

        Args:
            name: the fully qualified name, e.g. _dmarc.example.com
            record_type: TXT, MX, NS, A, AAAA or CAA
        """
        answers = query(name, record_type.upper())
        log.append(client=client, stage="diagnose", kind="observation",
                   human_text=f"Looked up {record_type.upper()} for {name}",
                   detail={"name": name, "type": record_type.upper(),
                           "answers": answers, "resolver": "1.1.1.1"})
        return "\n".join(answers) if answers else "(no records)"

    return [look_up]


async def run_checks(domain: str, client: str, log: RunLog,
                     dkim_selector: str = "resend") -> list[CheckResult]:
    """Deterministic. Each result is written to the run log as it lands."""
    log.append(client=client, stage="verify", kind="stage_start",
               human_text=f"Checking {domain}")
    results = await asyncio.to_thread(run_all, domain, dkim_selector=dkim_selector)
    for r in results:
        if r.status == "skip":
            continue
        log.append(
            client=client, stage="verify",
            kind="observation" if r.status == "pass" else "finding",
            human_text=r.human_text or r.operator_text,
            detail={"check": r.check, "operator_text": r.operator_text,
                    "evidence": r.evidence, "resolver": r.resolver, **r.detail},
        )
    log.append(client=client, stage="verify", kind="stage_done",
               human_text=f"{sum(r.status == 'pass' for r in results)} of "
                          f"{sum(r.status != 'skip' for r in results)} checks passed")
    return results


async def explain(domain: str, client: str, failures: list[CheckResult],
                  log: RunLog) -> str:
    """The model's part: diagnose and write for the owner."""
    if not failures:
        return "Everything checked out."

    model, label = build_model()
    agent = Agent(model=model, tools=_tools(domain, log, client), system_prompt=SYSTEM)
    log.append(client=client, stage="diagnose", kind="stage_start",
               human_text=f"Working out what to tell {client}", detail={"model": label})

    findings = "\n".join(
        f"- {r.check}: {r.operator_text}" + (f"\n  evidence: {r.evidence}" if r.evidence else "")
        for r in failures
    )
    reply = await agent.invoke_async(
        f"Domain: {domain}\nBusiness: {client}\n\nFailing checks:\n{findings}\n\n"
        "For each one, write the owner-facing explanation and say whether you can "
        "fix it or a person must decide."
    )
    text = str(reply)
    log.append(client=client, stage="diagnose", kind="stage_done",
               human_text=text.strip()[:400], detail={"model": label})
    return text


async def launch(domain: str, client: str, *, dkim_selector: str = "resend",
                 runs_dir=None) -> RunLog:
    log = RunLog(new_run_id(), runs_dir)
    results = await run_checks(domain, client, log, dkim_selector)
    failures = [r for r in results if r.status == "fail"]
    if failures:
        await explain(domain, client, failures, log)
    log.append(client=client, stage="verify", kind="run_done",
               human_text=f"Finished checking {domain}.",
               detail={"failures": [asdict(f)["check"] for f in failures]})
    return log
