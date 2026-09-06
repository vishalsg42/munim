"""Whether the agent's advice still says what it used to say.

**What this is not.** It is not evidence that the advice is good. This repository
argues in `DECISIONS.md` that fixtures would not have found the bugs real client
infrastructure found in an afternoon, and `SUBMISSION.md` says nothing shown is a
fixture. Both stand. This is regression pinning: fixed inputs, a real model, and
a table that says whether the answer drifted. The evidence of capability is still
the live findings.

**Why the agent and not the checks.** The 13 checks decide pass or fail from a
DNS answer and are unit-tested. Scoring those would be tests wearing a different
hat. The one place munim produces a judgement is `explain`: given failing checks,
say what is wrong, what it costs, and what to do. That is the thing that can
quietly get worse when a prompt or a model changes.

**Why the rubric is shaped the way it is.** The obvious version asks whether the
answer names the fault and avoids a forbidden word. That is defeated by
paraphrase, and an independent review produced the answer that defeats it:

    "...two sender policy records, so receivers treat neither as authoritative.
     Keep the record that lists your current provider and let the other one
     lapse. Safe to apply straight away."

It names the fault, never says "add", invents no record, and is wrong twice: DNS
records do not lapse, and it skips the ten-lookup limit. A rubric that passes
that is measuring vocabulary. So each expectation here is about the **action**:
the right operation on the right target, existing values preserved, and an
abstention where the evidence does not support acting. Where a rubric cannot
separate understanding from wording, the fixture says so instead of scoring it.

**And it is advisory.** The table prints the model's own sentence beside the
verdict, which concedes that a person is the judge. So it exits 0 whatever
happens: a machine verdict that gates a build would be claiming more than a
keyword predicate can carry.

**Samples, because one is not a measurement.** The first two live runs of this
file disagreed with each other on every fixture: the same model, minutes apart,
described the fault both times and prescribed the repair only once. A single
sample cannot tell that apart from a regression, so each fixture is run several
times and the table reports how many passed. A fixture that passes 3 of 3 has
settled; one that passes 2 of 3 is telling you the advice is not reliable, which
is a finding about the agent rather than noise to be averaged away.
"""

import asyncio
import re
import sys
from dataclasses import dataclass, field

from munim.checks.dns import CheckResult
from munim.pick import AMBER, DIM, GREEN, RED, paint

# What the agent is asked to explain, and what a correct answer has to do with
# it. Each fixture is a real failure shape taken from the check catalogue.
#
# `must` and `must_not` are matched against the answer in lower case. They are
# deliberately about the operation, not the noun: "delete the second record" and
# "keep only the first" are the same instruction, so a rubric that names one has
# to name the other.


@dataclass
class Fixture:
    name: str
    why: str                       # what a reader should know this is testing
    failures: list[CheckResult]
    must: list[list[str]] = field(default_factory=list)
    must_not: list[list[str]] = field(default_factory=list)
    unscored: str = ""             # set when a rubric cannot honestly decide


def _spf_two() -> CheckResult:
    return CheckResult(
        "spf_single", "fail",
        "2 SPF records. RFC 7208 says a domain with more than one is in error; "
        "receivers ignore all of them.",
        "This domain has more than one sender policy. They do not combine, both "
        "are ignored, and your mail authenticates as neither.",
        evidence=('bakery.test. IN TXT "v=spf1 include:_spf.google.com ~all"\n'
                  'bakery.test. IN TXT "v=spf1 include:amazonses.com -all"'),
        resolver="1.1.1.1",
        detail={"records": ["v=spf1 include:_spf.google.com ~all",
                            "v=spf1 include:amazonses.com -all"]})


def _dmarc_monitor() -> CheckResult:
    return CheckResult(
        "dmarc_enforced", "fail",
        "DMARC policy is p=none, which asks receivers to report and act on "
        "nothing.",
        "Your domain publishes a policy that tells other mail servers to take "
        "no action, so anyone forging your address is not stopped.",
        evidence='_dmarc.bakery.test. IN TXT "v=DMARC1; p=none; rua=mailto:a@b.test"',
        resolver="1.1.1.1", detail={"policy": "none"})


def _dkim_missing() -> CheckResult:
    return CheckResult(
        "dkim_present", "fail",
        "No DKIM record at resend._domainkey.",
        "Nothing signs your outgoing mail, so receivers cannot prove it really "
        "came from you.",
        evidence="resend._domainkey.bakery.test. -> (no records)",
        resolver="1.1.1.1", detail={"selector": "resend"})


FIXTURES = [
    Fixture(
        name="two_spf",
        why="The failure that costs a client their mail if answered wrongly: "
            "the two policies must be combined, not one of them deleted.",
        failures=[_spf_two()],
        # Combining, in any of the words a model actually uses for it. Naming
        # the operation rather than a keyword, because "merge", "combine" and
        # "into one" are the same instruction.
        must=[["combine", "merge", "into one", "single record", "one record"]],
        # Deleting either sender loses that sender's mail. Every phrasing of
        # "get rid of one of them" is the same wrong action.
        must_not=[["delete the", "remove the", "let the other", "lapse",
                   "keep only", "drop the"]],
    ),
    Fixture(
        name="dmarc_monitor_only",
        why="p=none is a real policy that does nothing. Moving straight to "
            "reject without a monitoring period is how legitimate mail starts "
            "bouncing.",
        failures=[_dmarc_monitor()],
        must=[["quarantine", "gradual", "monitor", "reports", "step"]],
        must_not=[["p=reject immediately", "straight to reject",
                   "set it to reject now"]],
    ),
    Fixture(
        name="dkim_missing",
        why="There is no correct record to write here: the value comes from "
            "the mail provider. The only right answer is to fetch it, and the "
            "wrong one is to invent a key.",
        failures=[_dkim_missing()],
        must=[["resend", "provider", "dashboard"]],
        must_not=[["v=dkim1; k=rsa; p=mii", "p=miibijanbgkq"]],
    ),
    Fixture(
        name="two_spf_and_no_dkim",
        why="Two faults at once. A model that answers the loudest and drops "
            "the other is worse than one that answers neither, because the "
            "operator stops looking.",
        failures=[_spf_two(), _dkim_missing()],
        must=[["combine", "merge", "into one", "single record", "one record"],
              ["dkim", "sign", "signing"]],
        unscored="Whether the two are ordered sensibly is a judgement no "
                 "predicate here can make. Read the sentences.",
    ),
]


def _hit(answer: str, any_of: list[str]) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in any_of)


@dataclass
class Scored:
    fixture: Fixture
    answer: str
    missing: list[list[str]]
    forbidden: list[list[str]]
    error: str = ""

    @property
    def status(self) -> str:
        """A missed action is a failure even where a judgement remains.

        `unscored` came first here, which meant a fixture carrying a note about
        something no predicate can judge could never fail at all. The first live
        run printed `unscored` beside "did not say any of: combine, merge, ..."
        for an answer that had missed a required action outright. `unscored` is
        the honest verdict only when everything mechanical passed and a human
        judgement is what is left.
        """
        if self.error:
            return "error"
        if self.missing or self.forbidden:
            return "fail"
        return "unscored" if self.fixture.unscored else "pass"


async def _run_one(fixture: Fixture, *, runs_dir=None) -> Scored:
    from munim.agent.launch import explain
    from munim.runlog import RunLog, new_run_id

    log = RunLog(new_run_id(), runs_dir)
    try:
        answer = await explain("bakery.test", "The Bakery", fixture.failures, log)
    except Exception as exc:
        return Scored(fixture, "", [], [], error=f"{type(exc).__name__}: {exc}")

    missing = [need for need in fixture.must if not _hit(answer, need)]
    forbidden = [bad for bad in fixture.must_not if _hit(answer, bad)]
    return Scored(fixture, answer, missing, forbidden)


MARK = {"pass": ("✓", GREEN), "fail": ("✗", RED),
        "unreliable": ("~", AMBER),
        "unscored": ("·", DIM), "error": ("!", AMBER)}

# Enough to separate "this always happens" from "this happened once", and few
# enough that the whole table is one coffee rather than one afternoon.
SAMPLES = 3


@dataclass
class Run:
    """Every sample of one fixture, and what they agreed on."""

    fixture: Fixture
    samples: list[Scored]

    @property
    def passed(self) -> int:
        return sum(s.status in ("pass", "unscored") for s in self.samples)

    @property
    def status(self) -> str:
        if all(s.status == "error" for s in self.samples):
            return "error"
        if self.passed == 0:
            return "fail"
        if self.passed < len(self.samples):
            # The interesting verdict, and the one a single run cannot produce.
            return "unreliable"
        return "unscored" if self.fixture.unscored else "pass"


def _sentence(answer: str) -> str:
    """The model's first sentence, which is what a reader judges."""
    flat = re.sub(r"\s+", " ", answer).strip()
    cut = re.split(r"(?<=[.!?]) ", flat)
    return (cut[0] if cut else flat)[:150]


def run(runs_dir=None, only: str = "", samples: int = SAMPLES) -> int:
    """Print the table. Always exits 0: see the module docstring."""
    from munim.agent.model import agents_off

    off = agents_off()
    if off is not None:
        print(f"{off['why']}\n  → {off['fix']}", file=sys.stderr)
        return 0

    chosen = [f for f in FIXTURES if not only or f.name == only]
    if not chosen:
        print(f"No fixture named {only!r}. Known: "
              f"{', '.join(f.name for f in FIXTURES)}", file=sys.stderr)
        return 2

    runs = [Run(f, [asyncio.run(_run_one(f, runs_dir=runs_dir))
                    for _ in range(samples)])
            for f in chosen]

    width = max(len(r.fixture.name) for r in runs) + 2
    pad = " " * (width + 2)
    print()
    for r in runs:
        glyph, colour = MARK[r.status]
        print(f"{paint(glyph, colour)} {r.fixture.name.ljust(width)}"
              f"{r.status}  {r.passed}/{len(r.samples)}")
        first = r.samples[0]
        if first.error:
            print(f"{pad}{first.error}")
            continue
        # What the failing samples were missing, not the passing ones.
        for sample in r.samples:
            for need in sample.missing:
                print(f"{pad}did not say any of: {', '.join(need)}")
            for bad in sample.forbidden:
                print(f"{pad}recommended: {', '.join(bad)}")
        if r.fixture.unscored:
            print(f"{pad}{r.fixture.unscored}")
        # The model's own words, because the rubric is advisory and the reader
        # is the judge. A table of verdicts with the answers hidden would be
        # asking to be trusted about exactly the thing it cannot decide.
        for sample in r.samples:
            print(f"{pad}{paint(_sentence(sample.answer), DIM)}")
    print()

    settled = sum(r.status in ("pass", "unscored") for r in runs)
    shaky = [r.fixture.name for r in runs if r.status == "unreliable"]
    print(f"{settled} of {len(runs)} fixtures answered the same way every time"
          f", over {samples} samples each.")
    if shaky:
        print(paint(f"Not settled: {', '.join(shaky)}. The advice changed "
                    f"between runs of the same model, which is a finding about "
                    f"the agent rather than noise.", AMBER))
    print(paint("Advisory. These pin drift, not correctness: read the "
                "sentences.", DIM))
    return 0
