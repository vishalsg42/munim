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


def test_an_unreachable_host_is_not_a_broken_certificate(monkeypatch):
    """Found by auditing a dozen clients at once: a transient timeout was
    reported as a broken certificate on a domain whose certificate had 84 days
    left. A check that cries wolf is worth less than no check (D20)."""
    import socket

    def refuse(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", refuse)
    result = checks.cert_valid("acme.example", timeout=1, attempts=2)
    assert result.status == "skip", "a timeout was reported as a failure"
    assert "undetermined" in result.operator_text


def test_a_certificate_that_does_not_verify_is_a_failure(monkeypatch):
    """The other half. Retrying a rejected certificate does not change it."""
    import ssl

    class Ctx:
        def wrap_socket(self, sock, server_hostname=None):
            raise ssl.SSLCertVerificationError("certificate has expired")

    monkeypatch.setattr(ssl, "create_default_context", lambda: Ctx())
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: _Sock())
    result = checks.cert_valid("acme.example", timeout=1)
    assert result.status == "fail"
    assert "does not verify" in result.operator_text


class _Sock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_a_bad_certificate_is_not_retried(monkeypatch):
    """Retrying it wastes the operator's time and changes nothing."""
    import ssl

    tries = []

    class Ctx:
        def wrap_socket(self, sock, server_hostname=None):
            tries.append(1)
            raise ssl.SSLCertVerificationError("certificate has expired")

    monkeypatch.setattr(ssl, "create_default_context", lambda: Ctx())
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: _Sock())
    checks.cert_valid("acme.example", timeout=1, attempts=3)
    assert len(tries) == 1, f"retried a rejected certificate {len(tries)} times"
