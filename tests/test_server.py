from mcpc.server import build_server


async def test_server_exposes_list_clients():
    server = build_server()
    names = {t.name for t in await server.list_tools()}
    assert "list_clients" in names


async def test_every_provider_tool_requires_an_explicit_client():
    """No ambient 'current client'. An implicit selection is how the wrong
    account gets written to (docs/DECISIONS.md D5)."""
    server = build_server()
    for tool in await server.list_tools():
        if tool.name == "list_clients":
            continue
        params = tool.inputSchema.get("properties", {})
        assert "client" in params, f"{tool.name} does not take an explicit client"
        assert "client" in tool.inputSchema.get("required", []), (
            f"{tool.name} does not require client"
        )
