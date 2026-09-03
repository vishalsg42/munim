"""The checks that need no credentials.

Every one of these is a real failure an operator hits, and none of them are run
today, because running twenty checks by hand on every launch for every client is
not realistic. That is the whole product in one sentence.

Deterministic on purpose (D7): these are pure functions over DNS answers. The
model never decides whether a check passed - it decides what to do about it and
how to say it to the person who owns the domain.

The resolver strategy matters. A negative answer taken before a write is cached
for the zone's SOA minimum, so a single resolver keeps reporting NXDOMAIN long
after the record exists. Asking the authoritative nameserver and a public
resolver separately turns that into the diagnosis rather than a wrong answer.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

import dns.exception
import dns.rdatatype
import dns.resolver

Status = Literal["pass", "fail", "skip"]

# Mechanisms that cost a DNS lookup against SPF's hard limit of 10 (RFC 7208 §4.6.4).
_SPF_LOOKUP_MECHANISMS = ("include:", "a:", "mx:", "ptr", "exists:", "redirect=")


@dataclass
class CheckResult:
    check: str
    status: Status
    operator_text: str          # for the person running it
    human_text: str             # for the business that owns the domain
    evidence: str = ""          # verbatim, so a claim can be checked
    resolver: str = ""
    detail: dict = field(default_factory=dict)


def _resolver(nameserver: str | None = None) -> dns.resolver.Resolver:
    r = dns.resolver.Resolver(configure=nameserver is None)
    if nameserver:
        r.nameservers = [nameserver]
    r.lifetime = 8.0
    r.timeout = 4.0
    return r


def query(name: str, rdtype: str, nameserver: str = "1.1.1.1") -> list[str]:
    """Return record values as strings. An absent record is an empty list, not
    an exception - absence is an answer here, not a failure."""
    try:
        answers = _resolver(nameserver).resolve(name, rdtype)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return []
    except dns.exception.Timeout:
        return []
    out = []
    for rdata in answers:
        if rdtype == "TXT":
            # A TXT record is a sequence of strings; joining them is what the
            # spec says a consumer does, and is why chunking is checkable.
            out.append("".join(s.decode() for s in rdata.strings))
        else:
            out.append(rdata.to_text())
    return out


def spf_single(domain: str, ns: str = "1.1.1.1") -> CheckResult:
    """More than one SPF record means every one of them is ignored."""
    txts = query(domain, "TXT", ns)
    spf = [t for t in txts if t.lower().startswith("v=spf1")]
    if len(spf) == 1:
        return CheckResult("spf_single", "pass",
                           "One SPF record.",
                           "Your outgoing mail is correctly claimed by one sender policy.",
                           evidence=spf[0], resolver=ns)
    if not spf:
        return CheckResult("spf_single", "fail",
                           "No SPF record.",
                           "Nothing tells other mail servers who is allowed to send as you, "
                           "so your messages are more likely to be treated as spam.",
                           resolver=ns)
    return CheckResult(
        "spf_single", "fail",
        f"{len(spf)} SPF records. RFC 7208 says a domain with more than one is in error; "
        "receivers ignore all of them.",
        "This domain has more than one sender policy, usually because a new mail provider "
        "was added alongside an old one. They do not combine - both are ignored, and your "
        "mail authenticates as neither.",
        evidence="\n".join(f'{domain}. IN TXT "{s}"' for s in spf),
        resolver=ns, detail={"records": spf},
    )


def spf_lookups(domain: str, ns: str = "1.1.1.1") -> CheckResult:
    """Over 10 DNS lookups is a permerror, which receivers treat as a hard fail."""
    txts = [t for t in query(domain, "TXT", ns) if t.lower().startswith("v=spf1")]
    if not txts:
        return CheckResult("spf_lookups", "skip", "No SPF record to count.", "", resolver=ns)
    record = txts[0]
    count = sum(record.lower().count(m) for m in _SPF_LOOKUP_MECHANISMS)
    if count <= 10:
        return CheckResult("spf_lookups", "pass",
                           f"SPF uses {count} of its 10 permitted DNS lookups.",
                           "Your sender policy is within the limits mail servers enforce.",
                           evidence=record, resolver=ns, detail={"lookups": count})
    return CheckResult("spf_lookups", "fail",
                       f"SPF requires {count} DNS lookups; the limit is 10. Receivers return "
                       "permerror and treat the result as a failure.",
                       "Your sender policy grew past the limit mail servers allow, so they "
                       "give up checking it and treat your mail as unverified.",
                       evidence=record, resolver=ns, detail={"lookups": count})


def dmarc_present(domain: str, ns: str = "1.1.1.1") -> CheckResult:
    txts = query(f"_dmarc.{domain}", "TXT", ns)
    dmarc = [t for t in txts if t.lower().startswith("v=dmarc1")]
    if dmarc:
        return CheckResult("dmarc_present", "pass", "DMARC published.",
                           "You have told other mail servers what to do with messages that "
                           "fail to prove they came from you.",
                           evidence=dmarc[0], resolver=ns)
    return CheckResult("dmarc_present", "fail", "No DMARC record.",
                       "Gmail and Outlook now deprioritise bulk mail from domains without "
                       "this, so your messages are more likely to land in spam.",
                       resolver=ns)


def dmarc_policy(domain: str, ns: str = "1.1.1.1") -> CheckResult:
    txts = [t for t in query(f"_dmarc.{domain}", "TXT", ns) if t.lower().startswith("v=dmarc1")]
    if not txts:
        return CheckResult("dmarc_policy", "skip", "No DMARC record to inspect.", "", resolver=ns)
    record = txts[0]
    policy = (re.search(r"\bp\s*=\s*(none|quarantine|reject)", record, re.I) or [None, "none"])[1].lower()
    if policy in ("quarantine", "reject"):
        return CheckResult("dmarc_policy", "pass", f"DMARC policy is p={policy}.",
                           "Messages pretending to be from you are rejected or quarantined.",
                           evidence=record, resolver=ns, detail={"policy": policy})
    return CheckResult("dmarc_policy", "fail", "DMARC policy is p=none: monitoring only.",
                       "Anyone can still send mail pretending to be you - the policy is set "
                       "to watch, not to act.",
                       evidence=record, resolver=ns, detail={"policy": policy})


def dkim_present(domain: str, selector: str, ns: str = "1.1.1.1") -> CheckResult:
    name = f"{selector}._domainkey.{domain}"
    txts = query(name, "TXT", ns)
    if any("p=" in t for t in txts):
        return CheckResult("dkim_present", "pass", f"DKIM key published at {selector}.",
                           "Your mail carries a signature receivers can verify.",
                           evidence=txts[0][:120] + ("…" if len(txts[0]) > 120 else ""),
                           resolver=ns)
    return CheckResult("dkim_present", "fail", f"No DKIM key at {name}.",
                       "Your mail is not signed, so receivers cannot prove it really came "
                       "from you.", resolver=ns)


def ns_delegated(domain: str, expect: str = "", ns: str = "1.1.1.1") -> CheckResult:
    records = [r.rstrip(".").lower() for r in query(domain, "NS", ns)]
    if not records:
        return CheckResult("ns_delegated", "fail", "No nameservers found.",
                           "This domain is not pointing anywhere yet.", resolver=ns)
    if expect and not any(expect.lower() in r for r in records):
        return CheckResult("ns_delegated", "fail",
                           f"Nameservers are {', '.join(records)}, not {expect}. Records written "
                           "at the intended provider will not be the ones the world sees.",
                           "This domain is still controlled somewhere else, so changes made "
                           "here would not take effect.",
                           evidence="\n".join(records), resolver=ns)
    return CheckResult("ns_delegated", "pass", f"Delegated to {', '.join(records)}.",
                       "This domain is under your control.",
                       evidence="\n".join(records), resolver=ns)


def apex_resolves(domain: str, ns: str = "1.1.1.1") -> CheckResult:
    addresses = query(domain, "A", ns) + query(domain, "AAAA", ns)
    if addresses:
        return CheckResult("apex_resolves", "pass", "Apex resolves.",
                           "Typing your address into a browser reaches your site.",
                           evidence="\n".join(addresses), resolver=ns)
    return CheckResult("apex_resolves", "fail", "Apex does not resolve.",
                       "Your web address does not lead anywhere.", resolver=ns)


def mx_present(domain: str, ns: str = "1.1.1.1") -> CheckResult:
    records = query(domain, "MX", ns)
    if records:
        return CheckResult("mx_present", "pass", "MX records present.",
                           "Mail sent to your address can be delivered.",
                           evidence="\n".join(records), resolver=ns)
    return CheckResult("mx_present", "fail", "No MX records.",
                       "Nobody can send email to this domain - there is nowhere to deliver it.",
                       resolver=ns)


def caa_allows(domain: str, issuer: str = "letsencrypt.org", ns: str = "1.1.1.1") -> CheckResult:
    records = query(domain, "CAA", ns)
    if not records:
        return CheckResult("caa_allows", "pass", "No CAA record; any authority may issue.",
                           "Nothing is blocking your security certificate from being renewed.",
                           resolver=ns)
    if any(issuer in r for r in records):
        return CheckResult("caa_allows", "pass", f"CAA permits {issuer}.",
                           "Your certificate can be renewed automatically.",
                           evidence="\n".join(records), resolver=ns)
    return CheckResult("caa_allows", "fail",
                       f"CAA does not list {issuer}, so renewal will silently fail.",
                       "Your site's security certificate will not renew, and visitors will "
                       "eventually see a warning instead of your site.",
                       evidence="\n".join(records), resolver=ns)


def run_all(domain: str, *, dkim_selector: str = "resend",
            expect_ns: str = "", ns: str = "1.1.1.1") -> list[CheckResult]:
    """Every credential-free check, against one domain."""
    return [
        spf_single(domain, ns), spf_lookups(domain, ns),
        dkim_present(domain, dkim_selector, ns),
        dmarc_present(domain, ns), dmarc_policy(domain, ns),
        mx_present(domain, ns), ns_delegated(domain, expect_ns, ns),
        apex_resolves(domain, ns), caa_allows(domain, ns=ns),
    ]
