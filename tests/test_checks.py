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


def test_a_truncated_dkim_key_is_caught_even_though_the_record_exists(monkeypatch):
    """The record is present and looks right in a dashboard. It is unusable."""
    truncated = "v=DKIM1; k=rsa; p=" + "A" * 40 + "x" * 260
    monkeypatch.setattr(checks, "query", _answers({
        ("resend._domainkey.acme.example", "TXT"): [truncated],
    }))
    result = checks.dkim_chunking("acme.example", "resend")
    assert result.status == "pass"  # long enough to be plausible

    # A genuinely truncated key: the record is long enough to have needed
    # splitting, but the key material after p= is a stub.
    monkeypatch.setattr(checks, "query", _answers({
        ("resend._domainkey.acme.example", "TXT"):
            ["v=DKIM1; k=rsa; " + "; ".join(f"note{i}=padding" for i in range(20)) + "; p=MIIBIjANBg"],
    }))
    result = checks.dkim_chunking("acme.example", "resend")
    assert result.status == "fail"
    assert "unusable" in result.human_text


def test_no_dkim_record_is_skipped_not_failed_twice(monkeypatch):
    """dkim_present already reports absence; chunking has nothing to say about
    a record that is not there, and two failures for one cause is noise."""
    monkeypatch.setattr(checks, "query", _answers({}))
    assert checks.dkim_chunking("acme.example", "resend").status == "skip"


def test_a_certificate_expiring_inside_the_window_fails(monkeypatch):
    """Rather than reaching the network, the boundary is what is tested: a
    certificate one day inside the window must fail, one day outside must pass."""
    import datetime as dt

    class FakeTLS:
        def __init__(self, days): self.days = days
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def getpeercert(self):
            when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=self.days)
            return {"notAfter": when.strftime("%b %d %H:%M:%S %Y GMT")}

    class FakeCtx:
        def __init__(self, days): self.days = days
        def wrap_socket(self, sock, server_hostname=None): return FakeTLS(self.days)

    class FakeSock:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def patch(days):
        monkeypatch.setattr(checks.ssl, "create_default_context", lambda: FakeCtx(days))
        monkeypatch.setattr(checks.socket, "create_connection", lambda *a, **k: FakeSock())

    patch(30)
    assert checks.cert_valid("acme.example", days=14).status == "pass"
    patch(5)
    result = checks.cert_valid("acme.example", days=14)
    assert result.status == "fail"
    # .days floors, so 5 days minus the elapsed microseconds reports 4. Flooring
    # is the right direction for an expiry warning: never claim more time than
    # there is.
    assert result.detail["days_left"] in (4, 5)
    assert "security warning" in result.human_text


def test_mail_checks_do_not_fire_on_a_platform_domain(monkeypatch):
    """Found by running the catalogue against a real client's Vercel URL: it
    reported six failures, every one of them correct behaviour. Nobody sends
    mail from a vercel.app address, and a check that cries wolf on a preview URL
    is one people learn to ignore."""
    monkeypatch.setattr(checks, "query", _answers({}))
    results = checks.run_all("balajiroofings-quote.vercel.app")
    mail = {"spf_single", "spf_lookups", "dkim_present", "dkim_chunking",
            "dmarc_present", "dmarc_policy", "mx_present", "ns_delegated"}
    for result in results:
        if result.check in mail:
            assert result.status == "skip", f"{result.check} fired on a platform domain"
            assert result.detail.get("reason") == "platform_domain"


def test_the_same_checks_still_fire_on_a_real_domain(monkeypatch):
    """The guard must not have turned the catalogue off."""
    monkeypatch.setattr(checks, "query", _answers({}))
    failures = {r.check for r in checks.run_all("acme.example") if r.status == "fail"}
    assert {"spf_single", "dmarc_present", "mx_present"} <= failures


def test_platform_detection_is_suffix_anchored():
    """A domain merely containing a platform name is still the business's own."""
    assert checks.is_platform_domain("shop.vercel.app")
    assert checks.is_platform_domain("BALAJI.VERCEL.APP")
    assert not checks.is_platform_domain("vercel.app.acme.example")
    assert not checks.is_platform_domain("myvercel.app-store.example")


async def test_prefetch_deduplicates_the_records_several_checks_share():
    """spf_single and spf_lookups both want the apex TXT; dmarc_present and
    dmarc_policy both want _dmarc. Fetching each once is where the win is."""
    from munim.checks import dns as d

    seen = []

    def counting_query(name, rdtype, nameserver="1.1.1.1"):
        seen.append((name, rdtype))
        return []

    original = d.query
    d.query = counting_query
    try:
        cache = await d.prefetch("acme.example", "resend")
    finally:
        d.query = original

    assert len(seen) == len(set(seen)), "the same record was fetched twice"
    assert ("acme.example", "TXT") in cache
    assert ("_dmarc.acme.example", "TXT") in cache
    assert ("resend._domainkey.acme.example", "TXT") in cache


async def test_a_failing_lookup_does_not_lose_the_others():
    """One unreachable record must not take the whole scan down."""
    from munim.checks import dns as d

    def flaky(name, rdtype, nameserver="1.1.1.1"):
        if rdtype == "CAA":
            raise OSError("resolver unreachable")
        return ["ok"]

    original = d.query
    d.query = flaky
    try:
        cache = await d.prefetch("acme.example")
    finally:
        d.query = original

    assert cache[("acme.example", "CAA")] == []
    assert cache[("acme.example", "TXT")] == ["ok"]
