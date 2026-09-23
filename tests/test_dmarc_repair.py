"""The one fault the catalogue could see and the plan could never touch.

`dmarc_policy` fails when a domain publishes `p=none`. It has failed on a real
client since the catalogue was written and no repair existed, because the plan
is built from `Resend.cloudflare_records`, Resend publishes DKIM, SPF and MX,
and no mail provider has an opinion about DMARC. So no DMARC record entered a
plan for any client connected to anything (#56).

The second half is that a client with no Resend session got no plan at all,
including for the record Resend has nothing to do with.
"""

from typing import cast

import pytest

from munim.container import Container
from munim.runlog import RunLog

from munim.agent.dmarc import STRENGTH, policy_of, strengthened


# ---- reading the policy -------------------------------------------------

@pytest.mark.parametrize("record,expected", [
    ("v=DMARC1; p=none; rua=mailto:d@acme.example", "none"),
    ("v=DMARC1;p=quarantine", "quarantine"),
    ("v=DMARC1; P=REJECT", "reject"),
    ("v=DMARC1; rua=mailto:d@acme.example", "none"),
])
def test_the_policy_is_read_the_way_the_check_reads_it(record, expected):
    """`checks/dns.py:dmarc_policy` defaults a missing `p` to none. Two
    different answers to the same question is a reason to distrust both."""
    assert policy_of(record) == expected


# ---- raising it ---------------------------------------------------------

def test_every_other_tag_survives():
    """The tag that matters most is `rua`: it is where the reports go, and it
    is how an operator finds out whether quarantining was safe. A record
    rewritten from a template loses it silently."""
    raised = strengthened(
        "v=DMARC1; p=none; rua=mailto:d@acme.example; pct=100; adkim=s")
    assert raised == ("v=DMARC1; p=quarantine; rua=mailto:d@acme.example; "
                      "pct=100; adkim=s")


def test_a_record_with_no_spaces_keeps_having_none():
    assert strengthened("v=DMARC1;p=none") == "v=DMARC1;p=quarantine"


def test_a_missing_policy_tag_is_added_rather_than_ignored():
    """It reads as p=none to the check, so leaving it alone would mean the
    repair agreed the domain was fine while the check said it was not."""
    raised = strengthened("v=DMARC1; rua=mailto:d@acme.example")
    assert policy_of(raised) == "quarantine"
    assert "rua=mailto:d@acme.example" in raised


def test_pct_is_not_mistaken_for_the_policy():
    """`p=` is a prefix of `pct=`. A substitution loose enough to find the
    policy is loose enough to find that, and rewriting pct changes how much
    mail the policy applies to."""
    raised = strengthened("v=DMARC1; pct=100; p=none")
    assert "pct=100" in raised
    assert policy_of(raised) == "quarantine"


# ---- and leaving it alone -----------------------------------------------

def test_a_domain_already_enforcing_is_not_touched():
    assert strengthened("v=DMARC1; p=quarantine") == ""


def test_a_stronger_policy_is_never_walked_backwards():
    """reject is stronger than quarantine. "Raise" has to mean raise."""
    assert strengthened("v=DMARC1; p=reject") == ""
    assert STRENGTH.index("reject") > STRENGTH.index("quarantine")


def test_something_that_is_not_a_dmarc_record_is_refused():
    """`_dmarc` is a TXT name and other things can be published there."""
    assert strengthened("v=spf1 include:_spf.example ~all") == ""
    assert strengthened("google-site-verification=abc123") == ""


def test_an_empty_result_means_nothing_to_do_rather_than_no_change():
    """Returning the record unchanged would let a caller publish a write that
    changes nothing, which reads in the run log as a repair that happened."""
    assert strengthened("v=DMARC1; p=reject") == ""


def test_an_unknown_target_policy_is_refused():
    with pytest.raises(ValueError):
        strengthened("v=DMARC1; p=none", to="whatever")


# ---- and the plan it now reaches ----------------------------------------
#
# Faked at the adapters, not at `plan` itself. `plan` is the function under
# test and the bug was inside it: a Resend refusal ended the whole plan before
# the DMARC record was read. A fake that replaced `plan` would have agreed with
# the bug.

class FakeRecord:
    def __init__(self, content):
        self.content = content


class FakeCloudflare:
    def __init__(self, dmarc=""):
        self._dmarc = dmarc
        self.asked = []

    async def zone_id(self, domain):
        return "zone1"

    async def records(self, zone, *, type=None, name=None):
        self.asked.append((type, name))
        if name and name.startswith("_dmarc.") and self._dmarc:
            return [FakeRecord(self._dmarc)]
        return []


class RefusingResend:
    def __init__(self, *args, **kwargs):
        pass

    async def ensure_domain(self, domain):
        from munim.container import UnknownCredential
        raise UnknownCredential("no resend credential for client 'acme'")


class FakeLog:
    def __init__(self):
        self.entries = []

    def append(self, **kw):
        self.entries.append(kw)


class FakeContainer:
    client = "c_0123456789abcdef"     # the id credentials are filed under
    label = "Acme Ltd"                # what a person reads


async def _plan_with(monkeypatch, tmp_path, dmarc):
    from munim.agent import mailplan

    cloudflare = FakeCloudflare(dmarc)
    monkeypatch.setattr(mailplan, "Cloudflare", lambda *a, **k: cloudflare)
    monkeypatch.setattr(mailplan, "Resend", RefusingResend)
    monkeypatch.setattr(mailplan, "PLANS_DIR", tmp_path / "plans")
    # Cast rather than left to infer: these are deliberate doubles, and an
    # unannotated substitution reads as an oversight to a type checker and
    # to the next person.
    made = await mailplan.plan(cast(Container, FakeContainer()),
                               "acme.example", cast(RunLog, FakeLog()))
    return made, cloudflare


async def test_a_client_with_no_resend_still_gets_their_dmarc_raised(
        monkeypatch, tmp_path):
    """The whole point. This client has Cloudflare and no Resend, which is the
    shape of a real one whose only fixable fault is the DMARC policy."""
    made, _ = await _plan_with(
        monkeypatch, tmp_path,
        "v=DMARC1; p=none; rua=mailto:d@acme.example")

    assert [c.purpose for c in made.changes] == ["DMARC"]
    assert made.changes[0].content == (
        "v=DMARC1; p=quarantine; rua=mailto:d@acme.example")
    assert not made.blocked, "a plan with something in it must be appliable"


async def test_the_missing_resend_is_reported_rather_than_swallowed(
        monkeypatch, tmp_path):
    """Half a plan silently presented as a whole one is worse than a refusal."""
    made, _ = await _plan_with(
        monkeypatch, tmp_path, "v=DMARC1; p=none")

    assert made.skipped, "nothing said about the half that could not be planned"
    said = " ".join(made.skipped)
    assert "resend" in said.lower() and "munim connect" in said
    # The command it hands back has to be typeable. This printed the client id
    # the first time it ran against a real account, which is Munim's own
    # bookkeeping appearing in an instruction.
    assert 'munim connect "Acme Ltd"' in said
    assert "c_0123456789abcdef" not in said


async def test_raising_a_policy_somebody_published_waits_for_a_person(
        monkeypatch, tmp_path):
    """Mail that was failing authentication silently starts being quarantined.
    That is a judgement call and the gate already exists for it."""
    made, _ = await _plan_with(monkeypatch, tmp_path, "v=DMARC1; p=none")
    assert made.needs_approval == made.changes


async def test_nothing_planned_at_all_still_says_why(monkeypatch, tmp_path):
    """No Resend and no DMARC fault. An empty plan with no reason reads as
    "everything is fine", and `apply` would accept it."""
    made, _ = await _plan_with(monkeypatch, tmp_path, "v=DMARC1; p=reject")

    assert made.changes == []
    assert made.blocked, "an empty plan must carry the reason it is empty"


async def test_a_domain_already_enforcing_adds_no_change(monkeypatch, tmp_path):
    made, cloudflare = await _plan_with(
        monkeypatch, tmp_path, "v=DMARC1; p=quarantine; rua=mailto:d@acme.example")
    assert [c for c in made.changes if c.purpose == "DMARC"] == []
    assert ("TXT", "_dmarc.acme.example") in cloudflare.asked, \
        "the record was never read, so the absence proves nothing"
