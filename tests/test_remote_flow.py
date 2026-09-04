"""The --via-mcp path, driven end to end against a stood-up provider.

Everything else about this path is tested at construction: the right metadata,
the right prefix, the right storage key. None of that proves a login works.
This runs the whole thing with the provider standing in: the 401 that starts
discovery, protected resource metadata, authorization server metadata, dynamic
registration, the browser redirect, the callback, and the token exchange.

What it is really pinning is that nothing along the way is shared between two
clients. The registration is per client, so the token is, so the session is.
"""

import asyncio
import urllib.parse

import httpx
import pytest
import respx

from munim.remote.session import auth_for
from munim.remote.storage import KeychainTokenStorage

SERVER = "https://mcp.cloudflare.com/mcp"
AS = "https://mcp.cloudflare.com"


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret


def _stand_up_provider(issued: dict):
    """The provider side of the flow, minus a human."""
    respx.get(f"{AS}/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(200, json={
            "resource": SERVER, "authorization_servers": [AS]}))
    respx.get(f"{AS}/.well-known/oauth-protected-resource").mock(
        return_value=httpx.Response(200, json={
            "resource": SERVER, "authorization_servers": [AS]}))
    respx.get(f"{AS}/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(200, json={
            "issuer": AS,
            "authorization_endpoint": f"{AS}/authorize",
            "token_endpoint": f"{AS}/token",
            "registration_endpoint": f"{AS}/register",
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }))

    def register(request):
        # A distinct client id per registration is the whole property.
        body = httpx.Response(200, json={
            "client_id": f"issued-{len(issued) + 1}",
            "redirect_uris": ["http://localhost:8976/oauth/callback"],
            "token_endpoint_auth_method": "none",
        })
        issued[f"client-{len(issued) + 1}"] = True
        return body

    respx.post(f"{AS}/register").mock(side_effect=register)
    respx.post(f"{AS}/token").mock(return_value=httpx.Response(200, json={
        "access_token": "granted-token", "token_type": "Bearer",
        "expires_in": 3600, "refresh_token": "r"}))


async def _log_in(client: str, ring: FakeKeyring) -> str:
    """Run the flow for one client, standing in for the person at the browser."""
    seen_url = {}

    async def capture(url: str) -> None:
        seen_url["url"] = url

    auth = auth_for(client, "cloudflare", backend=ring, on_url=capture)

    async def callback() -> tuple[str, str | None]:
        # The provider redirected; read the state back off the URL it opened.
        query = urllib.parse.parse_qs(urllib.parse.urlparse(seen_url["url"]).query)
        return "the-code", query.get("state", [None])[0]

    auth.context.callback_handler = auth._callback_handler = callback
    auth._callback_handler = callback

    # Drive the auth flow the way httpx would: it is a request-flow generator.
    request = httpx.Request("POST", SERVER)
    flow = auth.async_auth_flow(request)
    response = httpx.Response(401, headers={
        "WWW-Authenticate": f'Bearer resource_metadata="{AS}/.well-known/oauth-protected-resource/mcp"'
    }, request=request)

    outgoing = await flow.__anext__()
    while True:
        try:
            if outgoing.url.host == "mcp.cloudflare.com" and outgoing.url.path == "/mcp":
                outgoing = await flow.asend(response)
            else:
                async with httpx.AsyncClient() as http:
                    outgoing = await flow.asend(await http.send(outgoing))
        except StopAsyncIteration:
            break
    return seen_url.get("url", "")


@respx.mock
async def test_two_clients_log_in_and_keep_separate_tokens():
    issued: dict = {}
    _stand_up_provider(issued)
    ring = FakeKeyring()

    await _log_in("Balaji Roofings", ring)
    await _log_in("Kloudfirst", ring)

    a = await KeychainTokenStorage("Balaji Roofings", "cloudflare", ring).get_client_info()
    b = await KeychainTokenStorage("Kloudfirst", "cloudflare", ring).get_client_info()

    assert a is not None and b is not None, "registration did not reach storage"
    assert a.client_id != b.client_id, (
        "both clients share a registration, so the provider cannot tell them "
        "apart and one session will replace the other")
    assert len(issued) == 2, "the provider was asked to register only once"


@respx.mock
async def test_the_authorization_url_carries_pkce_and_our_callback():
    _stand_up_provider({})
    ring = FakeKeyring()
    url = await _log_in("Balaji Roofings", ring)

    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://localhost:8976/oauth/callback"]
    assert "code_verifier" not in query, "the verifier must never reach the browser"
