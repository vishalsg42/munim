"""The handoff: Resend emits records, Cloudflare publishes them.

Tested for the mistakes rather than the happy path, because this is the step
that fails invisibly. Every one of these, done wrong by hand, leaves a client
whose mail quietly stops being trusted.
"""

import pathlib

import httpx
import pytest
import respx

from munim.agent import mail as M
from munim.agent.mail import NeedsAPerson, set_up_mail
from munim.checks import dns as checks
from munim.container import Container
from munim.runlog import RunLog, new_run_id

CF = "https://api.cloudflare.com/client/v4"
RS = "https://api.resend.com"
DOMAIN = "ivyandfern.example"

RESEND_RECORDS = [
    {"record": "SPF", "type": "TXT", "name": "send",
     "value": "v=spf1 include:amazonses.com ~all"},
    {"record": "DKIM", "type": "CNAME", "name": "resend._domainkey",
     "value": "resend.dkim.amazonses.com"},
]


class Keychain:
    def get(self, client, provider):
        return {"cloudflare": "cf", "resend": "re"}.get(provider)


def _log(tmp_path):
    return RunLog(new_run_id(), pathlib.Path(tmp_path))


def _mock_resend():
    respx.get(f"{RS}/domains").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.post(f"{RS}/domains").mock(return_value=httpx.Response(200, json={
        "id": "d1", "name": DOMAIN, "status": "not_started",
        "records": RESEND_RECORDS}))
    respx.post(f"{RS}/domains/d1/verify").mock(
        return_value=httpx.Response(200, json={"status": "pending"}))


def _mock_zone():
    respx.get(f"{CF}/zones").mock(return_value=httpx.Response(200, json={
        "success": True, "errors": [], "result": [{"id": "z1", "name": DOMAIN}]}))


def _cf_list(records):
    return httpx.Response(200, json={"success": True, "errors": [], "result": records})


def _cf_one(record):
    return httpx.Response(200, json={"success": True, "errors": [], "result": record})


@respx.mock
async def test_records_are_published_with_fully_qualified_names(tmp_path, monkeypatch):
    """Resend returns 'resend._domainkey'. Published as-is that is a record
    nobody can find."""
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    _mock_resend(); _mock_zone()
    respx.get(f"{CF}/zones/z1/dns_records").mock(return_value=_cf_list([]))
    created = respx.post(f"{CF}/zones/z1/dns_records").mock(
        return_value=_cf_one({"id": "r", "type": "TXT", "name": "x", "content": "y"}))

    await set_up_mail(Container("ivy", Keychain()), DOMAIN, _log(tmp_path))

    import json
    names = [json.loads(c.request.content)["name"] for c in created.calls]
    assert f"send.{DOMAIN}" in names
    assert f"resend._domainkey.{DOMAIN}" in names


@respx.mock
async def test_dkim_is_never_published_behind_the_proxy(tmp_path, monkeypatch):
    """Cloudflare rewrites a proxied record, and a rewritten DKIM CNAME stops
    verifying. It is the second item in the check catalogue."""
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    _mock_resend(); _mock_zone()
    respx.get(f"{CF}/zones/z1/dns_records").mock(return_value=_cf_list([]))
    created = respx.post(f"{CF}/zones/z1/dns_records").mock(
        return_value=_cf_one({"id": "r", "type": "CNAME", "name": "x", "content": "y"}))

    await set_up_mail(Container("ivy", Keychain()), DOMAIN, _log(tmp_path))

    import json
    for call in created.calls:
        assert json.loads(call.request.content)["proxied"] is False


@respx.mock
async def test_an_existing_sender_policy_is_merged_not_appended(tmp_path, monkeypatch):
    """The whole reason this is an agent. Appending here means receivers ignore
    both policies and the client's mail authenticates as neither."""
    existing = "v=spf1 include:_spf.google.com ~all"
    monkeypatch.setattr(checks, "query",
                        lambda name, rdtype, nameserver="1.1.1.1":
                        [existing] if rdtype == "TXT" else [])
    _mock_resend(); _mock_zone()
    respx.get(f"{CF}/zones/z1/dns_records").mock(return_value=_cf_list([
        {"id": "r1", "type": "TXT", "name": f"send.{DOMAIN}", "content": existing}]))
    updated = respx.put(f"{CF}/zones/z1/dns_records/r1").mock(
        return_value=_cf_one({"id": "r1", "type": "TXT", "name": "x", "content": "y"}))
    created = respx.post(f"{CF}/zones/z1/dns_records").mock(
        return_value=_cf_one({"id": "r2", "type": "CNAME", "name": "x", "content": "y"}))

    approved = []
    result = await set_up_mail(Container("ivy", Keychain()), DOMAIN, _log(tmp_path),
                               approve=lambda merged: approved.append(merged) or True)

    assert approved, "changed an existing record without asking"
    assert "include:_spf.google.com" in result.merged
    assert "include:amazonses.com" in result.merged
    assert updated.called
    # Only the DKIM CNAME is newly created; the SPF record was merged in place.
    import json
    assert all(json.loads(c.request.content)["type"] == "CNAME" for c in created.calls)


@respx.mock
async def test_replacing_an_existing_record_without_approval_stops(tmp_path, monkeypatch):
    """Creating a record nobody has is not a judgement call. Replacing one
    somebody put there on purpose is."""
    monkeypatch.setattr(checks, "query",
                        lambda name, rdtype, nameserver="1.1.1.1":
                        ["v=spf1 include:_spf.google.com ~all"] if rdtype == "TXT" else [])
    _mock_resend(); _mock_zone()
    respx.get(f"{CF}/zones/z1/dns_records").mock(return_value=_cf_list([]))
    respx.post(f"{CF}/zones/z1/dns_records").mock(
        return_value=_cf_one({"id": "r", "type": "TXT", "name": "x", "content": "y"}))

    with pytest.raises(NeedsAPerson, match="approval"):
        await set_up_mail(Container("ivy", Keychain()), DOMAIN, _log(tmp_path))


@respx.mock
async def test_a_merge_that_would_still_fail_escalates(tmp_path, monkeypatch):
    """Over ten lookups is a permerror. Writing that is not a fix, so a person
    has to decide which senders to drop."""
    crowded = "v=spf1 " + " ".join(f"include:s{i}.example" for i in range(10)) + " ~all"
    monkeypatch.setattr(checks, "query",
                        lambda name, rdtype, nameserver="1.1.1.1":
                        [crowded] if rdtype == "TXT" else [])
    _mock_resend(); _mock_zone()
    respx.get(f"{CF}/zones/z1/dns_records").mock(return_value=_cf_list([]))
    respx.post(f"{CF}/zones/z1/dns_records").mock(
        return_value=_cf_one({"id": "r", "type": "TXT", "name": "x", "content": "y"}))

    with pytest.raises(NeedsAPerson, match="lookups"):
        await set_up_mail(Container("ivy", Keychain()), DOMAIN, _log(tmp_path),
                          approve=lambda m: True)


@respx.mock
async def test_running_it_twice_changes_nothing_the_second_time(tmp_path, monkeypatch):
    """Idempotent, so an interrupted setup is safe to re-run."""
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    respx.get(f"{RS}/domains").mock(return_value=httpx.Response(200, json={
        "data": [{"id": "d1", "name": DOMAIN, "status": "verified",
                  "records": RESEND_RECORDS}]}))
    respx.post(f"{RS}/domains/d1/verify").mock(
        return_value=httpx.Response(200, json={"status": "verified"}))
    create_domain = respx.post(f"{RS}/domains")
    _mock_zone()
    respx.get(f"{CF}/zones/z1/dns_records").mock(return_value=_cf_list([
        {"id": "r1", "type": "TXT", "name": f"send.{DOMAIN}",
         "content": "v=spf1 include:amazonses.com ~all"},
        {"id": "r2", "type": "CNAME", "name": f"resend._domainkey.{DOMAIN}",
         "content": "resend.dkim.amazonses.com"}]))
    create_record = respx.post(f"{CF}/zones/z1/dns_records")

    result = await set_up_mail(Container("ivy", Keychain()), DOMAIN, _log(tmp_path))

    assert not create_domain.called, "minted a second set of DKIM keys"
    assert not create_record.called, "rewrote records that were already correct"
    assert len(result.unchanged) == 2 and not result.published
