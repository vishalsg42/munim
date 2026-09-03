"""The write path, tested against Cloudflare's documented response shapes.

The property under test is idempotency. A launch that fails halfway and is
re-run must not append a second SPF record, because two SPF records means
receivers ignore both - the first item in this project's own check catalogue.
A tool that causes the fault it reports is worse than no tool.

respx intercepts at the transport, so the adapter's real request construction,
auth header and response parsing all execute.
"""

import httpx
import pytest
import respx

from munim.adapters.cloudflare import Cloudflare, CloudflareError
from munim.container import Container

API = "https://api.cloudflare.com/client/v4"
ZONE = "zone123"


class Keychain:
    def get(self, client, provider):
        return "cf-token" if provider == "cloudflare" else None


def _container():
    return Container("acme", Keychain())


def _record(rid, content, rtype="TXT", name="acme.example"):
    return {"id": rid, "type": rtype, "name": name, "content": content,
            "ttl": 1, "proxied": False}


def _list(records):
    return httpx.Response(200, json={"success": True, "errors": [], "result": records})


def _one(record):
    return httpx.Response(200, json={"success": True, "errors": [], "result": record})


@respx.mock
async def test_an_identical_record_is_left_alone():
    respx.get(f"{API}/zones/{ZONE}/dns_records").mock(
        return_value=_list([_record("r1", "v=spf1 include:amazonses.com ~all")]))
    create = respx.post(f"{API}/zones/{ZONE}/dns_records")
    update = respx.put(url__startswith=f"{API}/zones/{ZONE}/dns_records/")

    record, action = await Cloudflare(_container()).upsert(
        ZONE, type="TXT", name="acme.example",
        content="v=spf1 include:amazonses.com ~all")

    assert action == "unchanged"
    assert not create.called, "a correct record was rewritten"
    assert not update.called


@respx.mock
async def test_a_differing_record_is_updated_in_place_not_appended():
    """This is the whole point: append here and the domain ends up with two."""
    respx.get(f"{API}/zones/{ZONE}/dns_records").mock(
        return_value=_list([_record("r1", "v=spf1 include:_spf.google.com ~all")]))
    update = respx.put(f"{API}/zones/{ZONE}/dns_records/r1").mock(
        return_value=_one(_record("r1", "v=spf1 include:amazonses.com ~all")))
    create = respx.post(f"{API}/zones/{ZONE}/dns_records")

    _, action = await Cloudflare(_container()).upsert(
        ZONE, type="TXT", name="acme.example",
        content="v=spf1 include:amazonses.com ~all")

    assert action == "updated"
    assert update.called
    assert not create.called, "appended instead of updating: this creates the duplicate-SPF fault"


@respx.mock
async def test_a_genuinely_new_record_is_created():
    respx.get(f"{API}/zones/{ZONE}/dns_records").mock(return_value=_list([]))
    create = respx.post(f"{API}/zones/{ZONE}/dns_records").mock(
        return_value=_one(_record("new", "v=spf1 include:amazonses.com ~all")))

    _, action = await Cloudflare(_container()).upsert(
        ZONE, type="TXT", name="acme.example",
        content="v=spf1 include:amazonses.com ~all")

    assert action == "created"
    assert create.called


@respx.mock
async def test_writing_beside_existing_duplicates_is_refused():
    """Merging is a judgement call, so the adapter stops rather than guessing."""
    respx.get(f"{API}/zones/{ZONE}/dns_records").mock(return_value=_list([
        _record("r1", "v=spf1 include:_spf.google.com ~all"),
        _record("r2", "v=spf1 include:amazonses.com ~all"),
    ]))
    with pytest.raises(CloudflareError, match="already exist"):
        await Cloudflare(_container()).upsert(
            ZONE, type="TXT", name="acme.example", content="v=spf1 include:x ~all")


@respx.mock
async def test_merging_leaves_exactly_one_record():
    respx.get(f"{API}/zones/{ZONE}/dns_records").mock(return_value=_list([
        _record("r1", "v=spf1 include:_spf.google.com ~all"),
        _record("r2", "v=spf1 include:amazonses.com ~all"),
    ]))
    merged = "v=spf1 include:_spf.google.com include:amazonses.com ~all"
    update = respx.put(f"{API}/zones/{ZONE}/dns_records/r1").mock(
        return_value=_one(_record("r1", merged)))
    delete = respx.delete(f"{API}/zones/{ZONE}/dns_records/r2").mock(
        return_value=httpx.Response(200, json={"success": True, "errors": [], "result": {}}))

    record, action = await Cloudflare(_container()).merge_spf(ZONE, "acme.example", merged)

    assert action == "merged"
    assert update.called and delete.called
    assert record.content == merged


@respx.mock
async def test_the_token_is_sent_but_never_returned():
    route = respx.get(f"{API}/zones").mock(
        return_value=_list([{"id": ZONE, "name": "acme.example"}]))
    result = await Cloudflare(_container()).zone_id("acme.example")
    assert route.calls.last.request.headers["authorization"] == "Bearer cf-token"
    assert "cf-token" not in str(result)


@respx.mock
async def test_a_domain_in_the_wrong_account_says_so_plainly():
    """Naming the wrong client is the failure this product is built to prevent,
    so the error has to name the possibility."""
    respx.get(f"{API}/zones").mock(return_value=_list([]))
    with pytest.raises(CloudflareError, match="wrong client"):
        await Cloudflare(_container()).zone_id("someone-elses.example")
