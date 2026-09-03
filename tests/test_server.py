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
    return build_server(backend=Keychain(), registry=registry,
                        runs_dir=tmp_path / "runs"), registry


async def test_every_mutating_tool_names_its_client(tmp_path):
    server, _ = _server(tmp_path)
    tools = {t.name: t for t in await server.list_tools()}
    for name in MUTATING:
        assert name in tools, f"{name} is listed as mutating but is not registered"
        required = tools[name].inputSchema.get("required", [])
        assert "client" in required, f"{name} mutates without naming a client"


async def test_the_only_cross_client_tool_is_read_only(tmp_path):
    """Read across, write within (D5). If a tool spans containers it must not
    be able to change anything."""
    server, _ = _server(tmp_path)
    names = {t.name for t in await server.list_tools()}
    assert "find_across_clients" in names
    assert "find_across_clients" not in MUTATING


async def test_no_tool_advertises_returning_a_credential(tmp_path):
    """D6: nothing hands a secret back across the MCP boundary."""
    server, _ = _server(tmp_path)
    for tool in await server.list_tools():
        blurb = (tool.description or "").lower()
        assert "returns the token" not in blurb
        assert "returns the credential" not in blurb


async def test_connect_provider_does_not_echo_the_secret(tmp_path):
    server, registry = _server(tmp_path)
    result = await server.call_tool(
        "connect_provider",
        {"client": "acme", "provider": "resend", "credential": "re_super_secret"},
    )
    rendered = str(result)
    assert "re_super_secret" not in rendered, "the credential came back out"
    assert "resend" in registry.get("acme").providers


async def test_an_unregistered_client_is_refused_before_a_secret_is_stored(tmp_path):
    server, _ = _server(tmp_path)
    with pytest.raises(Exception):
        await server.call_tool(
            "connect_provider",
            {"client": "acme-uk", "provider": "resend", "credential": "x"},
        )


async def test_client_status_reports_presence_not_values(tmp_path):
    server, _ = _server(tmp_path)
    await server.call_tool("connect_provider",
                           {"client": "acme", "provider": "resend", "credential": "re_x"})
    result = str(await server.call_tool("client_status", {"client": "acme"}))
    assert "resend" in result
    assert "re_x" not in result
