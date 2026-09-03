"""The checks are deterministic, so they are tested against fixed DNS answers
rather than the live internet. `query` is the only thing that touches the
network, so it is the only thing stubbed - the logic under test is real."""

import pytest

from munim.checks import dns as checks


def _answers(mapping):
    def fake(name, rdtype, nameserver="1.1.1.1"):
        return mapping.get((name, rdtype), [])
    return fake


def test_two_spf_records_fail_because_receivers_ignore_both(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({
        ("acme.example", "TXT"): [
            "v=spf1 include:_spf.google.com ~all",
            "v=spf1 include:amazonses.com ~all",
        ],
    }))
    result = checks.spf_single("acme.example")
    assert result.status == "fail"
    assert "more than one" in result.human_text.lower()
    # The evidence has to be quotable, because the claim is checkable.
    assert result.evidence.count("v=spf1") == 2


def test_one_spf_record_passes(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({
        ("acme.example", "TXT"): ["v=spf1 include:amazonses.com ~all"],
    }))
    assert checks.spf_single("acme.example").status == "pass"


def test_no_spf_record_is_its_own_failure(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({}))
    result = checks.spf_single("acme.example")
    assert result.status == "fail"
    assert "nothing tells" in result.human_text.lower()


def test_spf_over_ten_lookups_is_a_permerror(monkeypatch):
    record = "v=spf1 " + " ".join(f"include:s{i}.example" for i in range(11)) + " ~all"
    monkeypatch.setattr(checks, "query", _answers({("acme.example", "TXT"): [record]}))
    result = checks.spf_lookups("acme.example")
    assert result.status == "fail"
    assert result.detail["lookups"] == 11


def test_spf_at_exactly_ten_lookups_still_passes(monkeypatch):
    record = "v=spf1 " + " ".join(f"include:s{i}.example" for i in range(10)) + " ~all"
    monkeypatch.setattr(checks, "query", _answers({("acme.example", "TXT"): [record]}))
    assert checks.spf_lookups("acme.example").status == "pass"


def test_dmarc_p_none_is_monitoring_not_protection(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({
        ("_dmarc.acme.example", "TXT"): ["v=DMARC1; p=none; rua=mailto:x@acme.example"],
    }))
    result = checks.dmarc_policy("acme.example")
    assert result.status == "fail"
    assert result.detail["policy"] == "none"


def test_dmarc_reject_passes(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({
        ("_dmarc.acme.example", "TXT"): ["v=DMARC1; p=reject"],
    }))
    assert checks.dmarc_policy("acme.example").status == "pass"


def test_nameservers_pointing_elsewhere_fail(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({
        ("acme.example", "NS"): ["ns1.oldhost.com.", "ns2.oldhost.com."],
    }))
    result = checks.ns_delegated("acme.example", expect="cloudflare")
    assert result.status == "fail"
    assert "not take effect" in result.human_text


def test_caa_blocking_the_issuer_fails_silently_in_production(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({
        ("acme.example", "CAA"): ['0 issue "digicert.com"'],
    }))
    result = checks.caa_allows("acme.example", issuer="letsencrypt.org")
    assert result.status == "fail"
    assert "renew" in result.human_text


def test_no_caa_record_permits_any_issuer(monkeypatch):
    monkeypatch.setattr(checks, "query", _answers({}))
    assert checks.caa_allows("acme.example").status == "pass"


def test_every_failing_check_speaks_to_the_owner_not_the_operator(monkeypatch):
    """A finding a business owner cannot act on is not a finding (D7)."""
    monkeypatch.setattr(checks, "query", _answers({}))
    for result in checks.run_all("acme.example"):
        if result.status == "fail":
            assert result.human_text, f"{result.check} has no owner-facing text"
            assert result.human_text != result.operator_text
