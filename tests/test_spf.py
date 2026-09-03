"""Combining sender policies.

Deterministic on purpose: the mechanics are rule-work, so they are tested
rather than prompted. Getting this wrong silently breaks a client's mail, which
is the failure the whole project is about.
"""

import pytest

from munim.agent.spf import merge_spf, within_lookup_limit


def test_two_policies_become_one_keeping_every_sender():
    m = merge_spf([
        "v=spf1 include:_spf.google.com ~all",
        "v=spf1 include:amazonses.com ~all",
    ])
    assert m.merged == "v=spf1 include:_spf.google.com include:amazonses.com ~all"
    assert len(m.senders) == 2


def test_the_strictest_qualifier_wins():
    """Combining a hard-fail policy with a soft-fail one must not quietly
    loosen the domain's protection."""
    m = merge_spf([
        "v=spf1 include:a.example ~all",
        "v=spf1 include:b.example -all",
    ])
    assert m.qualifier == "-all"
    assert m.merged.endswith("-all")


def test_order_of_first_appearance_is_preserved():
    """SPF evaluates left to right and the first match wins, so reordering can
    change which policy applies."""
    m = merge_spf([
        "v=spf1 include:first.example include:second.example ~all",
        "v=spf1 include:third.example ~all",
    ])
    assert m.senders == ["include:first.example", "include:second.example",
                         "include:third.example"]


def test_a_sender_present_in_both_is_not_duplicated():
    m = merge_spf([
        "v=spf1 include:shared.example include:a.example ~all",
        "v=spf1 include:shared.example include:b.example ~all",
    ])
    assert m.senders.count("include:shared.example") == 1


def test_ip_mechanisms_survive_the_merge():
    m = merge_spf([
        "v=spf1 ip4:198.51.100.0/24 ~all",
        "v=spf1 include:amazonses.com ~all",
    ])
    assert "ip4:198.51.100.0/24" in m.merged


def test_a_merge_that_busts_the_lookup_limit_is_detectable():
    """Over ten lookups is a permerror, so such a merge is not a fix and the
    agent must escalate rather than write it."""
    many = "v=spf1 " + " ".join(f"include:s{i}.example" for i in range(6)) + " ~all"
    other = "v=spf1 " + " ".join(f"include:t{i}.example" for i in range(6)) + " ~all"
    m = merge_spf([many, other])
    assert m.lookups == 12
    assert not within_lookup_limit(m.merged)


def test_merging_nothing_is_an_error_not_an_empty_policy():
    with pytest.raises(ValueError):
        merge_spf(["not an spf record"])
