"""Repair, reachable through the product this time.

`set_up_mail` takes an `approve` callback and calls it mid-flight. That works
from Python and cannot cross an MCP tool boundary: a tool call returns once, so
there is nowhere for a question to go. The repair therefore existed, was
tested, and had no caller outside its own module, which an external reviewer
found before we did.

Approval is now the gap between two calls. These pin the gate.
"""

import pytest

from munim.agent.mailplan import Change, MailPlan, NotApproved, apply


def _plan(*changes, blocked=""):
    return MailPlan(plan_id="p1", client="acme", domain="acme.example",
                    changes=list(changes), blocked=blocked)


def _create():
    return Change("DKIM", "CNAME", "x._domainkey.acme.example", "v", "create")


def _merge():
    return Change("SPF", "TXT", "acme.example", "v=spf1 a -all", "merge",
                  current=["v=spf1 include:old -all"])


def _update():
    return Change("SPF", "TXT", "acme.example", "new", "update", current=["old"])


def test_creating_a_record_nobody_put_there_needs_no_approval():
    assert _plan(_create()).needs_approval == []
    assert _create().needs_a_person is False


@pytest.mark.parametrize("change", [_merge(), _update()])
def test_touching_a_record_somebody_put_there_does(change):
    assert change.needs_a_person is True
    assert _plan(change).needs_approval == [change]


async def test_apply_refuses_before_it_touches_anything():
    """A refusal that has already opened a session has already done something.
    Passing None as the container proves nothing was reached."""
    with pytest.raises(NotApproved, match="Re-run with approved=true"):
        await apply(None, _plan(_merge()), None)


async def test_a_blocked_plan_is_refused_even_when_approved():
    """Over the lookup limit means the merged policy would fail too. Approval
    is consent to a change, not a way to overrule arithmetic."""
    made = _plan(_merge(), blocked="would need 12 DNS lookups and the limit is 10")
    with pytest.raises(NotApproved, match="limit is 10"):
        await apply(None, made, None, approved=True)


async def test_the_refusal_names_what_it_would_have_changed():
    """"Needs approval" with nothing named is not something anyone can approve."""
    with pytest.raises(NotApproved) as caught:
        await apply(None, _plan(_merge(), _create()), None)
    assert "SPF acme.example" in str(caught.value)
    assert "DKIM" not in str(caught.value), "a create does not need approving"


def test_a_plan_survives_a_round_trip(tmp_path, monkeypatch):
    """The plan is read back by a second tool call, in a second process if the
    coding agent reconnected between them."""
    import munim.agent.mailplan as mod

    monkeypatch.setattr(mod, "PLANS_DIR", tmp_path / "plans")
    made = _plan(_merge(), _create())
    mod._save(made)

    back = mod.load("p1")
    assert back.domain == made.domain
    assert [c.action for c in back.changes] == ["merge", "create"]
    assert len(back.needs_approval) == 1


def test_a_missing_plan_says_how_to_make_one(tmp_path, monkeypatch):
    import munim.agent.mailplan as mod

    monkeypatch.setattr(mod, "PLANS_DIR", tmp_path / "plans")
    with pytest.raises(FileNotFoundError, match="plan_mail_setup"):
        mod.load("nope")
