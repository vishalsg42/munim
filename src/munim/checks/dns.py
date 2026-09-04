"""The checks that need no credentials.

Every one of these is a real failure an operator hits, and none of them are run
today, because running thirteen checks by hand on every launch for every client is
not realistic. That is the whole product in one sentence.

Deterministic on purpose (D7): these are pure functions over DNS answers. The
model never decides whether a check passed - it decides what to do about it and
how to say it to the person who owns the domain.

The resolver strategy matters. A negative answer taken before a write is cached
for the zone's SOA minimum, so a single resolver keeps reporting NXDOMAIN long
after the record exists. Asking the authoritative nameserver and a public
resolver separately turns that into the diagnosis rather than a wrong answer.
"""

import asyncio
import re
import socket
import ssl
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import httpx

import dns.exception
import dns.rdatatype
import dns.resolver

Status = Literal["pass", "fail", "skip"]

# Domains owned by a hosting platform, not by the business. A project deployed
# to one of these has no mail of its own and never will, so reporting missing
# SPF, DKIM, DMARC or MX on it is noise - and a check that cries wolf on a
# preview URL is a check people learn to ignore.
#
# Found by running the catalogue against a real client's Vercel URL, which
# reported six failures that were all correct behaviour.
PLATFORM_SUFFIXES = (
    ".vercel.app", ".netlify.app", ".pages.dev", ".github.io", ".herokuapp.com",
    ".azurewebsites.net", ".onrender.com", ".fly.dev", ".workers.dev",
    ".surge.sh", ".web.app", ".firebaseapp.com", ".repl.co",
)

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


def is_platform_domain(domain: str) -> bool:
    """Whether this name belongs to a hosting platform rather than the business."""
    lowered = domain.lower().rstrip(".")
    return any(lowered.endswith(suffix) for suffix in PLATFORM_SUFFIXES)


# Which part of the setup a check speaks for, so a skip explains itself in the
# right terms. "mail settings belong to the platform" is wrong about whether www
# reaches the site.
# The verb travels with the subject: "DNS belong" and "the certificate belong"
# are the same fault as "2 things needs your attention".
_SUBJECT = {
    "spf_single": "mail settings belong", "spf_lookups": "mail settings belong",
    "dkim_present": "mail settings belong", "dkim_chunking": "mail settings belong",
    "dmarc_present": "mail settings belong", "dmarc_policy": "mail settings belong",
    "mx_present": "mail settings belong",
    "ns_delegated": "DNS belongs", "apex_resolves": "DNS belongs",
    "caa_allows": "DNS belongs",
    "www_redirect": "the web address belongs",
    "https_enforced": "the web address belongs",
    "cert_valid": "the certificate belongs",
}


def _not_their_domain(check: str, domain: str) -> CheckResult:
    platform = next(s for s in PLATFORM_SUFFIXES if domain.lower().endswith(s))
    subject = _SUBJECT.get(check, "these settings belong")
    return CheckResult(
        check, "skip",
        f"{domain} is a {platform.lstrip('.')} address, so {subject} to "
        "the platform, not to this business.",
        "", detail={"reason": "platform_domain"})


def _resolver(nameserver: str | None = None) -> dns.resolver.Resolver:
    r = dns.resolver.Resolver(configure=nameserver is None)
    if nameserver:
        r.nameservers = [nameserver]
    r.lifetime = 8.0
    r.timeout = 4.0
    return r


# Prefetched answers for the task currently running. A ContextVar rather than a
# module global: gather() copies the context into each task, so two clients
# checked at once cannot see each other's answers. The previous version swapped
# the module-level `query` for a closure and restored it in a finally, which is
# safe only for as long as nothing between the swap and the restore awaits. One
# await added later, or one call from a second event loop, and a client is
# served another client's DNS - the exact failure this project exists to prevent.
_prefetched: ContextVar[dict[tuple[str, str], list[str]] | None] = ContextVar(
    "_prefetched", default=None)


def query(name: str, rdtype: str, nameserver: str = "1.1.1.1") -> list[str]:
    """Return record values as strings. An absent record is an empty list, not
    an exception - absence is an answer here, not a failure."""
    cache = _prefetched.get()
    if cache is not None:
        answered = cache.get((name, rdtype))
        if answered is not None:
            return answered
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
    if is_platform_domain(domain):
        return _not_their_domain("spf_single", domain)
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
    if is_platform_domain(domain):
        return _not_their_domain("spf_lookups", domain)
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
    if is_platform_domain(domain):
        return _not_their_domain("dmarc_present", domain)
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
    if is_platform_domain(domain):
        return _not_their_domain("dmarc_policy", domain)
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
    if is_platform_domain(domain):
        return _not_their_domain("dkim_present", domain)
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
    if is_platform_domain(domain):
        return _not_their_domain("ns_delegated", domain)
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
    if is_platform_domain(domain):
        return _not_their_domain("mx_present", domain)
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


def dkim_chunking(domain: str, selector: str, ns: str = "1.1.1.1") -> CheckResult:
    """A DKIM key longer than 255 bytes must be split into several strings.

    Pasted as one long string it is silently invalid: the record exists, looks
    right in a dashboard, and no receiver can verify a signature with it.
    """
    if is_platform_domain(domain):
        return _not_their_domain("dkim_chunking", domain)
    name = f"{selector}._domainkey.{domain}"
    txts = query(name, "TXT", ns)
    if not txts:
        return CheckResult("dkim_chunking", "skip", "No DKIM record to inspect.", "", resolver=ns)
    joined = txts[0]
    if len(joined) <= 255:
        return CheckResult("dkim_chunking", "pass", "DKIM key is short enough not to need splitting.",
                           "Your email signature is published correctly.", resolver=ns)
    # dnspython joins the strings for us, so a correctly chunked record arrives
    # whole. What we can still catch is a key that is present but unparseable.
    if "p=" not in joined or len(joined.split("p=")[1].strip().strip('"')) < 100:
        return CheckResult("dkim_chunking", "fail",
                           "DKIM record is present but the key is truncated or malformed.",
                           "Your email signature is published but unusable, so receivers "
                           "cannot verify your mail even though it looks set up.",
                           evidence=joined[:120] + "…", resolver=ns)
    return CheckResult("dkim_chunking", "pass", "DKIM key parses and is a plausible length.",
                       "Your email signature is published correctly.", resolver=ns)


def www_redirect(domain: str, timeout: float = 8.0) -> CheckResult:
    """Half of everyone types www. If it does not reach the site, half of the
    business's customers see an error."""
    if is_platform_domain(domain):
        return _not_their_domain("www_redirect", domain)
    response = None
    last: Exception | None = None
    for _ in range(2):
        try:
            response = httpx.get(f"https://www.{domain}", follow_redirects=True,
                                 timeout=timeout)
            break
        except httpx.HTTPError as exc:
            last = exc

    if response is None:
        # Two different answers wearing the same exception. If www does not
        # resolve at all then customers really cannot reach it, which is the
        # finding. If it resolves and the request did not complete, that is the
        # network on the day, and reporting it as a failure is how an audit
        # across a dozen clients teaches people to ignore it (D20).
        if not query(f"www.{domain}", "A") and not query(f"www.{domain}", "AAAA") \
                and not query(f"www.{domain}", "CNAME"):
            return CheckResult("www_redirect", "fail",
                               f"www.{domain} does not resolve.",
                               "Customers who type www before your address will not "
                               "reach your site.", resolver="https")
        return CheckResult("www_redirect", "skip",
                           f"www.{domain} resolves but did not answer twice: "
                           f"{type(last).__name__}. Undetermined rather than failing.",
                           "", resolver="https", detail={"reason": "unreachable"})
    if response.status_code < 400:
        return CheckResult("www_redirect", "pass",
                           f"www.{domain} reaches the site ({response.status_code}).",
                           "Your address works with or without www.",
                           evidence=str(response.url), resolver="https")
    return CheckResult("www_redirect", "fail",
                       f"www.{domain} returns {response.status_code}.",
                       "Customers who type www before your address see an error.",
                       resolver="https")


def https_enforced(domain: str, timeout: float = 8.0) -> CheckResult:
    """Plain http must end up on https, or a browser shows 'Not secure'."""
    response = None
    last: Exception | None = None
    for _ in range(2):
        try:
            response = httpx.get(f"http://{domain}", follow_redirects=True,
                                 timeout=timeout)
            break
        except httpx.HTTPError as exc:
            last = exc

    if response is None:
        # Whether http redirects to https is unanswerable if http never
        # answered. Saying "your site may not load" on that basis is a guess
        # dressed as a finding, and an audit repeats it across every client.
        return CheckResult("https_enforced", "skip",
                           f"http://{domain} did not answer twice: "
                           f"{type(last).__name__}. Whether it redirects is "
                           f"undetermined rather than failing.",
                           "", resolver="http", detail={"reason": "unreachable"})
    if str(response.url).startswith("https://"):
        return CheckResult("https_enforced", "pass", "Plain http redirects to https.",
                           "Visitors always arrive on the secure version of your site.",
                           evidence=str(response.url), resolver="http")
    return CheckResult("https_enforced", "fail", "Plain http is served without redirecting.",
                       "Some visitors see a 'Not secure' warning in their browser instead "
                       "of your site.", evidence=str(response.url), resolver="http")


def cert_valid(domain: str, days: int = 14, timeout: float = 8.0,
               attempts: int = 2) -> CheckResult:
    """A certificate that expires unnoticed replaces the site with a warning.

    A rejected certificate and an unreachable host are different answers and
    used to be the same one. Auditing a dozen clients at once made the
    difference visible: a transient timeout was reported as a broken
    certificate on a domain whose certificate had 84 days left. A check that
    cries wolf is worth less than no check (D20), so a handshake that could not
    be completed is now reported as not determined rather than as a failure.
    """
    context = ssl.create_default_context()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with socket.create_connection((domain, 443), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as tls:
                    cert = tls.getpeercert()
            break
        except ssl.SSLCertVerificationError as exc:
            # The host answered and the certificate is not acceptable. That is
            # the failure this check exists to find, and retrying will not
            # change it.
            return CheckResult("cert_valid", "fail",
                               f"{domain} presented a certificate that does not "
                               f"verify: {getattr(exc, 'verify_message', None) or exc}.",
                               "Visitors see a security warning instead of your site.",
                               resolver="tls")
        except (OSError, ssl.SSLError) as exc:
            last = exc
    else:
        return CheckResult("cert_valid", "skip",
                           f"Could not complete a TLS handshake with {domain} "
                           f"after {attempts} attempts: {last}. Not the same as "
                           f"a bad certificate, so this is undetermined rather "
                           f"than failing.",
                           "", resolver="tls",
                           detail={"reason": "unreachable"})
    expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
        tzinfo=timezone.utc)
    left = (expires - datetime.now(timezone.utc)).days
    if left > days:
        return CheckResult("cert_valid", "pass",
                           f"Certificate valid for another {left} days.",
                           "Your site is secure and the certificate is not close to expiring.",
                           evidence=f"notAfter={cert['notAfter']}", resolver="tls")
    return CheckResult("cert_valid", "fail",
                       f"Certificate expires in {left} days.",
                       "Visitors will start seeing a security warning instead of your site "
                       f"in {left} days unless it renews.",
                       evidence=f"notAfter={cert['notAfter']}", resolver="tls",
                       detail={"days_left": left})


async def prefetch(domain: str, dkim_selector: str = "resend",
                   ns: str = "1.1.1.1") -> dict[tuple[str, str], list[str]]:
    """Fetch every record the catalogue needs, concurrently, once.

    The checks are sequential and several read the same record - spf_single and
    spf_lookups both want the apex TXT, dmarc_present and dmarc_policy both want
    _dmarc. Fetching serially made a "parallel" scan slower than a serial one,
    because the concurrency was at the wrong level: threads per client, each
    still doing thirteen round trips in a row.

    This fans out at the level that actually costs time - the lookups - and
    deduplicates them.
    """
    wanted = [
        (domain, "TXT"), (domain, "MX"), (domain, "NS"),
        (domain, "A"), (domain, "AAAA"), (domain, "CAA"),
        (f"_dmarc.{domain}", "TXT"),
        (f"{dkim_selector}._domainkey.{domain}", "TXT"),
    ]
    answers = await asyncio.gather(
        *(asyncio.to_thread(query, name, rdtype, ns) for name, rdtype in wanted),
        return_exceptions=True,
    )
    cache: dict[tuple[str, str], list[str]] = {}
    for key, value in zip(wanted, answers):
        cache[key] = [] if isinstance(value, BaseException) else value
    return cache


async def run_all_async(domain: str, *, dkim_selector: str = "resend",
                        expect_ns: str = "", ns: str = "1.1.1.1") -> list[CheckResult]:
    """run_all, with the lookups fanned out and deduplicated first."""
    cache = await prefetch(domain, dkim_selector, ns)
    token = _prefetched.set(cache)
    try:
        # In a thread, not inline: the checks are synchronous, and any lookup
        # the prefetch missed is a network call that would otherwise stall the
        # event loop and every other client being checked alongside it.
        # to_thread copies the context, so the cache above travels with it.
        return await asyncio.to_thread(
            run_all, domain, dkim_selector=dkim_selector,
            expect_ns=expect_ns, ns=ns)
    finally:
        _prefetched.reset(token)


async def run_reachability_async(domain: str) -> list[CheckResult]:
    """run_reachability, with the three connections made at the same time."""
    return list(await asyncio.gather(
        asyncio.to_thread(www_redirect, domain),
        asyncio.to_thread(https_enforced, domain),
        asyncio.to_thread(cert_valid, domain),
    ))


def run_all(domain: str, *, dkim_selector: str = "resend",
            expect_ns: str = "", ns: str = "1.1.1.1") -> list[CheckResult]:
    """Every credential-free check, against one domain."""
    return [
        spf_single(domain, ns), spf_lookups(domain, ns),
        dkim_present(domain, dkim_selector, ns),
        dkim_chunking(domain, dkim_selector, ns),
        dmarc_present(domain, ns), dmarc_policy(domain, ns),
        mx_present(domain, ns), ns_delegated(domain, expect_ns, ns),
        apex_resolves(domain, ns), caa_allows(domain, ns=ns),
    ]


def run_reachability(domain: str) -> list[CheckResult]:
    """Checks that need a live connection rather than a DNS answer. Separate
    because they are slower and can be skipped when a domain is not up yet."""
    return [www_redirect(domain), https_enforced(domain), cert_valid(domain)]
