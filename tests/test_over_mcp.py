"""Reaching a client's REST API through the session they already have.

The fixtures here are what Cloudflare's and Resend's live MCP servers actually
returned on 2026-09-12, not what their docs describe. The Resend ones matter
most: that server writes for a person, and a DKIM key read wrongly out of prose
is a value that looks plausible and gets published into somebody's DNS.
"""

import json

import httpx
import pytest

from munim.remote import rest, resendtext
from munim.remote.resendtext import ResendTextError

# ---- measured 2026-09-12, resend list-domains and get-domain -------------

LIST = ["Found 1 domain:",
        "Name: acme.example\nID: ad1b8ef1-206e-4bc5-b442-cc5ed8fff7d9\n"
        "Status: verified\nRegion: ap-northeast-1\nSending: enabled\n"
        "Receiving: disabled\nOpen Tracking: false\nClick Tracking: false\n"
        "Created at: 2026-09-06 11:56:10.502912+00"]

RECORDS = ("DNS Records:\n\nDKIM (TXT):\n  Name: resend._domainkey\n"
           "  Value: p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC6hsA9\n"
           "  TTL: Auto\n  Status: verified\n\n"
           "SPF (MX):\n  Name: send\n"
           "  Value: feedback-smtp.ap-northeast-1.amazonses.com\n"
           "  TTL: Auto\n  Status: verified\n  Priority: 10\n\n"
           "SPF (TXT):\n  Name: send\n  Value: v=spf1 include:amazonses.com ~all\n"
           "  TTL: Auto\n  Status: verified")

GET = [LIST[1], RECORDS]


# ---- the parser ----------------------------------------------------------

def test_a_domain_comes_out_of_the_prose():
    found = resendtext.one(resendtext.joined(GET))

    assert found["id"] == "ad1b8ef1-206e-4bc5-b442-cc5ed8fff7d9"
    assert found["name"] == "acme.example"
    assert found["status"] == "verified"


def test_every_record_comes_out_whole():
    found = resendtext.records(resendtext.joined(GET))

    assert [(r["record"], r["type"], r["name"]) for r in found] == [
        ("DKIM", "TXT", "resend._domainkey"),
        ("SPF", "MX", "send"),
        ("SPF", "TXT", "send"),
    ]
    assert found[0]["value"].startswith("p=MIGfMA0GCSqGSIb3DQEB")
    assert found[1]["priority"] == 10


def test_the_list_carries_no_records_and_that_is_not_an_error():
    """`list-domains` prints no DNS section, exactly as `GET /domains` omits
    the array. A domain with nothing published is a different thing from one
    whose records could not be read."""
    assert resendtext.records(resendtext.joined(LIST)) == []
    assert resendtext.one(resendtext.joined(LIST))["records"] == []


def test_a_records_section_that_parses_to_nothing_is_an_error():
    """The failure that matters is silent. If Resend reformats, an empty list
    here would mean `plan` finds nothing to publish and reports the domain
    fine."""
    with pytest.raises(ResendTextError, match="format has most likely changed"):
        resendtext.records("DNS Records:\n\nwho knows what this is now\n")


def test_a_dkim_value_that_is_not_a_dkim_key_is_refused():
    """A heading saying DKIM over a value that is not one is the case where
    guessing publishes a key nobody holds."""
    bad = RECORDS.replace("p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC6hsA9",
                          "resend.dkim.amazonses.com")

    with pytest.raises(ResendTextError, match="does not look like one"):
        resendtext.records(bad)


def test_a_record_with_no_value_is_refused():
    bad = RECORDS.replace("  Value: v=spf1 include:amazonses.com ~all\n", "")

    with pytest.raises(ResendTextError, match="has no value"):
        resendtext.records(bad)


def test_a_priority_that_is_not_a_number_is_refused():
    with pytest.raises(ResendTextError, match="not a number"):
        resendtext.records(RECORDS.replace("Priority: 10", "Priority: high"))


def test_two_domains_where_one_was_expected_is_refused():
    two = resendtext.joined(LIST) + "\n\nName: other.example\nID: d2\nStatus: verified"

    with pytest.raises(ResendTextError, match="found 2"):
        resendtext.one(two)


# ---- the transport -------------------------------------------------------

def _request(method, url, **kw):
    return httpx.Request(method, url, **kw)


async def _through(transport, request, answers):
    async def fake(client, provider, tool, arguments=None, **kw):
        return answers(provider, tool, arguments or {})
    transport._call = lambda tool, arguments: fake(
        "c", transport.provider, tool, arguments)
    return await transport.handle_async_request(request)


async def test_a_cloudflare_get_becomes_one_execute_call():
    seen = {}

    def answer(provider, tool, arguments):
        seen["tool"] = tool
        seen["code"] = arguments["code"]
        return {"failed": False, "result": {"success": True, "errors": [],
                                            "result": [], "status": 200}}

    reply = await _through(
        rest.CloudflareOverMCP("c"),
        _request("GET", "https://api.cloudflare.com/client/v4/zones?name=acme.example"),
        answer)

    assert seen["tool"] == "execute"
    # The base path is the adapter's business and not the API's.
    assert '"path": "/zones"' in seen["code"]
    assert '"query": {"name": "acme.example"}' in seen["code"]
    assert seen["code"].startswith("async () => cloudflare.request(")
    assert reply.status_code == 200


async def test_a_cloudflare_write_carries_its_body():
    seen = {}

    def answer(provider, tool, arguments):
        seen["code"] = arguments["code"]
        return {"failed": False, "result": {"success": True, "errors": [],
                                            "result": {"id": "r1"}, "status": 200}}

    body = {"type": "TXT", "name": "send.acme.example", "content": "v=spf1 ~all"}
    await _through(
        rest.CloudflareOverMCP("c"),
        _request("POST", "https://api.cloudflare.com/client/v4/zones/z1/dns_records",
                 json=body),
        answer)

    sent = json.loads(seen["code"][len("async () => cloudflare.request("):-1])
    assert sent["method"] == "POST"
    assert sent["path"] == "/zones/z1/dns_records"
    assert sent["body"] == body


async def test_the_request_is_data_inside_the_code_not_a_program():
    """Nothing the caller supplies gets to be JavaScript.

    A domain is attacker-adjacent input: it comes from a registry somebody
    typed into. It is serialised as ASCII JSON, so a quote or a newline in a
    record value stays a quote in a string.
    """
    seen = {}

    def answer(provider, tool, arguments):
        seen["code"] = arguments["code"]
        return {"failed": False, "result": {"success": True, "errors": [],
                                            "result": {}, "status": 200}}

    nasty = {"content": 'x") } ; (async () => { evil() //', "name": "señor.example"}
    await _through(
        rest.CloudflareOverMCP("c"),
        _request("POST", "https://api.cloudflare.com/client/v4/zones/z1/dns_records",
                 json=nasty),
        answer)

    code = seen["code"]
    # That this parses at all is the property: an unescaped quote would have
    # closed the string and the rest would be program text.
    sent = json.loads(code[len("async () => cloudflare.request("):-1])
    assert sent["body"] == nasty, "the payload did not survive the round trip"
    assert 'x") }' not in code, "a quote was left able to close the string"
    assert code.isascii(), "a non-ASCII code point ended up in a program"


async def test_a_cloudflare_failure_reads_as_cloudflare_saying_no():
    """`_ok` in the adapter raises on `success: false` and reads `errors`. A
    transport failure has to arrive in that shape or it surfaces as a
    KeyError somewhere unrelated."""
    def answer(provider, tool, arguments):
        return {"failed": True, "result": {"error": "the session expired"}}

    reply = await _through(
        rest.CloudflareOverMCP("c"),
        _request("GET", "https://api.cloudflare.com/client/v4/zones"), answer)

    assert reply.status_code == 502
    body = reply.json()
    assert body["success"] is False
    assert "session expired" in body["errors"][0]["message"]


async def test_resend_endpoints_map_to_resend_tools():
    calls = []

    def answer(provider, tool, arguments):
        calls.append((tool, arguments))
        if tool == "list-domains":
            return {"failed": False, "result": LIST}
        return {"failed": False, "result": GET}

    listed = await _through(rest.ResendOverMCP("c"),
                            _request("GET", "https://api.resend.com/domains"), answer)
    one = await _through(rest.ResendOverMCP("c"),
                         _request("GET", "https://api.resend.com/domains/d1"), answer)

    assert calls[0][0] == "list-domains"
    assert calls[1] == ("get-domain", {"id": "d1"})
    assert listed.json()["data"][0]["name"] == "acme.example"
    assert len(one.json()["records"]) == 3


async def test_creating_a_domain_passes_the_name_and_region():
    calls = []

    def answer(provider, tool, arguments):
        calls.append((tool, arguments))
        return {"failed": False, "result": GET}

    await _through(
        rest.ResendOverMCP("c"),
        _request("POST", "https://api.resend.com/domains",
                 json={"name": "acme.example", "region": "us-east-1"}), answer)

    assert calls == [("create-domain", {"name": "acme.example",
                                        "region": "us-east-1"})]


async def test_an_endpoint_with_no_tool_says_what_to_do_instead():
    """Resend publishes 104 tools and `mailplan` uses four of them. Anything
    else has to fail as a refusal an operator can act on, not as a parse of an
    empty answer."""
    def answer(provider, tool, arguments):
        raise AssertionError("nothing should have been called")

    reply = await _through(rest.ResendOverMCP("c"),
                           _request("POST", "https://api.resend.com/emails"), answer)

    assert reply.status_code == 501
    assert "--token" in reply.json()["message"]


async def test_prose_that_cannot_be_read_arrives_as_a_message():
    """`Resend._ok` turns a 4xx or 5xx into a ResendError carrying `message`,
    so the text that failed has to travel in that field."""
    def answer(provider, tool, arguments):
        # A domain that reads fine over a records section that does not, which
        # is the shape a reformat would take and the one that could otherwise
        # return a domain with nothing to publish.
        return {"failed": False, "result": [LIST[1], "DNS Records:\n\nsomething new\n"]}

    reply = await _through(rest.ResendOverMCP("c"),
                           _request("GET", "https://api.resend.com/domains/d1"), answer)

    assert reply.status_code == 502
    assert "most likely changed" in reply.json()["message"]


# ---- what counts as being able to reach a provider ----------------------
#
# `can_write` on the repair edge asked `container.has`, which knows only about
# pasted keys. A client connected by OAuth to both providers was refused a
# repair that would now have worked. An edge guarding the wrong condition is
# worse than no edge: it refuses quietly and looks right doing it.

class _Ring:
    def __init__(self, held):
        self.store = {(f"munim-mcp:{p}:tokens", "c_1"): '{"access_token": "t"}'
                      for p in held}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


class _Keys:
    def __init__(self, held=()):
        self.held = set(held)

    def get(self, client, provider):
        return "key" if provider in self.held else None

    def set(self, client, provider, secret):
        self.held.add(provider)


def test_a_pasted_key_is_a_route():
    from munim.container import Container

    box = Container("c_1", _Keys({"cloudflare"}), keyring=_Ring([]))
    assert box.can_reach("cloudflare") is True


def test_a_session_with_an_mcp_route_is_a_route():
    from munim.container import Container

    box = Container("c_1", _Keys(), keyring=_Ring(["cloudflare", "resend"]))
    assert box.can_reach("cloudflare") is True
    assert box.can_reach("resend") is True
    assert box.has("cloudflare") is False, "there is still no key, and that is the point"


def test_a_session_whose_rest_api_takes_it_is_a_route():
    """Vercel, measured: its REST API returns 200 to the session token, so the
    container borrows it and never reaches the transport."""
    from munim.container import Container

    box = Container("c_1", _Keys(), keyring=_Ring(["vercel"]))
    assert box.can_reach("vercel") is True


def test_nothing_at_all_is_not_a_route():
    from munim.container import Container

    box = Container("c_1", _Keys(), keyring=_Ring([]))
    assert box.can_reach("cloudflare") is False
    assert box.can_reach("resend") is False


def test_a_provider_with_no_rest_profile_is_not_a_route():
    """Linear runs an MCP server and has no entry in the auth table, so there
    is no REST API here to reach and saying otherwise would be a lie the
    repair edge acts on."""
    from munim.container import Container

    box = Container("c_1", _Keys(), keyring=_Ring(["linear"]))
    assert box.can_reach("linear") is False
