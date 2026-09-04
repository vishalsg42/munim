"""An authenticated MCP session for one client with one provider.

This is the alternative to writing an adapter per provider: the provider
already runs an MCP server, and every one of them registers a client on demand,
so a session per client needs no application registered by hand and no secret
in this repository (D25).

The multi-account property is not engineered here. It falls out of registering
once per client: two clients are two applications as far as the provider is
concerned, so there is nothing shared to clobber. What this module does is make
sure the registration and the tokens are stored per client, and refuse to open
a session for a client that is not registered.
"""

import asyncio
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientMetadata

from munim.connect.callback import redirect_uri, serve_until_callback
from munim.remote.servers import SERVERS, server_for
from munim.remote.storage import KeychainTokenStorage


class NoRemoteServer(Exception):
    """This provider runs no MCP server, so there is nothing to connect to."""


def _metadata(client: str) -> OAuthClientMetadata:
    """What Munim tells a provider about itself at registration.

    The client name carries the operator's name for the client, because it is
    what appears on the consent screen and on the provider's list of authorised
    applications. Connecting the wrong account is the one failure a person has
    to catch, and this is where they can see it.
    """
    return OAuthClientMetadata(
        client_name=f"Munim ({client})",
        redirect_uris=[redirect_uri()],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


def auth_for(client: str, provider: str, *, backend=None,
             on_url=None) -> OAuthClientProvider:
    """The OAuth client for one (client, provider), storing to the keychain."""
    server = server_for(provider)
    if server is None:
        raise NoRemoteServer(
            f"{provider} runs no MCP server, so there is no session to open. "
            "Providers that do: " + ", ".join(sorted(SERVERS))
        )

    storage = (KeychainTokenStorage(client, provider, backend) if backend
               else KeychainTokenStorage(client, provider))

    async def redirect(url: str) -> None:
        if on_url is not None:
            await on_url(url)
        else:
            import webbrowser
            print(f"Sign in as {client}'s {provider} account:\n{url}", flush=True)
            webbrowser.open(url)

    async def callback() -> tuple[str, str | None]:
        answer = await asyncio.to_thread(serve_until_callback)
        return answer.get("code", ""), answer.get("state")

    if not server.public_client:
        # Registration issues the secret; it is stored beside the tokens and
        # never becomes a value here. Only the auth method differs.
        meta = _metadata(client).model_copy(
            update={"token_endpoint_auth_method": "client_secret_post"})
    else:
        meta = _metadata(client)

    return OAuthClientProvider(
        server_url=server.url,
        client_metadata=meta,
        storage=storage,
        redirect_handler=redirect,
        callback_handler=callback,
    )


@asynccontextmanager
async def session_for(client: str, provider: str, *, backend=None, on_url=None):
    """Open one client's session with one provider's MCP server."""
    server = server_for(provider)
    if server is None:
        raise NoRemoteServer(f"{provider} runs no MCP server")

    auth = auth_for(client, provider, backend=backend, on_url=on_url)
    async with streamablehttp_client(server.url, auth=auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def tools_for(client: str, provider: str, **kwargs) -> list[str]:
    """What this client's account can be asked to do. Read-only."""
    async with session_for(client, provider, **kwargs) as session:
        return [t.name for t in (await session.list_tools()).tools]
