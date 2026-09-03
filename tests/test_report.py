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
