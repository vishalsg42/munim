"""The MCP surface holds two rules, and these fail the build if it stops.

The earlier version asserted "every tool but list_clients requires client",
which was already false for add_client and is false by definition for
find_across_clients. A rule that breaks the day a legitimate tool lands gets
widened at 11pm and quietly stops protecting anything. This asserts the rule
that actually matters instead: anything that *mutates* names its client.
"""

import pytest

from munim.server import MUTATING, build_server
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


async def test_the_only_cross_client_tool_is_read_only(tmp_path):
    """Read across, write within (D5). If a tool spans containers it must not
    be able to change anything."""
    server, _, _ = _server(tmp_path)
    names = {t.name for t in await server.list_tools()}
    assert "find_across_clients" in names
    assert "find_across_clients" not in MUTATING


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
    # deliberately has nowhere to say so.
    assert keychain.get("acme", "resend") == "re_super_secret"


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
    monkeypatch.setattr(checks, "run_reachability", lambda d: [])

    server, registry, keychain = _server(tmp_path)
    assert [c.name for c in registry.clients()] == ["acme"]

    await server.call_tool("check", {"target": "newclient.example"})
    assert "newclient.example" in [c.name for c in registry.clients()]


async def test_naming_the_same_domain_twice_does_not_duplicate_it(tmp_path, monkeypatch):
    from munim.checks import dns as checks
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    monkeypatch.setattr(checks, "run_reachability", lambda d: [])

    server, registry, keychain = _server(tmp_path)
    await server.call_tool("check", {"target": "newclient.example"})
    await server.call_tool("check", {"target": "newclient.example"})
    assert sum(1 for c in registry.clients() if c.name == "newclient.example") == 1


async def test_an_existing_client_is_found_by_its_domain(tmp_path, monkeypatch):
    """Saying the domain of a client you already added must reach that client,
    not create a second one under a different name."""
    from munim.checks import dns as checks
    monkeypatch.setattr(checks, "query", lambda *a, **k: [])
    monkeypatch.setattr(checks, "run_reachability", lambda d: [])

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
