"""The report is the only artefact a non-technical person sees, so its prose is
part of the product, not decoration."""

import pathlib

import pytest

from munim.report import render
from munim.runlog import RunLog, new_run_id


def _log(tmp_path, findings=0, passes=2):
    log = RunLog(new_run_id(), tmp_path)
    for i in range(passes):
        log.append(client="Ivy", stage="verify", kind="observation",
                   human_text=f"Fine thing {i}", detail={"check": f"ok{i}"})
    for i in range(findings):
        log.append(client="Ivy", stage="verify", kind="finding",
                   human_text=f"Broken thing {i}",
                   detail={"check": f"bad{i}", "operator_text": f"tech {i}"})
    return log


def test_the_headline_agrees_with_itself(tmp_path):
    assert "One thing needs your attention" in render(
        _log(tmp_path, findings=1), domain="d", business="Ivy")
    assert "2 things need your attention" in render(
        _log(tmp_path, findings=2), domain="d", business="Ivy")


def test_a_clean_run_says_so_and_shows_the_size_of_the_net(tmp_path):
    """'Nothing wrong' only means something if you can see what was checked."""
    page = render(_log(tmp_path, findings=0, passes=5), domain="d", business="Ivy")
    assert "Everything checks out" in page
    assert "5 things" in page


def test_the_owner_wording_leads_and_the_jargon_follows(tmp_path):
    page = render(_log(tmp_path, findings=1), domain="d", business="Ivy")
    assert page.index("Broken thing 0") < page.index("Technically:")


def test_business_and_domain_are_escaped(tmp_path):
    page = render(_log(tmp_path), domain="<script>x</script>", business="A & B")
    assert "<script>" not in page
    assert "A &amp; B" in page


def _log_from(tmp_path, events):
    """A run log built from (kind, check, text) triples."""
    log = RunLog(new_run_id(), tmp_path)
    for kind, check, text in events:
        log.append(client="Ivy & Fern Studio", stage="mail", kind=kind,
                   human_text=text, detail={"check": check} if check else {})
    return log


def test_one_check_is_a_thing_not_things(tmp_path):
    """"We checked 1 things" - the headline pluralised and the subtitle did not."""
    log = _log_from(tmp_path, [("observation", "mx_present", "Mail can reach you.")])
    page = render(log, domain="ivyandfern.co.uk", business="Ivy & Fern Studio")
    assert "1 thing about" in page
    assert "1 things" not in page


def test_two_checks_are_things(tmp_path):
    log = _log_from(tmp_path, [("observation", "mx_present", "Mail can reach you."),
                               ("observation", "dmarc_present", "Mail is signed.")])
    page = render(log, domain="ivyandfern.co.uk", business="Ivy & Fern Studio")
    assert "2 things about" in page


def test_a_repaired_finding_appears_in_what_we_looked_at(tmp_path):
    """It showed in a card and nowhere else, so a run whose only event was a
    repair printed "Everything we looked at" above an empty list - against this
    module's own rule that the size of the net has to be visible."""
    log = _log_from(tmp_path, [
        ("finding", "spf_single", "This domain has more than one sender policy."),
        ("resolved", "spf_single", "One sender policy now, covering every sender."),
    ])
    page = render(log, domain="ivyandfern.co.uk", business="Ivy & Fern Studio")
    assert "Everything we looked at" in page
    body = page.split("Everything we looked at", 1)[1]
    assert "<li>" in body, "the repaired check is missing from the list"
    # Ticked and described by what is true now. Showing the finding text under a
    # green tick told the owner their domain still had the fixed problem.
    assert "One sender policy now" in body
    assert "more than one sender policy" not in body


def test_no_heading_over_an_empty_list(tmp_path):
    """A run that checked nothing must not promise everything it looked at."""
    log = _log_from(tmp_path, [("stage_start", None, "Checking email authentication")])
    page = render(log, domain="ivyandfern.co.uk", business="Ivy & Fern Studio")
    assert "Everything we looked at" not in page
