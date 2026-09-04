"""Every check reports under its own name, and the catalogue is what we claim.

`dkim_chunking` carried four stacked platform guards, the first of which
returned `_not_their_domain("mx_present", ...)`. On any platform domain it
reported itself as a second mx_present: the room drew two mx chips and no
chunking chip, the report listed the same check twice, and the thirteen-check
claim was twelve. A unit test of dkim_chunking would not have caught it, because
the value it returns is perfectly valid. Only the name is wrong.
"""

import asyncio

import pytest

from munim.checks import dns as checks

PLATFORM = "example-app.vercel.app"
CATALOGUE = [
    "spf_single", "spf_lookups", "dkim_present", "dkim_chunking",
    "dmarc_present", "dmarc_policy", "mx_present", "ns_delegated",
    "apex_resolves", "caa_allows", "www_redirect", "https_enforced",
    "cert_valid",
]


@pytest.mark.parametrize("name", CATALOGUE)
def test_a_check_reports_under_its_own_name(name):
    import inspect

    fn = getattr(checks, name)
    # Platform domains short-circuit before any lookup, so this touches no wire.
    needs_selector = "selector" in inspect.signature(fn).parameters
    result = fn(PLATFORM, "resend") if needs_selector else fn(PLATFORM)
    assert result.check == name, f"{name} reported as {result.check!r}"


def test_the_catalogue_is_thirteen_checks_with_no_duplicates():
    """The count is quoted in the README, the video script and to judges."""
    results = checks.run_all(PLATFORM) + checks.run_reachability(PLATFORM)
    names = [r.check for r in results]
    assert len(names) == len(set(names)), f"duplicated: {sorted(names)}"
    assert set(names) == set(CATALOGUE)
    assert len(CATALOGUE) == 13


def test_a_skip_explains_itself_in_the_right_terms():
    """"mail settings belong to the platform" is wrong about whether www
    reaches the site."""
    by_name = {r.check: r for r in
               checks.run_all(PLATFORM) + checks.run_reachability(PLATFORM)}
    assert "mail settings" in by_name["spf_single"].operator_text
    assert "mail settings" not in by_name["www_redirect"].operator_text
    assert "mail settings" not in by_name["apex_resolves"].operator_text
    assert "mail settings" not in by_name["cert_valid"].operator_text


def test_the_skip_sentence_agrees_with_its_subject():
    """"DNS belong" is the same fault as "2 things needs your attention".

    Only the checks that actually short-circuit on a platform domain are
    asserted here: apex_resolves, caa_allows, https_enforced and cert_valid
    carry no platform guard, because those questions are still worth answering
    about a vercel.app address.
    """
    results = checks.run_all(PLATFORM) + checks.run_reachability(PLATFORM)
    skipped = [r for r in results if r.status == "skip"]
    assert skipped, "nothing skipped, so this asserts nothing"
    for r in skipped:
        says = r.operator_text
        assert (" belong to the platform" in says
                or " belongs to the platform" in says), f"{r.check}: {says}"

    by_name = {r.check: r for r in skipped}
    assert "DNS belongs" in by_name["ns_delegated"].operator_text
    assert "the web address belongs" in by_name["www_redirect"].operator_text
    assert "mail settings belong to" in by_name["spf_single"].operator_text
