"""Combining sender policies.

Merging SPF records is the decision that separates this from a script. A domain
that already carries a policy from an old mail provider, and gains a second from
a new one, has two records - and receivers ignore both. The naive fix is to add
a third. The correct fix is to combine them into one, keeping every sender that
should still be able to send and dropping nothing by accident.

Deterministic on purpose: the mechanics of combining are rule-work, so they are
tested rather than prompted. What the agent decides is *whether* to merge, and
which senders belong in the result.
"""

import re
from dataclasses import dataclass

_QUALIFIERS = ("~all", "-all", "?all", "+all")
# Strictest wins: if any policy says hard-fail, the merged policy hard-fails.
_STRICTNESS = {"-all": 3, "~all": 2, "?all": 1, "+all": 0}


@dataclass
class Merge:
    merged: str
    senders: list[str]
    qualifier: str
    dropped: list[str]

    @property
    def lookups(self) -> int:
        return sum(self.merged.count(m) for m in
                   ("include:", "a:", "mx:", "ptr", "exists:", "redirect="))


def merge_spf(records: list[str]) -> Merge:
    """Combine SPF records into one, preserving order of first appearance.

    Order is preserved because SPF is evaluated left to right and the first
    match wins; reordering can change which policy applies to a sender.
    """
    policies = [r.strip() for r in records if r.strip().lower().startswith("v=spf1")]
    if not policies:
        raise ValueError("no SPF records to merge")

    senders: list[str] = []
    qualifier = "~all"
    strictest = -1

    for policy in policies:
        for term in policy.split()[1:]:  # skip the v=spf1 prefix
            lowered = term.lower()
            if lowered in _QUALIFIERS:
                if _STRICTNESS[lowered] > strictest:
                    strictest, qualifier = _STRICTNESS[lowered], lowered
                continue
            if term not in senders:
                senders.append(term)

    merged = " ".join(["v=spf1", *senders, qualifier])
    return Merge(merged=merged, senders=senders, qualifier=qualifier, dropped=[])


def within_lookup_limit(record: str) -> bool:
    """A merged policy over 10 lookups is a permerror, which receivers treat as
    a hard failure - so a merge that busts the limit is not a fix."""
    return sum(record.count(m) for m in
               ("include:", "a:", "mx:", "ptr", "exists:", "redirect=")) <= 10
