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

from munim.adapters.cloudflare import (Cloudflare, CloudflareError,
                                       Record, unquoted)
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


class _Zone:
    """A Cloudflare zone that remembers what was written to it.

    A fake that answers every list with the same fixed rows cannot tell a merge
    that worked from one that left both policies in place, which is the only
    thing this function has to get right. It has to hold state.
    """

    def __init__(self, records):
        self.rows = {r["id"]: r for r in records}
        self.deleted = []
        self.updated = []
        self.fail_delete = None            # record id whose delete is rejected
        self.fail_put = False              # the write is rejected
        self.pretend_deletes_worked = False  # 200 OK, nothing actually removed

    def install(self):
        respx.get(f"{API}/zones/{ZONE}/dns_records").mock(
            side_effect=lambda request: _list(list(self.rows.values())))
        respx.put(url__startswith=f"{API}/zones/{ZONE}/dns_records/").mock(
            side_effect=self._put)
        respx.delete(url__startswith=f"{API}/zones/{ZONE}/dns_records/").mock(
            side_effect=self._delete)
        return self

    def _id(self, request):
        return str(request.url).rsplit("/", 1)[-1]

    def _put(self, request):
        import json as _json
        rid = self._id(request)
        if self.fail_put:
            return httpx.Response(200, json={
                "success": False, "errors": [{"message": "rejected"}], "result": None})
        body = _json.loads(request.content)
        self.rows[rid] = {**self.rows[rid], **body, "id": rid}
        self.updated.append(rid)
        return _one(self.rows[rid])

    def _delete(self, request):
        rid = self._id(request)
        if self.fail_delete == rid:
            return httpx.Response(200, json={
                "success": False, "errors": [{"message": "rate limited"}], "result": None})
        if self.pretend_deletes_worked:
            self.deleted.append(rid)
            return httpx.Response(200, json={"success": True, "errors": [], "result": {}})
        self.rows.pop(rid, None)
        self.deleted.append(rid)
        return httpx.Response(200, json={"success": True, "errors": [], "result": {}})

    def spf(self):
        return [r for r in self.rows.values()
                if r["content"].lower().startswith("v=spf1")]


@respx.mock
async def test_merging_leaves_exactly_one_record():
    zone = _Zone([
        _record("r1", "v=spf1 include:_spf.google.com ~all"),
        _record("r2", "v=spf1 include:amazonses.com ~all"),
    ]).install()
    merged = "v=spf1 include:_spf.google.com include:amazonses.com ~all"

    record, action = await Cloudflare(_container()).merge_spf(ZONE, "acme.example", merged)

    assert action == "merged"
    assert record.content == merged
    assert len(zone.spf()) == 1, f"left {len(zone.spf())} policies behind"
    assert zone.spf()[0]["content"] == merged


@respx.mock
async def test_a_failed_write_leaves_one_policy_not_three():
    """Deleting before writing is what makes a partial failure survivable.

    Write-then-delete and delete-then-write fail equally badly when a *delete*
    fails: either way two policies are left and receivers ignore both. They
    differ when the *write* fails. Write first and nothing has been removed, so
    the domain keeps every policy it had and mail stays broken. Delete first and
    the leftovers are already gone, so the domain is left with one intact
    policy: not the merge that was wanted, but a working one.
    """
    zone = _Zone([
        _record("r1", "v=spf1 include:_spf.google.com ~all"),
        _record("r2", "v=spf1 include:amazonses.com ~all"),
        _record("r3", "v=spf1 include:mailgun.org ~all"),
    ]).install()
    zone.fail_put = True
    merged = "v=spf1 include:_spf.google.com include:amazonses.com ~all"

    with pytest.raises(CloudflareError):
        await Cloudflare(_container()).merge_spf(ZONE, "acme.example", merged)

    left = zone.spf()
    assert len(left) == 1, f"a failed write left {len(left)} policies in place"
    assert left[0]["content"] == "v=spf1 include:_spf.google.com ~all"


@respx.mock
async def test_a_merge_that_did_not_take_is_reported_not_assumed():
    """An API that answers success without changing anything must not read as a
    successful merge. The caller's whole reason for calling is that there ends
    up being one policy, so that is read back rather than inferred from
    two HTTP 200s."""
    zone = _Zone([
        _record("r1", "v=spf1 include:_spf.google.com ~all"),
        _record("r2", "v=spf1 include:amazonses.com ~all"),
    ]).install()
    zone.pretend_deletes_worked = True   # 200 OK, nothing removed
    merged = "v=spf1 include:_spf.google.com include:amazonses.com ~all"

    with pytest.raises(CloudflareError, match="2 sender policies after the merge"):
        await Cloudflare(_container()).merge_spf(ZONE, "acme.example", merged)


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


# ---- TXT values as a resolver sees them ---------------------------------
#
# Found on a live zone on 2026-09-13: the same zone returned SPF records quoted
# and DKIM records bare, because Cloudflare hands back whichever form a record
# was created in. Nothing normalised it, so `"v=spf1 ..."` failed
# `startswith("v=spf1")` and a published policy was invisible to every piece of
# code that looks for one.



def test_a_quoted_value_reads_as_the_resolver_reports_it():
    assert unquoted('"v=spf1 include:amazonses.com ~all"') == \
        "v=spf1 include:amazonses.com ~all"


def test_a_bare_value_is_left_alone():
    assert unquoted("v=DMARC1; p=quarantine") == "v=DMARC1; p=quarantine"


def test_a_split_value_is_joined():
    """A long DKIM key is stored as several strings and answered as one."""
    assert unquoted('"v=DKIM1; p=AAAA" "BBBB"') == "v=DKIM1; p=AAAABBBB"


def test_an_escaped_quote_survives():
    assert unquoted('"a \\"b\\" c"') == 'a "b" c'


def test_a_value_that_merely_contains_a_quote_is_not_mangled():
    assert unquoted('say "what"') == 'say "what"'


def test_a_quoted_spf_record_is_visible_to_the_code_that_looks_for_policies():
    """The bug, at the point it did damage.

    `mailplan` and `merge_spf` both select policies with
    `content.lower().startswith("v=spf1")`. A dashboard-created SPF record
    failed that test, so `plan` offered to create a policy that was already
    published, which is the duplicate-SPF fault this tool detects, proposed by
    the tool itself.
    """
    record = Record.from_api({
        "id": "r1", "type": "TXT", "name": "send.acme.example",
        "content": '"v=spf1 include:amazonses.com ~all"'})

    assert record.content.lower().startswith("v=spf1")


def test_only_textual_records_are_normalised():
    """A CNAME target is not a quoted string and must not be treated as one."""
    record = Record.from_api({
        "id": "r1", "type": "CNAME", "name": "www.acme.example",
        "content": '"weird".example'})

    assert record.content == '"weird".example'


@respx.mock
async def test_merge_sees_a_policy_that_was_added_in_the_dashboard():
    """The worst shape of the quoting bug, and why it is fixed at the boundary
    rather than at each comparison.

    Two policies, one added through the dashboard and one through the API, is
    exactly the state `merge_spf` exists for. Unnormalised, it saw one, left
    the other in place, and then its own read-back guard, written for precisely
    this failure, counted with the same blind spot and reported success. The
    domain would have been left with two policies and a log line saying one.
    """
    merged = "v=spf1 include:old.example include:amazonses.com ~all"
    route = respx.get(f"{API}/zones/{ZONE}/dns_records")
    route.side_effect = [
        _list([_record("r1", '"v=spf1 include:old.example ~all"'),
               _record("r2", "v=spf1 include:amazonses.com ~all")]),
        _list([_record("r1", merged)]),
    ]
    gone = respx.delete(f"{API}/zones/{ZONE}/dns_records/r2").mock(
        return_value=_one(_record("r2", "x")))
    respx.put(f"{API}/zones/{ZONE}/dns_records/r1").mock(
        return_value=_one(_record("r1", merged)))

    _, action = await Cloudflare(_container()).merge_spf(ZONE, "acme.example", merged)

    assert action == "merged"
    assert gone.called, "the quoted policy was left behind"


@respx.mock
async def test_a_correct_record_stored_with_quotes_is_left_alone():
    """`upsert` compares content to decide create, update or nothing. A record
    that is already right, stored quoted, compared unequal and was rewritten
    for no reason."""
    respx.get(f"{API}/zones/{ZONE}/dns_records").mock(
        return_value=_list([_record("r1", '"v=spf1 include:amazonses.com ~all"')]))
    create = respx.post(f"{API}/zones/{ZONE}/dns_records")
    update = respx.put(url__startswith=f"{API}/zones/{ZONE}/dns_records/")

    _, action = await Cloudflare(_container()).upsert(
        ZONE, type="TXT", name="acme.example",
        content="v=spf1 include:amazonses.com ~all")

    assert action == "unchanged"
    assert not create.called and not update.called
