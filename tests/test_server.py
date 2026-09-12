"""The MCP surface holds two rules, and these fail the build if it stops.

The earlier version asserted "every tool but list_clients requires client",
which was already false for add_client and is false by definition for
find_across_clients. A rule that breaks the day a legitimate tool lands gets
widened at 11pm and quietly stops protecting anything. This asserts the rule
that actually matters instead: anything that *mutates* names its client.
"""

import pytest

from munim.server import CROSS_CLIENT, MUTATING, build_server
from munim.registry import ClientRecord, Registry


def _server(tmp_path):
    class Keychain:
        def __init__(self): self.store = {}
        def get(self, c, p): return self.store.get((c, p))
        def set(self, c, p, s): self.store[(c, p)] = s

    registry = Registry(tmp_path / "registry.json")
    registry.add(ClientRecord(name="acme", domain="acme.example"))
    keychain = Keychain()
    return (build_server(backend=keychain, registry=registry,
                         runs_dir=tmp_path / "runs"), registry, keychain)


async def test_every_mutating_tool_names_its_client(tmp_path):
    server, _, _ = _server(tmp_path)
    tools = {t.name: t for t in await server.list_tools()}
    for name in MUTATING:
        assert name in tools, f"{name} is listed as mutating but is not registered"
        required = tools[name].inputSchema.get("required", [])
        assert "client" in required, f"{name} mutates without naming a client"


async def test_no_cross_client_tool_can_change_anything(tmp_path):
    """Read across, write within (D5). A tool that spans containers must not be
    able to mutate.

    Named after the set rather than after one tool. The earlier version
    asserted `find_across_clients` specifically, so when a second cross-client
    tool landed it kept passing without covering it: the exact failure this
    file's docstring warns about."""
    server, _, _ = _server(tmp_path)
    names = {t.name for t in await server.list_tools()}

    assert CROSS_CLIENT <= names, f"declared but not registered: {CROSS_CLIENT - names}"
    for tool in CROSS_CLIENT:
        assert tool not in MUTATING, f"{tool} spans clients and mutates"


async def test_a_new_across_tool_has_to_be_declared(tmp_path):
    """So the rule above cannot be escaped by adding a tool and not telling it."""
    server, _, _ = _server(tmp_path)
    looks_cross_client = {t.name for t in await server.list_tools()
                          if "across" in t.name or "all_clients" in t.name}
    undeclared = looks_cross_client - CROSS_CLIENT
    assert not undeclared, (
        f"{undeclared} span clients by their name but are not in CROSS_CLIENT, "
        "so nothing checks they are read-only")


async def test_no_tool_advertises_returning_a_credential(tmp_path):
    """D6: nothing hands a secret back across the MCP boundary."""
    server, _, _ = _server(tmp_path)
    for tool in await server.list_tools():
        blurb = (tool.description or "").lower()
        assert "returns the token" not in blurb
        assert "returns the credential" not in blurb


async def test_connect_provider_does_not_echo_the_secret(tmp_path):
    server, registry, keychain = _server(tmp_path)
    result = await server.call_tool(
        "connect_provider",
        {"client": "acme", "provider": "resend", "credential": "re_super_secret"},
    )
    rendered = str(result)
    assert "re_super_secret" not in rendered, "the credential came back out"
    # The keychain is the only record that a provider is connected; the registry
    # deliberately has nowhere to say so. Filed under the client's id, not the
    # name the call used: a credential filed under a label disappears the moment
    # the label changes.
    acme = registry.get("acme")
    assert keychain.get(acme.id, "resend") == "re_super_secret"
    assert keychain.get("acme", "resend") is None, "filed under the label"


async def test_an_unregistered_client_is_refused_before_a_secret_is_stored(tmp_path):
    server, _, _ = _server(tmp_path)
    with pytest.raises(Exception):
        await server.call_tool(
            "connect_provider",
            {"client": "acme-uk", "provider": "resend", "credential": "x"},
        )


async def test_client_status_reports_presence_not_values(tmp_path):
    server, _, _ = _server(tmp_path)
    await server.call_tool("connect_provider",
                           {"client": "acme", "provider": "resend", "credential": "re_x"})
    result = str(await server.call_tool("client_status", {"client": "acme"}))
    assert "resend" in result
    assert "re_x" not in result


async def test_naming_a_new_domain_registers_it_and_checks_it(tmp_path, monkeypatch):
    """No setup step. The first mention of a domain is enough, because a DNS
    lookup is public and there is nothing to protect on a read."""
    from munim.checks import dns as checks
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    # The async one, which is what `check` actually calls. Patching the
    # sync twin did nothing: `run_reachability_async` gathers the three
    # connection checks directly rather than going through it, so these
    # tests were opening real sockets and passing for the wrong reason.
    async def _no_reachability(domain):
        return []
    monkeypatch.setattr(checks, "run_reachability_async", _no_reachability)

    server, registry, keychain = _server(tmp_path)
    assert [c.name for c in registry.clients()] == ["acme"]

    await server.call_tool("check", {"target": "newclient.example"})
    assert "newclient.example" in [c.name for c in registry.clients()]


async def test_naming_the_same_domain_twice_does_not_duplicate_it(tmp_path, monkeypatch):
    from munim.checks import dns as checks
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    # The async one, which is what `check` actually calls. Patching the
    # sync twin did nothing: `run_reachability_async` gathers the three
    # connection checks directly rather than going through it, so these
    # tests were opening real sockets and passing for the wrong reason.
    async def _no_reachability(domain):
        return []
    monkeypatch.setattr(checks, "run_reachability_async", _no_reachability)

    server, registry, keychain = _server(tmp_path)
    await server.call_tool("check", {"target": "newclient.example"})
    await server.call_tool("check", {"target": "newclient.example"})
    assert sum(1 for c in registry.clients() if c.name == "newclient.example") == 1


async def test_an_existing_client_is_found_by_its_domain(tmp_path, monkeypatch):
    """Saying the domain of a client you already added must reach that client,
    not create a second one under a different name."""
    from munim.checks import dns as checks
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    # The async one, which is what `check` actually calls. Patching the
    # sync twin did nothing: `run_reachability_async` gathers the three
    # connection checks directly rather than going through it, so these
    # tests were opening real sockets and passing for the wrong reason.
    async def _no_reachability(domain):
        return []
    monkeypatch.setattr(checks, "run_reachability_async", _no_reachability)

    server, registry, keychain = _server(tmp_path)   # acme, domain acme.example
    await server.call_tool("check", {"target": "acme.example"})
    assert len(registry.clients()) == 1


async def test_an_unknown_name_that_is_not_a_domain_is_refused(tmp_path):
    """Auto-registering a typo'd client name would be how a wrong-tenant write
    starts. A bare name has to already exist."""
    server, _, _ = _server(tmp_path)
    with pytest.raises(Exception, match="not a domain"):
        await server.call_tool("check", {"target": "Acme Corp"})


async def test_reads_may_register_but_writes_may_not(tmp_path):
    """The safety property: connect_provider still refuses an unknown client
    even though check would have registered one (D5)."""
    server, registry, keychain = _server(tmp_path)
    with pytest.raises(Exception):
        await server.call_tool("connect_provider", {
            "client": "brand-new.example", "provider": "resend", "credential": "x"})
    assert "brand-new.example" not in [c.name for c in registry.clients()]


def test_the_readme_lists_every_tool_that_exists(tmp_path):
    """A reviewer read this repository and described it as an on-demand
    diagnostic tool, missing the per-client sessions entirely. That is the
    documentation failing, not the reader.

    So the tool surface is written down, and this fails when it drifts: a tool
    that exists and is undocumented is invisible, and one documented that does
    not exist is a claim the code cannot support.
    """
    import pathlib

    from munim.server import build_server

    root = pathlib.Path(__file__).parent.parent
    # The table moved out of the README when it was cut to what a first-time
    # reader needs. The rule is unchanged: the surface is written down
    # somewhere a reader will reach, and the README links to it.
    documented = (root / "docs" / "TOOLS.md").read_text()
    surface = {t.name for t in build_server()._tool_manager.list_tools()}

    undocumented = {n for n in surface if f"`{n}`" not in documented}
    assert not undocumented, f"tools nobody reading the docs would know about: {undocumented}"

    readme = (root / "README.md").read_text()
    assert "docs/TOOLS.md" in readme, (
        "the tool list is documented but the README does not point at it, so "
        "nobody arriving at the repository would find it")


async def test_applying_a_plan_made_for_another_client_is_refused(tmp_path, monkeypatch):
    """A plan carries the client it was made for. Applying it elsewhere is a
    write in the wrong account, which is exactly what D5 exists to stop."""
    import munim.agent.mailplan as mod

    monkeypatch.setattr(mod, "PLANS_DIR", tmp_path / "plans")
    mod._save(mod.MailPlan(plan_id="p9", client="somebody-else",
                           domain="other.example", changes=[]))

    server, _, _ = _server(tmp_path)
    with pytest.raises(Exception, match="different client|made for"):
        await server.call_tool("apply_mail_setup",
                               {"client": "acme", "plan_id": "p9"})


async def test_repair_is_reachable_from_the_tool_surface(tmp_path):
    """The whole point. The repair code was written, tested, and callable from
    nothing: an external reviewer found that before we did."""
    server, _, _ = _server(tmp_path)
    names = {t.name for t in await server.list_tools()}
    assert {"plan_mail_setup", "apply_mail_setup"} <= names


async def test_every_tool_that_changes_something_names_its_client(tmp_path):
    server, _, _ = _server(tmp_path)
    tools = {t.name: t for t in await server.list_tools()}
    for name in ("plan_mail_setup", "apply_mail_setup"):
        assert name in MUTATING, f"{name} writes and is not declared mutating"
        assert "client" in tools[name].inputSchema.get("required", []), name


async def test_a_mail_plan_over_the_session_needs_no_pasted_key(tmp_path, monkeypatch):
    """The reported confusion, end to end, and the shape of its fix.

    `client_status` said resend was connected and `plan_mail_setup` said there
    was no resend credential, in the same minute, both reading a different
    store. The first answer was a clearer refusal naming both stores. This is
    the second: the session is the connection, so the plan is built over it and
    there is nothing to paste.

    The provider answers here are the ones their live servers gave on
    2026-09-12, prose from Resend and the Cloudflare API's own JSON from
    Cloudflare's `execute`.
    """
    import json

    from munim.registry import ClientRecord, Registry
    from munim.remote import rest
    from munim.server import build_server

    class Ring:
        def __init__(self, store): self.store = store
        def get_password(self, service, account):
            return self.store.get((service, account))
        def set_password(self, service, account, secret):
            self.store[(service, account)] = secret
        def delete_password(self, service, account):
            self.store.pop((service, account), None)

    class Keys:
        def __init__(self, ring): self._ring = ring
        def get(self, client, provider):
            return self._ring.get_password(f"munim:{provider}", client)
        def set(self, client, provider, secret):
            self._ring.set_password(f"munim:{provider}", client, secret)

    DOMAIN_BLOCK = ("Name: acme.example\nID: d1\nStatus: verified\n"
                    "Region: us-east-1\nSending: enabled")
    RECORD_BLOCK = (
        "DNS Records:\n\nDKIM (TXT):\n  Name: resend._domainkey\n"
        "  Value: p=MIGfMA0GCSqGSIb3DQEB\n  TTL: Auto\n  Status: verified\n\n"
        "SPF (MX):\n  Name: send\n  Value: feedback-smtp.us-east-1.amazonses.com\n"
        "  TTL: Auto\n  Status: verified\n  Priority: 10\n\n"
        "SPF (TXT):\n  Name: send\n  Value: v=spf1 include:amazonses.com ~all\n"
        "  TTL: Auto\n  Status: verified")

    asked = []

    async def fake_call(client, provider, tool, arguments=None, **kw):
        asked.append((provider, tool))
        if provider == "resend" and tool == "list-domains":
            return {"failed": False, "result": ["Found 1 domain:", DOMAIN_BLOCK]}
        if provider == "resend" and tool == "get-domain":
            return {"failed": False, "result": [DOMAIN_BLOCK, RECORD_BLOCK]}
        if provider == "cloudflare" and tool == "execute":
            code = (arguments or {}).get("code", "")
            if "/zones/" in code and "dns_records" in code:
                result = []
            else:
                result = [{"id": "z1", "name": "acme.example"}]
            return {"failed": False,
                    "result": {"success": True, "errors": [], "messages": [],
                               "result": result, "status": 200}}
        raise AssertionError(f"unexpected call: {provider}.{tool}")

    monkeypatch.setattr(rest, "call_tool", fake_call)

    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme Ltd", domain="acme.example"))
    record = reg.clients()[0]

    # An MCP session for both, and no pasted key anywhere: exactly the shape
    # that used to refuse.
    ring = Ring({("munim-mcp:resend:tokens", record.id): '{"a": 1}',
                 ("munim-mcp:cloudflare:tokens", record.id): '{"a": 1}'})
    server = build_server(backend=Keys(ring), registry=reg,
                          runs_dir=tmp_path / "runs",
                          reports_dir=tmp_path / "reports", keyring=ring)

    result = await server.call_tool(
        "plan_mail_setup", {"client": "Acme Ltd", "domain": "acme.example"})
    blocks = result[0] if isinstance(result, tuple) else result
    shaped = json.loads((blocks[0] if isinstance(blocks, list) else blocks).text)

    assert "error" not in shaped, shaped
    assert shaped["changes"], "a plan with nothing in it is not a plan"
    # The DKIM key came out of prose and has to arrive intact.
    dkim = [c for c in shaped["changes"] if c["purpose"] == "DKIM"]
    assert dkim and dkim[0]["content"] == "p=MIGfMA0GCSqGSIb3DQEB"
    assert ("resend", "get-domain") in asked, "the records were never read back"
    assert ("cloudflare", "execute") in asked, "Cloudflare was not reached"


# ---- links into the control room ----------------------------------------
#
# The room is a separate process nobody starts for you, so most tool calls
# happen with nothing listening. `check` still returned a `report` URL and `fix`
# still returned `watch`, both pointing at a port with nothing behind it.

async def test_check_offers_no_room_links_when_the_room_is_down(tmp_path, monkeypatch):
    from munim.checks import dns as checks
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])

    async def _no_reachability(domain):
        return []
    monkeypatch.setattr(checks, "run_reachability_async", _no_reachability)
    monkeypatch.setattr("munim.room.link.is_up", lambda timeout=0.2: False)

    server, _, _ = _server(tmp_path)
    result = await server.call_tool("check", {"target": "acme.example"})
    body = result[1] if isinstance(result, tuple) else result

    assert "127.0.0.1" not in str(body), "offered a link to a room that is down"
    # The file is written whatever the room is doing, and this is the line that
    # has to stay true for the links to be droppable at all.
    assert "report_file" in str(body)


async def test_check_offers_them_when_it_is_up(tmp_path, monkeypatch):
    from munim.checks import dns as checks
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])

    async def _no_reachability(domain):
        return []
    monkeypatch.setattr(checks, "run_reachability_async", _no_reachability)
    monkeypatch.setattr("munim.room.link.is_up", lambda timeout=0.2: True)

    server, _, _ = _server(tmp_path)
    result = await server.call_tool("check", {"target": "acme.example"})

    assert "/reports/" in str(result)


def test_no_tool_builds_the_room_url_by_hand():
    """One place knows where the room is.

    Three tool results built the URL inline, so the port that `munim-room
    --port` and $MUNIM_ROOM_PORT actually move was hardcoded in three places
    that could not move with it.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "munim"
    allowed = {root / "room" / "link.py", root / "room" / "server.py",
               root / "cli.py"}
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path not in allowed and "127.0.0.1:8977" in path.read_text()
    ]
    assert offenders == [], f"hardcoded room URL in: {', '.join(offenders)}"
