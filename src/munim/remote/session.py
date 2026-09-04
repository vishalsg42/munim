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
import urllib.parse
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientMetadata

from munim.connect.callback import redirect_uri, serve_until_callback
from munim.remote.servers import SERVERS, server_for
from munim.remote.storage import (
    CONFIDENTIAL_AUTH_METHOD,
    KeychainTokenStorage,
)


# What OAuthClientProvider allows for the whole flow. The listener matches it
# rather than undercutting it.
LOGIN_TIMEOUT = 300.0


class NeedsLogin(Exception):
    """Opening this session would mean authorising, and the caller said no.

    A read-only script that reaches for a browser is not read-only. The
    cross-account probe did exactly that once a Cloudflare token expired: it
    opened a browser, printed an authorize URL, and blocked for five minutes
    waiting for a callback that nobody was there to complete. Anything running
    unattended wants a legible refusal instead.
    """


class NoRemoteServer(Exception):
    """This provider runs no MCP server, so there is nothing to connect to."""


def _metadata(client: str) -> OAuthClientMetadata:
    """What Munim tells a provider about itself at registration.

    The client name carries the operator's name for the client, because it is
    what appears on the consent screen and on the provider's list of authorised
    applications. Connecting the wrong account is the one failure a person has
    to catch, and this is where they can see it.

    No scope is set here, and setting one would be theatre. The MCP spec
    defines a Scope Selection Strategy and the SDK implements it: the scope
    comes from the WWW-Authenticate challenge, else the resource's
    scopes_supported, else the authorization server's, and whatever the client
    put in its metadata is overwritten before the authorize request is built.

    So on this route the provider chooses. RemoteServer.scopes records what
    Munim would ask for and is honoured on the application route, which builds
    its own authorize URL.
    """
    return OAuthClientMetadata(
        client_name=f"Munim ({client})",
        redirect_uris=[redirect_uri()],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


def _registered_application(provider: str) -> tuple[str, str] | None:
    """A client id and secret the operator registered themselves.

    Some authorization servers will not issue a client on demand. Every Google
    one is like this: accounts.google.com advertises no registration endpoint
    and requires a secret, which is why a coding agent's Gmail connector works
    without setup only because the agent itself is a registered application.

    Munim is a client too, so for those providers somebody has to register one.
    Read from the environment rather than shipped, so nothing here carries a
    credential that belongs to a provider account.
    """
    import os

    prefix = provider.upper().replace("-", "_")
    client_id = os.environ.get(f"{prefix}_OAUTH_CLIENT_ID")
    if not client_id:
        return None
    return client_id, os.environ.get(f"{prefix}_OAUTH_CLIENT_SECRET", "")


def auth_for(client: str, provider: str, *, backend=None,
             on_url=None, label: str | None = None,
             allow_login: bool = True) -> OAuthClientProvider:
    """The OAuth client for one (client, provider), storing to the keychain.

    `client` is the identity credentials are filed under, so it is an id.
    `label` is what a person should read: it goes on the consent screen and in
    the sign-in prompt. They were the same string until the id became the
    storage key, at which point every human-facing line started rendering
    "Munim (c_6d7900c3e0e99c16)" and the consent screen stopped saying which
    client was being authorised, which is the one thing it is there to say.
    """
    label = label or client
    server = server_for(provider)
    if server is None:
        raise NoRemoteServer(
            f"{provider} runs no MCP server, so there is no session to open. "
            "Providers that do: " + ", ".join(sorted(SERVERS))
        )

    storage = (KeychainTokenStorage(client, provider, backend) if backend
               else KeychainTokenStorage(client, provider))

    # The state the SDK put on the authorization request. The listener waits for
    # a callback carrying this one and ignores the rest: anything can reach a
    # localhost port, and accepting the first arrival is how a login fails with
    # "state parameter mismatch" on somebody else's redirect.
    pending: dict[str, str | None] = {}

    async def redirect(url: str) -> None:
        if not allow_login:
            # Raised before the browser opens, not after: the point is that
            # nothing appears on screen and nothing waits.
            raise NeedsLogin(
                f"{client} has no usable {provider} session, and opening one "
                f"means signing in. Run: munim connect \"{label or client}\" "
                f"{provider}"
            )
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        pending["state"] = query.get("state", [None])[0]
        if on_url is not None:
            await on_url(url)
        else:
            import webbrowser
            # The caller may not have a name yet: connecting without one uses a
            # provisional key until the provider says which account it was, and
            # printing that key reads as gibberish.
            whose = f"{label}'s " if not label.startswith("…") else ""
            print(f"Sign in to the {whose}{provider} account:\n{url}", flush=True)
            webbrowser.open(url)

    async def callback() -> tuple[str, str | None]:
        # As long as the SDK is prepared to wait, and no longer. The listener
        # defaulted to 180s while OAuthClientProvider allows 300, so a sign-in
        # that involved actually logging in - a fresh account, a second factor -
        # ran out here first and reported no callback while the browser was
        # still on the provider's login page.
        answer = await asyncio.to_thread(serve_until_callback,
                                         timeout=LOGIN_TIMEOUT,
                                         expect_state=pending.get("state"))
        if "error" in answer:
            # Ours, and a refusal. Saying so beats waiting out the deadline and
            # reporting that no callback arrived when one did.
            raise RuntimeError(
                f"{provider} refused the login: "
                f"{answer.get('error_description') or answer['error']}"
            )
        return answer.get("code", ""), answer.get("state")

    if not server.public_client:
        # Registration issues the secret; it is stored beside the tokens and
        # never becomes a value here. Only the auth method differs.
        meta = _metadata(label).model_copy(
            update={"token_endpoint_auth_method": CONFIDENTIAL_AUTH_METHOD})
    else:
        meta = _metadata(label)

    if server.auth == "app":
        # Nothing to register against, so an application has to already exist.
        # Seeding storage with it is what makes the SDK use it instead of
        # trying to register and failing at an endpoint that is not there.
        registered = _registered_application(provider)
        if registered is None:
            raise NoRemoteServer(
                f"{provider} will not register a client on demand, so it needs "
                f"an application registered by hand"
                + (f" at {server.register_at}" if server.register_at else "")
                + f", then {provider.upper()}_OAUTH_CLIENT_ID and "
                f"{provider.upper()}_OAUTH_CLIENT_SECRET in .env. "
                f"`munim servers` says which providers need this.")
        storage.seed_client_info(*registered, redirect_uri())

    return OAuthClientProvider(
        server_url=server.url,
        client_metadata=meta,
        storage=storage,
        redirect_handler=redirect,
        callback_handler=callback,
    )


def endpoint_for(client: str, provider: str, backend=None) -> str:
    """Where this client's server is.

    Usually the provider's one address for everybody. For a provider whose URL
    carries the credential, it is per client and comes from the keychain, which
    is also why it is not in servers.json: that file lists servers, and this is
    one client's secret.
    """
    server = server_for(provider)
    if server is None:
        raise NoRemoteServer(f"{provider} runs no MCP server")
    if server.auth != "url":
        return server.url

    stored = KeychainTokenStorage(client, provider, backend).endpoint()
    if not stored:
        raise NoRemoteServer(
            f"{provider} identifies a client by their own endpoint URL, and "
            f"none is stored for this one. Add it with: "
            f"munim connect \"<client>\" {provider} --url <their URL>")
    return stored


class WrongAccount(Exception):
    """The session opened, and it is not the account this client was bound to."""


async def _verify_account(session, client: str, provider: str, backend=None) -> None:
    """Refuse a session that has drifted to another account.

    Access tokens expire, and a refresh that fails becomes a fresh
    authorization. That authorization is decided by whoever the browser is
    signed in to, not by the client record, so a client can be silently
    rebound to a different account: it happened here, between one probe and the
    next, and nothing noticed because the client id and the stored name were
    both still right.

    Checked on every session rather than at connect time, because connect time
    is not when it goes wrong.
    """
    from munim.remote.identity import identity_of

    store = KeychainTokenStorage(client, provider, backend)
    expected = store.account()
    if not expected:
        # Never recorded, so there is nothing to compare against. Record it now
        # so the next session has something.
        found = await identity_of(session, provider)
        if found:
            store.remember_account(found)
        return

    found = await identity_of(session, provider)
    if found and found != expected:
        raise WrongAccount(
            f"This session is authenticated as {found!r}, and this client was "
            f"connected as {expected!r}. A token was refreshed against whichever "
            f"account the browser was signed in to. Nothing was read or "
            f"changed. Reconnect it: munim connect <client> {provider}"
        )


@asynccontextmanager
async def session_for(client: str, provider: str, *, backend=None, on_url=None,
                      verify: bool = True, label: str | None = None,
                      allow_login: bool = True):
    """Open one client's session with one provider's MCP server."""
    server = server_for(provider)
    if server is None:
        raise NoRemoteServer(f"{provider} runs no MCP server")

    url = endpoint_for(client, provider, backend)

    if server.auth == "url":
        # The address is the credential, so there is nothing to authenticate
        # with and nothing to open a browser for.
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return  # a url-authenticated server has no account to drift

    auth = auth_for(client, provider, backend=backend, on_url=on_url,
                    label=label, allow_login=allow_login)
    try:
        async with streamablehttp_client(url, auth=auth) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if verify:
                    await _verify_account(session, client, provider, backend)
                yield session
    except BaseExceptionGroup as group:
        # The transport runs inside an anyio task group, so anything raised in
        # here comes back wrapped. A caller cannot catch these through a group,
        # and they are the two a caller most needs: the wrong account, and a
        # session that would have to prompt for a login.
        surfaced = [e for e in _flatten(group)
                    if isinstance(e, (WrongAccount, NeedsLogin))]
        if surfaced:
            raise surfaced[0] from None
        raise


def _flatten(error: BaseException):
    if isinstance(error, BaseExceptionGroup):
        for inner in error.exceptions:
            yield from _flatten(inner)
    else:
        yield error


async def tools_for(client: str, provider: str, **kwargs) -> list[str]:
    """What this client's account can be asked to do. Read-only."""
    async with session_for(client, provider, **kwargs) as session:
        return [t.name for t in (await session.list_tools()).tools]


async def connect_and_identify(client: str, provider: str, *,
                               label: str | None = None,
                               **kwargs) -> tuple[list[str], str | None]:
    """Open the session and ask the provider which account it belongs to.

    The identity is the point. The operator types a name; the provider knows
    what was actually authorised, and showing them side by side is what turns
    "check it is the right account" from advice into something checkable.
    """
    from munim.remote.identity import identity_of

    # verify=False on purpose. Connecting is how an operator says which account
    # this client uses, so it is the one moment the answer is allowed to
    # change: a guard that refuses here would block the only remedy for having
    # been bound to the wrong one. The caller records what it landed on, which
    # is what every later session is then checked against.
    async with session_for(client, provider, verify=False, label=label,
                           **kwargs) as session:
        tools = [t.name for t in (await session.list_tools()).tools]
        return tools, await identity_of(session, provider)
