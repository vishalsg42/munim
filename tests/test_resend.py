"""Resend is one end of the handoff the project is about.

It emits DKIM, SPF and return-path records that have to be written into
Cloudflare - a different company, a different login. Getting the A record wrong
means the site does not load. Getting these wrong means nothing breaks and the
client's mail stops arriving.
"""

import httpx
import respx

from munim.adapters.resend import DnsRecord, Domain, Resend
from munim.container import Container

API = "https://api.resend.com"


class Keychain:
    def get(self, client, provider):
        return "re_key" if provider == "resend" else None


def _r():
    return Resend(Container("ivy", Keychain()))


RECORDS = [
    {"record": "SPF", "type": "TXT", "name": "send",
     "value": "v=spf1 include:amazonses.com ~all", "status": "not_started"},
    {"record": "SPF", "type": "MX", "name": "send",
     "value": "feedback-smtp.us-east-1.amazonses.com", "priority": 10},
    {"record": "DKIM", "type": "CNAME", "name": "resend._domainkey",
     "value": "resend.dkim.amazonses.com"},
]


@respx.mock
async def test_creating_a_domain_returns_the_records_to_publish():
    respx.get(f"{API}/domains").mock(
        return_value=httpx.Response(200, json={"data": []}))
    respx.post(f"{API}/domains").mock(return_value=httpx.Response(200, json={
        "id": "d1", "name": "ivyandfern.example", "status": "not_started",
        "records": RECORDS}))

    domain, action = await _r().ensure_domain("ivyandfern.example")
    assert action == "created"
    assert {r.purpose for r in domain.records} == {"SPF", "DKIM"}


@respx.mock
async def test_an_existing_domain_is_not_created_twice():
    """A re-run must not mint a second set of DKIM keys: the published record
    would then not match the key the client's mail is signed with."""
    respx.get(f"{API}/domains").mock(return_value=httpx.Response(200, json={
        "data": [{"id": "d1", "name": "ivyandfern.example",
                  "status": "verified", "records": RECORDS}]}))
    create = respx.post(f"{API}/domains")

    domain, action = await _r().ensure_domain("ivyandfern.example")
    assert action == "unchanged"
    assert domain.verified
    assert not create.called


def test_relative_names_become_absolute_for_cloudflare():
    """Resend returns names relative to the domain; Cloudflare wants them
    fully qualified. Publishing 'resend._domainkey' on its own creates a record
    nobody can find."""
    domain = Domain(id="d1", name="ivyandfern.example", status="not_started",
                    records=[DnsRecord.from_api(r) for r in RECORDS])
    out = Resend.cloudflare_records(domain)
    names = {e["name"] for e in out}
    assert "send.ivyandfern.example" in names
    assert "resend._domainkey.ivyandfern.example" in names
    assert all(n.endswith("ivyandfern.example") for n in names)


def test_an_apex_record_is_not_doubled_up():
    domain = Domain(id="d1", name="ivyandfern.example", status="x", records=[
        DnsRecord(purpose="SPF", type="TXT", name="@", value="v=spf1 ~all")])
    assert Resend.cloudflare_records(domain)[0]["name"] == "ivyandfern.example"


def test_an_already_absolute_name_is_left_alone():
    domain = Domain(id="d1", name="ivyandfern.example", status="x", records=[
        DnsRecord(purpose="DKIM", type="CNAME",
                  name="resend._domainkey.ivyandfern.example", value="x")])
    assert Resend.cloudflare_records(domain)[0]["name"] == \
        "resend._domainkey.ivyandfern.example"


def test_mx_priority_survives_the_translation():
    """Dropping it publishes an MX record that cannot be ordered."""
    domain = Domain(id="d1", name="ivyandfern.example", status="x",
                    records=[DnsRecord.from_api(RECORDS[1])])
    assert Resend.cloudflare_records(domain)[0]["priority"] == 10


@respx.mock
async def test_the_key_is_sent_and_never_returned():
    route = respx.get(f"{API}/domains").mock(
        return_value=httpx.Response(200, json={"data": []}))
    result = await _r().domains()
    assert route.calls.last.request.headers["authorization"] == "Bearer re_key"
    assert "re_key" not in str(result)
