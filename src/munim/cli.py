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


def add_server(name: str, url: str) -> int:
    """Point Munim at any MCP server and record what it needs.

    The three built in are not the product. An operator with their own server,
    or with one of the hundreds now published, gives a URL and this works out
    the rest by doing what a client does: calling it without credentials and
    reading the challenge back.
    """
    import asyncio

    from munim.remote.discover import NotAnMcpServer, probe
    from munim.remote.servers import remember

    try:
        found = asyncio.run(probe(url, name))
    except NotAnMcpServer as exc:
        print(str(exc), file=sys.stderr)
        return 2

    remember(found)
    print(f"Added {name!r} at {url}", file=sys.stderr)
    print(f"  {found.note}", file=sys.stderr)

    if found.auth == "registers":
        print(f"  Nothing to set up. Connect a client with: "
              f"munim connect {name}", file=sys.stderr)
    elif found.auth == "app":
        print(f"  This one needs an application registered by hand"
              + (f" at {found.register_at}" if found.register_at else "")
              + f", then {name.upper()}_OAUTH_CLIENT_ID and "
              f"{name.upper()}_OAUTH_CLIENT_SECRET in .env.", file=sys.stderr)
    else:
        print("  It answered without credentials. If the URL carries the "
              "credential, treat it as a secret: it is stored in "
              "~/.munim/servers.json and should not be shared.", file=sys.stderr)
    return 0


def list_servers() -> int:
    from munim.remote.servers import SERVERS, all_servers

    for name, server in sorted(all_servers().items()):
        origin = "built in" if name in SERVERS else "yours"
        ready = "ready" if server.ready else f"needs {server.auth}"
        print(f"{name:14} {ready:14} {origin:9} {server.url}")
    return 0


def merge(source: str, target: str) -> int:
    """Fold one client into another, credentials and all.

    Needed because connecting an account that is already known under another
    label makes a second client, and then a call could go to either. Refuses
    when both hold the same provider: that is two different accounts, not one
    client recorded twice, and picking a winner would silently drop a
    credential for a live account.
    """
    from munim.container import KeychainBackend
    from munim.remote.servers import SERVERS
    from munim.remote.storage import KeychainTokenStorage

    registry = _registry()
    try:
        a, b = registry.get(source), registry.get(target)
    except UnknownClient as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if a.id == b.id:
        print("those are the same client", file=sys.stderr)
        return 2

    backend = KeychainBackend()
    clash = [p for p in ("cloudflare", "vercel", "resend")
             if backend.get(a.id, p) and backend.get(b.id, p)]
    clash += [p for p in sorted(SERVERS)
              if KeychainTokenStorage(a.id, p)._read("tokens")
              and KeychainTokenStorage(b.id, p)._read("tokens")]
    if clash:
        print(f"both hold {', '.join(sorted(set(clash)))}, so these are two "
              f"accounts rather than one client twice. Disconnect one side "
              f"first if you are sure.", file=sys.stderr)
        return 2

    carried = []
    for provider in ("cloudflare", "vercel", "resend"):
        secret = backend.get(a.id, provider)
        if secret is not None:
            backend.set(b.id, provider, secret)
            carried.append(provider)
    for provider in sorted(SERVERS):
        store = KeychainTokenStorage(a.id, provider)
        if store._read("tokens") is not None:
            store.move_to(b.id)
            carried.append(f"{provider} (mcp)")

    if a.domain and not b.domain:
        b.domain = a.domain
        registry.update(b)
    registry.remove(a.id)

    print(f"{a.name!r} folded into {b.name!r}"
          + (f", carrying {', '.join(carried)}" if carried else ""),
          file=sys.stderr)
    return 0


def forget(client: str) -> int:
    """Remove a client that holds nothing. Refuses otherwise: a row removed
    while a credential remains leaves one nothing can reach or name."""
    from munim.container import KeychainBackend
    from munim.remote.servers import SERVERS
    from munim.remote.storage import KeychainTokenStorage

    registry = _registry()
    try:
        record = registry.get(client)
    except UnknownClient as exc:
        print(str(exc), file=sys.stderr)
        return 2

    backend = KeychainBackend()
    held = [p for p in ("cloudflare", "vercel", "resend") if backend.get(record.id, p)]
    held += [f"{p} (mcp)" for p in sorted(SERVERS)
             if KeychainTokenStorage(record.id, p)._read("tokens")]
    if held:
        print(f"{record.name!r} still holds {', '.join(held)}. Merge it into "
              f"another client, or disconnect it first.", file=sys.stderr)
        return 2

    registry.remove(record.id)
    print(f"forgot {record.name!r}", file=sys.stderr)
    return 0


def _redacted(url: str) -> str:
    """A URL that carries a credential, safe to print.

    Zoho's endpoints look like
    https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message, and the hex is the
    secret. Printing it into a terminal that gets pasted into a bug report is
    how a credential leaves a machine, so the host stays and the path goes.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/…"


def ask_which_client(registry, ask=input) -> str | None:
    """Which client is this for.

    A URL that carries a credential cannot name itself the way an OAuth login
    can, so the choice has to come from somewhere. Refusing and telling the
    operator to type a name they already have on screen is worse than asking.

    Returns a client id, a new name, or None if they backed out.
    """
    records = sorted(registry.clients(), key=lambda r: r.name.lower())
    print("Which client is this for?", file=sys.stderr)
    for number, record in enumerate(records, 1):
        print(f"  {number}  {record.name}"
              + (f"   {record.domain}" if record.domain else ""), file=sys.stderr)
    print("  n  a client not listed", file=sys.stderr)
    print("> ", end="", file=sys.stderr, flush=True)

    try:
        answer = ask().strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return None

    if answer.lower() == "n":
        print("Name for this client: ", end="", file=sys.stderr, flush=True)
        try:
            name = ask().strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return None
        return name or None

    if answer.isdigit() and 1 <= int(answer) <= len(records):
        return records[int(answer) - 1].id

    # A name or an id typed straight in, for anyone who knows what they want.
    for record in records:
        if answer in (record.id, record.name):
            return record.id
    if answer:
        print(f"{answer!r} is not one of those.", file=sys.stderr)
    return None


def connect_by_url(client: str, provider: str, url: str) -> int:
    """Connect a provider that identifies a client by their own endpoint.

    There is no OAuth here and nothing to open a browser for: the address is
    the credential. It is stored per client in the keychain rather than in
    servers.json, because that file lists servers and this is one client's
    secret.
    """
    import asyncio

    from munim.remote.discover import NotAnMcpServer, probe
    from munim.remote.storage import KeychainTokenStorage

    registry = _registry()
    try:
        record = registry.get(client)
    except UnknownClient:
        record = ClientRecord(name=client)
        registry.add(record)
        print(f"{client!r} was not registered yet. Added it.", file=sys.stderr)

    try:
        found = asyncio.run(probe(url, provider))
    except NotAnMcpServer as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if found.auth != "url":
        print(f"{_redacted(url)} wants {found.auth} authentication, not a "
              f"credential in the URL. Connect it with: munim connect "
              f"{client!r} {provider}", file=sys.stderr)
        return 2

    KeychainTokenStorage(record.id, provider).remember_endpoint(url)
    print(f"Connected {provider} for {record.name} at {_redacted(url)}",
          file=sys.stderr)
    print("  The path carries the credential, so it is in your keychain and "
          "not in any file this repository holds.", file=sys.stderr)
    return 0


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

    # Remember which account this turned out to be. Without it, connecting the
    # same account under a second label makes a second client and nothing can
    # tell: the sessions look different because the labels are.
    from munim.remote.accounts import holder_of
    from munim.remote.storage import KeychainTokenStorage

    registry = _registry()
    current_id = None
    if not naming:
        try:
            current_id = registry.get(client).id
        except UnknownClient:
            current_id = None

    if account:
        already = holder_of(registry, provider, account, exclude=current_id)
        if already is not None:
            # The provisional session is a duplicate of one already held. Drop
            # it rather than leaving a second set of credentials for one
            # account, which is the thing `merge` exists to clean up.
            if naming:
                KeychainTokenStorage(PROVISIONAL, provider).move_to(already.id)
                print(f"That is {already.name}'s {provider} account, which was "
                      f"already connected. Refreshed it rather than adding a "
                      f"second client.", file=sys.stderr)
                return 0
            print(f"That {provider} account is already connected as "
                  f"{already.name!r}. Nothing was added: two clients holding "
                  f"one account means a call could go to either.\n"
                  f"  To move it: munim merge {already.name!r} {client!r}",
                  file=sys.stderr)
            return 2

    if naming:
        if not account:
            print(f"{provider} did not say which account was authorised, so "
                  f"there is nothing to name this after. Run it again with a "
                  f"name: munim connect \"<client>\" {provider}",
                  file=sys.stderr)
            return 2
        KeychainTokenStorage(PROVISIONAL, provider).move_to(account)
        try:
            record = registry.get(account)
        except UnknownClient:
            record = ClientRecord(name=account)
            registry.add(record)
        client = record.name
        KeychainTokenStorage(record.id, provider).remember_account(account)

    # The account the provider says was authorised, beside the name it was
    # stored under. This is the only moment the two can be compared, and until
    # now nothing compared them: a typo at the prompt stored a real token under
    # a name that had nothing to do with it.
    if account and not naming and current_id is not None:
        KeychainTokenStorage(current_id, provider).remember_account(account)

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
    # Whatever is known, built in or added by the operator. A fixed list here
    # meant adding a server did not make it connectable.
    from munim.remote.servers import all_servers
    known = sorted({*PROVIDERS, "resend", *all_servers()})
    c.add_argument("provider", nargs="?", choices=known)
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
    c.add_argument("--url", metavar="URL",
                   help="for a provider that identifies a client by their own "
                        "endpoint, such as Zoho. The path carries the "
                        "credential, so it goes to your keychain")

    ls = sub.add_parser("clients", help="list registered clients")
    ls.add_argument("--verbose", action="store_true")

    r = sub.add_parser("rename", help="call a client something else")
    r.add_argument("old")
    r.add_argument("new")

    a = sub.add_parser("add-server", help="point Munim at any MCP server")
    a.add_argument("name")
    a.add_argument("url")

    sub.add_parser("servers", help="which MCP servers Munim knows about")

    m = sub.add_parser("merge", help="fold one client into another")
    m.add_argument("source")
    m.add_argument("target")

    f = sub.add_parser("forget", help="remove a client that holds nothing")
    f.add_argument("client")

    sub.add_parser("doctor", help="what is set up, what is not, and the next step")

    args = parser.parse_args(argv)

    # Credentials used to be filed under the client's name. Move anything still
    # there before anything tries to read it, or a client connected yesterday
    # looks disconnected today. Idempotent and cheap: it checks the id first.
    try:
        from munim.migrate import migrate
        for line in migrate(_registry()):
            print(f"moved {line}", file=sys.stderr)
    except Exception:
        pass  # never block a command on a migration

    # `munim connect cloudflare` reads as one positional, and argparse fills the
    # first one. Shift it: a lone argument that names a provider is a provider.
    if args.command == "connect" and args.provider is None:
        from munim.remote.servers import all_servers
        if args.client in {*PROVIDERS, "resend", *all_servers()}:
            args.client, args.provider = None, args.client
        else:
            parser.error(f"unknown provider {args.client!r}. Choose from: "
                         + ", ".join(sorted({*PROVIDERS, "resend", *all_servers()})))

    if args.command == "add-server":
        return add_server(args.name, args.url)

    if args.command == "servers":
        return list_servers()

    if args.command == "merge":
        return merge(args.source, args.target)

    if args.command == "forget":
        return forget(args.client)

    if args.command == "rename":
        return rename(args.old, args.new)

    if args.command == "doctor":
        from munim.doctor import run as doctor_run
        return doctor_run(_registry())

    if args.command == "clients":
        backend = KeychainBackend()
        for record in _registry().clients():
            from munim.container import Container
            container = Container(record.id, backend)
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

    if getattr(args, "url", None):
        target = args.client
        if target is None:
            if not sys.stdin.isatty():
                parser.error("--url needs a client: the URL cannot name itself, "
                             "and there is no terminal to ask on")
            target = ask_which_client(_registry())
            if target is None:
                print("Nothing connected.", file=sys.stderr)
                return 2
        return connect_by_url(target, args.provider, args.url)

    # `--token` never reaches here: it is handled above and stores a pasted key.
    if not args.via_app and server_for(args.provider) is not None:
        return connect_via_mcp(args.client, args.provider)
    return connect(args.client, args.provider)


if __name__ == "__main__":
    raise SystemExit(main())
