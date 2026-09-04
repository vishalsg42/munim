"""Point Munim at any MCP server and work out what it needs.

Three providers are not a product. The product is a session per client against
something that speaks MCP, and an operator with their own server should be able
to add it by giving a URL. What a URL cannot say is how it wants to be
authenticated, and probing found three different answers in one afternoon:
a server that registers clients on demand, one that requires an application
registered by hand, and one whose URL is itself the credential.
"""

import httpx
import pytest
import respx

from munim.remote.discover import NotAnMcpServer, probe

URL = "https://mcp.example.test/mcp"


def _init_ok(**headers):
    return httpx.Response(200, headers=headers, json={
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": "2026-07-28", "capabilities": {},
                   "serverInfo": {"name": "x", "version": "1"}}})


def _challenge(meta=f"https://mcp.example.test/.well-known/oauth-protected-resource"):
    return httpx.Response(401, headers={
        "WWW-Authenticate": f'Bearer resource_metadata="{meta}"'})


def _as_metadata(**extra):
    return httpx.Response(200, json={
        "issuer": "https://auth.example.test",
        "authorization_endpoint": "https://auth.example.test/authorize",
        "token_endpoint": "https://auth.example.test/token", **extra})


@respx.mock
async def test_a_server_that_registers_clients_needs_nothing_set_up():
    respx.post(URL).mock(return_value=_challenge())
    respx.get("https://mcp.example.test/.well-known/oauth-protected-resource").mock(
        return_value=httpx.Response(200, json={
            "resource": URL, "authorization_servers": ["https://auth.example.test"]}))
    respx.get("https://auth.example.test/.well-known/oauth-authorization-server").mock(
        return_value=_as_metadata(
            registration_endpoint="https://auth.example.test/register",
            token_endpoint_auth_methods_supported=["none"]))

    found = await probe(URL, "acme")
    assert found.auth == "registers"
    assert found.public_client is True
    assert found.ready is True


@respx.mock
async def test_a_server_with_no_registration_endpoint_needs_an_application():
    respx.post(URL).mock(return_value=_challenge())
    respx.get("https://mcp.example.test/.well-known/oauth-protected-resource").mock(
        return_value=httpx.Response(200, json={
            "resource": URL, "authorization_servers": ["https://auth.example.test"]}))
    respx.get("https://auth.example.test/.well-known/oauth-authorization-server").mock(
        return_value=_as_metadata(
            token_endpoint_auth_methods_supported=["client_secret_post"]))

    found = await probe(URL, "acme")
    assert found.auth == "app"
    assert found.ready is False
    assert found.register_at == "https://auth.example.test"


@respx.mock
async def test_a_server_that_answers_without_credentials_is_url_authenticated():
    """Zoho's shape: the endpoint path carries the credential, so there is no
    challenge to read and the URL is the thing to keep secret."""
    respx.post(URL).mock(side_effect=[
        _init_ok(),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 2,
                                  "result": {"tools": [{"name": "list"}]}}),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 3, "result": {}}),
    ])
    found = await probe(URL, "zoho-ish")
    assert found.auth == "url"


@respx.mock
async def test_something_that_is_not_an_mcp_server_says_so():
    respx.post(URL).mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(NotAnMcpServer, match="probably not an MCP server"):
        await probe(URL, "acme")


@respx.mock
async def test_a_url_that_does_not_answer_says_so():
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(NotAnMcpServer, match="did not answer"):
        await probe(URL, "acme")


def test_a_server_the_operator_added_wins_over_a_built_in(tmp_path, monkeypatch):
    """Someone who points a name at their own server means it."""
    import munim.remote.servers as mod

    monkeypatch.setattr(mod, "USER_SERVERS", tmp_path / "servers.json")
    mod.remember(mod.RemoteServer(provider="cloudflare", url="https://mine.test/mcp",
                                  public_client=True, auth="registers", note="mine"))
    assert mod.all_servers()["cloudflare"].url == "https://mine.test/mcp"


def test_an_unreadable_server_file_does_not_take_the_built_ins_down(tmp_path, monkeypatch):
    import munim.remote.servers as mod

    path = tmp_path / "servers.json"
    path.write_text("{ this is not json")
    monkeypatch.setattr(mod, "USER_SERVERS", path)
    assert set(mod.all_servers()) >= {"cloudflare", "vercel", "resend"}
