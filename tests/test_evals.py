"""The rubric has to score the action, not the vocabulary.

Written because the obvious version of this file scores the vocabulary and
looks fine doing it. An independent review supplied the answer that defeats it,
and that answer is now a test: it names the fault, avoids every forbidden word,
invents no record, and tells the operator to do the one thing that would cost
their client their mail.
"""

import pytest

from munim import evals


def _fixture(name):
    return next(f for f in evals.FIXTURES if f.name == name)


def _score(name, answer):
    fixture = _fixture(name)
    missing = [need for need in fixture.must if not evals._hit(answer, need)]
    forbidden = [bad for bad in fixture.must_not if evals._hit(answer, bad)]
    return evals.Scored(fixture, answer, missing, forbidden)


GOOD_SPF = (
    "Your domain has two sender policies and receivers ignore both, so your "
    "mail authenticates as neither. Combine them into one record keeping every "
    "sender you use, and check the result stays under the ten-lookup limit "
    "before publishing it."
)

# The one that beats a vocabulary rubric. It names the fault, never says "add",
# names no specific record, invents no value, and is wrong twice: DNS records
# do not lapse, and it skips the lookup limit entirely.
PLAUSIBLE_AND_WRONG = (
    "Your domain publishes two sender policy records, so receivers treat "
    "neither as authoritative and mail from this domain authenticates as "
    "nothing. Keep the record that lists your current provider and let the "
    "other one lapse. This is safe to apply straight away."
)


def test_a_correct_spf_answer_passes():
    assert _score("two_spf", GOOD_SPF).status == "pass"


def test_the_answer_that_beats_a_vocabulary_rubric_fails():
    """The whole reason this file exists."""
    scored = _score("two_spf", PLAUSIBLE_AND_WRONG)
    assert scored.status == "fail", \
        "an answer telling the operator to let a DNS record lapse scored a pass"
    assert scored.forbidden, "it failed for the wrong reason"


def test_deleting_a_record_and_keeping_only_one_are_the_same_wrong_action():
    """"delete the second" and "keep only the first" are one instruction. A
    rubric naming one phrasing and not the other measures wording."""
    for phrasing in ["Delete the second record and you are done.",
                     "Keep only the record from your current provider.",
                     "Remove the older one; it is no longer needed.",
                     "Just drop the one you are not using."]:
        assert _score("two_spf", phrasing).status == "fail", phrasing


def test_naming_the_fault_alone_is_not_enough():
    """Description without an action is the failure mode a rubric that only
    checks for the fault's noun rewards."""
    only_described = ("This domain has two sender policies, which is why its "
                      "mail is not authenticating.")
    assert _score("two_spf", only_described).status == "fail"


def test_a_dmarc_answer_that_jumps_to_reject_fails():
    """p=none does nothing, but going straight to reject bounces legitimate
    mail. The right answer moves in steps."""
    assert _score("dmarc_monitor_only",
                  "Set it to reject now and you are protected.").status == "fail"
    assert _score("dmarc_monitor_only",
                  "Move to quarantine first and read the reports for a "
                  "fortnight before tightening further.").status == "pass"


def test_inventing_a_dkim_key_fails():
    """There is no correct value to write: it comes from the provider."""
    invented = ("Add a TXT record at resend._domainkey with "
                "v=DKIM1; k=rsa; p=MIIBIjANBgkq...")
    assert _score("dkim_missing", invented).status == "fail"
    fetched = ("Copy the DKIM record Resend shows in the dashboard for this "
               "domain and publish it as-is.")
    assert _score("dkim_missing", fetched).status == "pass"


def test_answering_one_of_two_faults_fails():
    """Answering the loudest and dropping the other is worse than answering
    neither, because the operator stops looking."""
    half = ("Combine the two sender policies into one record, keeping every "
            "sender.")
    assert _score("two_spf_and_no_dkim", half).missing, \
        "the unmentioned second fault was not noticed"


def test_a_fixture_that_cannot_be_scored_says_so_rather_than_guessing():
    """Where a predicate cannot separate understanding from wording, the
    honest output is "not scored", not a green tick."""
    both = ("Combine the two sender policies into one record, and publish the "
            "DKIM record Resend gives you so your mail is signed.")
    scored = _score("two_spf_and_no_dkim", both)
    assert scored.missing == [] and scored.forbidden == []
    assert scored.status == "unscored"
    assert _fixture("two_spf_and_no_dkim").unscored


def test_every_fixture_explains_what_it_is_for():
    """A rubric a reader cannot audit is worse than none, because it is
    believed."""
    for fixture in evals.FIXTURES:
        assert fixture.why.strip(), fixture.name
        assert fixture.failures, fixture.name


def test_a_fixture_that_answers_differently_between_runs_is_not_a_pass():
    """The verdict a single sample cannot produce. Two live runs of this file,
    the same model minutes apart, disagreed on every fixture: it described the
    fault both times and prescribed the repair only once."""
    good = _score("two_spf", GOOD_SPF)
    bad = _score("two_spf", PLAUSIBLE_AND_WRONG)

    assert evals.Run(_fixture("two_spf"), [good, good, good]).status == "pass"
    assert evals.Run(_fixture("two_spf"), [bad, bad, bad]).status == "fail"
    run = evals.Run(_fixture("two_spf"), [good, bad, good])
    assert run.status == "unreliable", \
        "advice that changes between identical runs was reported as settled"
    assert run.passed == 2


def test_the_table_is_advisory_and_does_not_gate(monkeypatch, capsys):
    """It prints the model's own sentence, which concedes the reader is the
    judge. Exiting non-zero on a keyword verdict would claim more than that."""
    monkeypatch.setattr(evals, "FIXTURES", [_fixture("two_spf")])
    monkeypatch.setattr("munim.agent.model.agents_off", lambda *a, **k: None)

    async def wrong(fixture, runs_dir=None):
        return _score("two_spf", PLAUSIBLE_AND_WRONG)

    monkeypatch.setattr(evals, "_run_one", wrong)

    assert evals.run(samples=1) == 0, "a keyword rubric was used to gate"
    out = capsys.readouterr().out
    assert "fail" in out
    assert "lapse" in out, "the model's own words were not shown"
    assert "Advisory" in out


def test_agents_off_says_so_rather_than_scoring_nothing(monkeypatch, capsys):
    assert evals.run() == 0
    assert "munim config ai on" in capsys.readouterr().err


def test_an_unjudgeable_aspect_does_not_excuse_a_missed_action():
    """Found by the first live run, which printed `unscored` beside "did not
    say any of: combine, merge, ...". The note says one aspect cannot be
    judged; it must not make the whole fixture unfailable."""
    only_the_spf_fault = ("There are two SPF records for your domain, but "
                          "email providers only allow one.")
    scored = _score("two_spf_and_no_dkim", only_the_spf_fault)
    assert scored.missing, "the missed actions were not detected at all"
    assert scored.status == "fail", \
        "a note about ordering hid an answer that missed a required action"
