"""`munim connect`: log in to a provider as one client.

Kept out of the MCP server on purpose. OAuth needs a browser and a callback
listener, which a stdio subprocess spawned by a coding agent has no business
opening. Running it as its own command also means the secret never passes
through the agent's context: the browser talks to the provider, the provider
talks to the callback, and the token goes straight to the keychain.
"""

import argparse
import os
import sys

from munim.connect.oauth import (PROVIDERS, SHIPPED_CLIENT_IDS,
                                 OAuthConnector)
from munim.connect.token import TokenConnector
from munim.container import KeychainBackend
from munim.env import load as load_env
from munim.registry import ClientRecord, Registry, UnknownClient

REGISTRY = None  # resolved at call time so tests can point it elsewhere


def _registry() -> Registry:
    from pathlib import Path
    return REGISTRY or Registry(Path.home() / ".munim" / "registry.json")


def _client_id(provider: str) -> tuple[str, str]:
    """OAuth app credentials for a provider.

    These identify *this tool* to the provider, not the client: one
    registration serves every client the operator connects. Where the provider
    supports public PKCE clients, Munim ships an id so nobody has to register
    anything, and the environment overrides it for anyone who would rather use
    their own.
    """
    prefix = provider.upper()
    client_id = (os.environ.get(f"{prefix}_OAUTH_CLIENT_ID")
                 or SHIPPED_CLIENT_IDS.get(provider, ""))
    return client_id, os.environ.get(f"{prefix}_OAUTH_CLIENT_SECRET", "")


PROVISIONAL = "…connecting"


def connect_via_mcp(client: str | None, provider: str) -> int:
    """Connect through the provider's own MCP server.

    Nothing is registered by hand. The provider's authorization server issues a
    client on demand, so this works for anyone who installs Munim, and it is
    per client: each one is a separate registration, which is why two accounts
    with the same provider do not clobber each other (D25).
    """
    import asyncio

    from munim.remote.servers import server_for
    from munim.remote.session import NoRemoteServer, connect_and_identify

    server = server_for(provider)
    if server is None:
        print(f"{provider} runs no MCP server. Use `munim connect {client} "
              f"{provider} --via-app`.", file=sys.stderr)
        return 2

    # Without a name, authorise first and ask the provider who that was. The
    # session has to be stored somewhere while that happens, so it starts under
    # a provisional name and moves once the answer comes back. Naming a client
    # up front was always a guess checked by eye; this makes the account itself
    # the source of the name.
    naming = client is None
    working_name = client or PROVISIONAL

    if naming:
        print(f"Opening your browser. Sign in to the {provider} account you "
              f"want to add, and the client will be named after it.",
              file=sys.stderr)
    else:
        print(f"Opening your browser to log in to {provider} as {client}.",
              file=sys.stderr)
        print(f"The consent screen will name the application "
              f"\"Munim ({client})\".", file=sys.stderr)

    try:
        tools, account = asyncio.run(connect_and_identify(working_name, provider))
    except NoRemoteServer as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if naming:
        if not account:
            print(f"{provider} did not say which account was authorised, so "
                  f"there is nothing to name this after. Run it again with a "
                  f"name: munim connect \"<client>\" {provider}",
                  file=sys.stderr)
            return 2
        from munim.remote.storage import KeychainTokenStorage
        KeychainTokenStorage(PROVISIONAL, provider).move_to(account)
        client = account
        registry = _registry()
        try:
            registry.get(client)
        except UnknownClient:
            registry.add(ClientRecord(name=client))

    # The account the provider says was authorised, beside the name it was
    # stored under. This is the only moment the two can be compared, and until
    # now nothing compared them: a typo at the prompt stored a real token under
    # a name that had nothing to do with it.
    where = f"\n  account: {account}" if account and not naming else ""
    print(f"Connected {provider} for {client}: {len(tools)} tools.{where}",
          file=sys.stderr)
    if account and not naming:
        print("  If that is not the right account, run the command again and "
              "pick the other one at the consent screen.", file=sys.stderr)
    if naming:
        print(f'  Rename it with whatever you call them: '
              f'munim rename "{client}" "<your name for them>"', file=sys.stderr)
    return 0


def rename(old: str, new: str) -> int:
    """Move a client and everything filed under its name.

    The registry entry is the visible part; the sessions and pasted keys are
    filed by client name too, and leaving them behind would silently
    disconnect a client that still looks connected.
    """
    from munim.container import KeychainBackend
    from munim.remote.servers import SERVERS
    from munim.remote.storage import KeychainTokenStorage

    registry = _registry()
    try:
        record = registry.rename(old, new)
    except (UnknownClient, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    moved = []
    for provider in sorted(SERVERS):
        store = KeychainTokenStorage(old, provider)
        if store._read("tokens") is not None:
            store.move_to(new)
            moved.append(f"{provider} (mcp)")

    backend = KeychainBackend()
    for provider in ("cloudflare", "vercel", "resend"):
        secret = backend.get(old, provider)
        if secret is not None:
            backend.set(new, provider, secret)
            moved.append(provider)

    carried = f" carrying {', '.join(moved)}" if moved else ""
    print(f"{old!r} is now {new!r}{carried}.", file=sys.stderr)
    if record.domain:
        print(f"  domain: {record.domain}", file=sys.stderr)
    return 0


def connect(client: str, provider: str) -> int:
    load_env()
    registry = _registry()
    try:
        registry.get(client)
    except UnknownClient:
        print(f"{client!r} is not registered yet. Adding it.", file=sys.stderr)
        registry.add(ClientRecord(name=client))

    backend = KeychainBackend()

    if provider not in PROVIDERS:
        print(f"{provider} publishes no OAuth endpoint, so it uses an API key.",
              file=sys.stderr)
        print(f"Paste one for {client}: ", end="", file=sys.stderr, flush=True)
        try:
            secret = input().strip()
        except EOFError:
            print("\nNothing pasted; not storing anything.", file=sys.stderr)
            return 2
        if not secret:
            print("Nothing pasted; not storing anything.", file=sys.stderr)
            return 2
        TokenConnector(backend).connect(client, provider, secret)
        print(f"Stored {provider} for {client}.", file=sys.stderr)
        return 0

    client_id, client_secret = _client_id(provider)
    if not client_id:
        print(
            f"No OAuth app registered for {provider}.\n"
            f"Create one, set its redirect URL to "
            f"http://localhost:8976/oauth/callback, then put the client id in "
            f".env as {provider.upper()}_OAUTH_CLIENT_ID.\n"
            f"Until then: munim connect {client} {provider} --token",
            file=sys.stderr)
        return 2

    print(f"Opening your browser to log in to {provider} as {client}…",
          file=sys.stderr)
    account = OAuthConnector(backend).connect(client, provider, client_id,
                                              client_secret or None)
    # Show which account was authorised: this is the one moment where the wrong
    # client can still be connected, and only a person can catch it.
    where = f" ({account})" if account else ""
    print(f"Connected {provider}{where} for {client}.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="munim", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("connect", help="log in to a provider as one client")
    c.add_argument("client", nargs="?",
                   help="what you call this client. Leave it out and the "
                        "account you sign in to supplies the name")
    c.add_argument("provider", nargs="?", choices=sorted({*PROVIDERS, "resend"}))
    c.add_argument("--token", action="store_true",
                   help="paste an API key instead of logging in")
    c.add_argument("--via-app", action="store_true",
                   help="use a registered OAuth application instead of the "
                        "provider's MCP server. Only needed if you want your "
                        "own application name on the consent screen")
    # This was the way in before it became the default. Accepted and ignored,
    # because a flag that was documented and then removed is a dead end for
    # whoever copied the line.
    c.add_argument("--via-mcp", action="store_true", help=argparse.SUPPRESS)

    ls = sub.add_parser("clients", help="list registered clients")
    ls.add_argument("--verbose", action="store_true")

    r = sub.add_parser("rename", help="call a client something else")
    r.add_argument("old")
    r.add_argument("new")

    sub.add_parser("doctor", help="what is set up, what is not, and the next step")

    args = parser.parse_args(argv)

    # `munim connect cloudflare` reads as one positional, and argparse fills the
    # first one. Shift it: a lone argument that names a provider is a provider.
    if args.command == "connect" and args.provider is None:
        if args.client in {*PROVIDERS, "resend"}:
            args.client, args.provider = None, args.client
        else:
            parser.error(f"unknown provider {args.client!r}. "
                         f"Choose from: {', '.join(sorted({*PROVIDERS, 'resend'}))}")

    if args.command == "rename":
        return rename(args.old, args.new)

    if args.command == "doctor":
        from munim.doctor import run as doctor_run
        return doctor_run(_registry())

    if args.command == "clients":
        backend = KeychainBackend()
        for record in _registry().clients():
            from munim.container import Container
            container = Container(record.name, backend)
            connected = [p for p in ("cloudflare", "vercel", "resend")
                         if container.has(p)]
            print(f"{record.name:32} {record.domain or '-':32} "
                  f"{', '.join(connected) or 'nothing connected'}")
        return 0

    if args.token:
        backend = KeychainBackend()
        print(f"Paste the {args.provider} key for {args.client}: ",
              end="", file=sys.stderr, flush=True)
        try:
            secret = input().strip()
        except EOFError:
            secret = ""
        if not secret:
            print("\nNothing pasted; not storing anything.", file=sys.stderr)
            return 2
        TokenConnector(backend).connect(args.client, args.provider, secret)
        print("Stored.", file=sys.stderr)
        return 0

    # The provider's own MCP server is the default wherever there is one: it
    # registers a client on demand, so it works from a clean clone with nothing
    # set up. Sending someone to register an application when they do not have
    # to was the friction this project set out to remove, and it was ours.
    from munim.remote.servers import server_for

    # `--token` never reaches here: it is handled above and stores a pasted key.
    if not args.via_app and server_for(args.provider) is not None:
        return connect_via_mcp(args.client, args.provider)
    return connect(args.client, args.provider)


if __name__ == "__main__":
    raise SystemExit(main())
