"""Raising a DMARC policy without losing what else it said.

`dmarc_policy` has failed on a real client's domain since the check catalogue
was written, and nothing could repair it. The plan is built from
`Resend.cloudflare_records`, which returns what Resend publishes: DKIM, SPF and
MX. Resend has no opinion about DMARC, so no DMARC record ever entered a plan,
for any client, connected to anything. The fault was diagnosable and not
fixable, which is the gap `fix` exists to close (#56).

Two rules, and both come from what the record is.

**Only raise an existing record, never invent one.** A DMARC record needs an
`rua` address for the reports to go to, and nobody has told Munim what mailbox
that is. Publishing `p=quarantine` with nowhere to send failures would take a
domain from "not protected" to "protected and nobody is watching", which is
worse and looks better.

**Keep every other tag, in order.** A real record carries `rua`, `ruf`, `pct`,
`sp`, `adkim`, `aspf`, `fo`, and an operator chose them. Rewriting the record
from a template would quietly drop the reporting address, which is the tag that
tells them whether the change was safe.
"""

import re

# The order matters to nobody except a person reading their own zone file, and
# that is reason enough to preserve it rather than normalise it.
_POLICY = re.compile(r"^\s*p\s*=\s*(none|quarantine|reject)\s*$", re.I)

# Weakest first. "Raise" means "move up this list", so a domain already at
# reject is left alone rather than walked backwards to quarantine.
STRENGTH = ("none", "quarantine", "reject")


def policy_of(record: str) -> str:
    """The `p=` value, or "none" when it is absent or unreadable.

    Matches `checks/dns.py:dmarc_policy`, which defaults the same way. RFC 7489
    says a record with no `p` is discarded by receivers, but the check calls
    that "monitoring only" and an operator reading two different answers to the
    same question would be right to distrust both.
    """
    for tag in record.split(";"):
        found = _POLICY.match(tag)
        if found:
            return found.group(1).lower()
    return "none"


def strengthened(record: str, to: str = "quarantine") -> str:
    """The same record with its policy raised, or "" when there is nothing to do.

    Empty rather than the unchanged record, so a caller cannot mistake "already
    strong enough" for "here is a change to publish".
    """
    if to not in STRENGTH:
        raise ValueError(f"{to!r} is not a DMARC policy. One of: "
                         f"{', '.join(STRENGTH)}")
    if not record.strip().lower().startswith("v=dmarc1"):
        return ""
    if STRENGTH.index(policy_of(record)) >= STRENGTH.index(to):
        return ""

    # Rebuilt tag by tag rather than by a substitution on the whole string,
    # because `p=` also appears inside a DKIM-style key and as the start of
    # `pct=`. A regex loose enough to find the policy is loose enough to find
    # those.
    out, replaced = [], False
    for tag in record.split(";"):
        if _POLICY.match(tag):
            # The original spacing around the value is not preserved; the tag
            # separator is, because that is what a reader sees.
            out.append(re.sub(r"(?i)(\s*p\s*=\s*)(none|quarantine|reject)",
                              lambda m: f"{m.group(1)}{to}", tag))
            replaced = True
        else:
            out.append(tag)
    if not replaced:
        # A record with no `p` at all reads as p=none to the check above, so it
        # is raised by adding the tag rather than by leaving it alone.
        out.insert(1, f" p={to}")
    return ";".join(out)
