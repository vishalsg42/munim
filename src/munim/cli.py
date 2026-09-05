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
from getpass import getpass

from munim.connect.oauth import (PROVIDERS, SHIPPED_CLIENT_IDS,
                                 OAuthConnector)
from munim.connect.token import TokenConnector
from munim.container import KEY_PROVIDERS, KeychainBackend
from munim.env import load as load_env
from munim.pick import choose
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

# What `munim` on its own prints. The parser used to take the module docstring,
# which is about `connect` specifically, so the bare name answered "what is
# this?" by describing one subcommand. That was harmless while the bare name was
# an error and became wrong the moment it turned into the front door.
DESCRIPTION = """One operator, many clients, one MCP server.

Munim holds a separate set of credentials per client, so a coding agent can read
across every client you look after and write only inside one you have named.

Start with `munim doctor`: it says what is set up, what is not, and the exact
command to fix each gap."""


def installed_version() -> str:
    """What `munim --version` prints.

    Read from the installed distribution rather than hardcoded, so it cannot
    drift from pyproject.toml the way a second copy of a version string always
    eventually does. A source checkout that was never installed has no
    distribution to ask, and says so rather than inventing a number: "unknown"
    is a true answer and 0.0.0 is not.
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as distribution_version

    try:
        return distribution_version("munim")
    except PackageNotFoundError:
        return "unknown (running from a source tree, not an install)"


def find_orphans(known: set[str]) -> list[str]:
    """Client ids the keychain holds that no client record claims.

    Split out of the sweep so the same enumeration can be shown to somebody
    before it is acted on. It used to enumerate and delete in one pass, which
    meant `--all` removed credentials it had never named.

    `keyring` cannot list what it holds, so this shells out to the macOS
    keychain. Elsewhere it says so rather than pretending the sweep happened.
    """
    import platform
    import subprocess

    if platform.system() != "Darwin":
        print("  (orphan sweep only works on macOS: keyring cannot list what "
              "it holds, so there is nothing to enumerate elsewhere)",
              file=sys.stderr)
        return []

    try:
        dump = subprocess.run(["security", "dump-keychain"], capture_output=True,
                              text=True, timeout=60).stdout
    except Exception:
        return []

    found: set[str] = set()
    account = None
    for line in dump.splitlines():
        if '"acct"' in line and '="' in line:
            account = line.split('="', 1)[1].rstrip('"')
        elif "munim" in line and account and account.startswith("c_"):
            found.add(account)
    return sorted(found - known)


def planned_removals(records, providers, backend, everything: bool = False):
    """Every keychain item `disconnect` will remove: what it is, and how to go.

    One list, printed and then acted on. The confirmation used to be computed
    separately from the deletion, by asking `connected.connections()`, which
    answers a narrower question: it reports a provider only when there are
    *tokens*. Five things fell through that gap, and the worst is Zoho, which
    authenticates by URL and stores an endpoint and no tokens at all. A session
    that looks empty by that test is the one credential here that no browser
    login can rebuild, and it was being deleted without ever being named.

    Two computations of "what will go" can disagree. One cannot.
    """
    from munim.remote.storage import KeychainTokenStorage

    planned: list[tuple[str, object]] = []

    def sweep(who: str, shown: str, note: str = "") -> None:
        for name in providers:
            if backend.get(who, name) is not None:
                planned.append((
                    f"{shown}: {name} key{note}",
                    lambda w=who, n=name: bool(backend.forget(w, n))))
            kinds = KeychainTokenStorage(who, name).holds()
            if kinds:
                planned.append((
                    f"{shown}: {name} session ({', '.join(kinds)}){note}",
                    lambda w=who, n=name: bool(KeychainTokenStorage(w, n).forget())))

    for record in records:
        sweep(record.id, record.name)
        # Credentials filed under the label, from before the identity split.
        # Deleted by this command since it was written, and never mentioned.
        sweep(record.name, record.name, " (filed under the old label)")

    if everything:
        for orphan in find_orphans({r.id for r in records}):
            sweep(orphan, f"orphan {orphan}")

    return planned


def confirm(planned, ask=None) -> bool:
    """Show the plan and make somebody agree to it.

    Every other destructive path here is scoped by something the operator
    typed. `--all` is scoped by nothing, and it could empty the keychain from a
    single flag with no way back except a browser login per client per provider.

    `ask` is resolved at call time rather than bound as a default, so that a
    test driving `cli.main([...])` can replace it. Holding `input` as a default
    argument binds the builtin when the module loads and no later patch reaches
    it, which made this unreachable from the only way the tests run the CLI.
    """
    ask = ask or input

    print("This removes every credential listed here:", file=sys.stderr)
    for what, _ in planned:
        print(f"  {what}", file=sys.stderr)
    print(f"{len(planned)} credential(s). Getting them back is a browser login "
          f"for each one.", file=sys.stderr)
    print("Type yes to continue: ", end="", file=sys.stderr, flush=True)
    try:
        return ask().strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False


def disconnect(client: str | None, provider: str | None, everything: bool,
               assume_yes: bool = False, dry_run: bool = False,
               ask=None) -> int:
    """Remove stored credentials. Nothing else is touched.

    Clients, domains and run logs stay: this removes what can act on somebody's
    account and leaves what says who they are. Reconnecting is a browser
    window, so the cost of being wrong here is minutes rather than data.
    """
    from munim.container import KEY_PROVIDERS, KeychainBackend
    from munim.remote.servers import all_servers
    from munim.remote.storage import KeychainTokenStorage

    registry = _registry()
    if everything:
        records = registry.clients()
    else:
        try:
            records = [registry.get(client)]
        except UnknownClient as exc:
            print(str(exc), file=sys.stderr)
            return 2

    providers = [provider] if provider else sorted(
        {*all_servers(), *KEY_PROVIDERS})

    backend = KeychainBackend()
    planned = planned_removals(records, providers, backend, everything=everything)

    if dry_run:
        for what, _ in planned:
            print(f"  would remove {what}", file=sys.stderr)
        print(f"{len(planned)} credential(s). Nothing was removed.",
              file=sys.stderr)
        return 0

    if everything and planned and not assume_yes:
        if not sys.stdin.isatty():
            print("disconnect --all removes every credential for every client. "
                  "There is no terminal to confirm on, so nothing was removed. "
                  "Run it with --dry-run to see the list, or --yes if you meant "
                  "it.", file=sys.stderr)
            return 2
        if not confirm(planned, ask):
            print("Nothing was removed.", file=sys.stderr)
            return 2

    removed = [what for what, forget in planned if forget()]

    if not removed:
        print("Nothing was stored.", file=sys.stderr)
        return 0

    for line in removed:
        print(f"  removed {line}", file=sys.stderr)
    print(f"{len(removed)} credential(s) gone. Clients and their domains are "
          f"still here; reconnect with `munim connect <provider>`.",
          file=sys.stderr)
    return 0


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
    from munim.container import KEY_PROVIDERS, KeychainBackend
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
    from munim.container import KEY_PROVIDERS, KeychainBackend
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


ACCOUNT_NAMES_IT = "__account__"


def ask_which_client(registry, ask=None, *, account_can_name=False) -> str | None:
    """Which client is this for.

    A URL that carries a credential cannot name itself the way an OAuth login
    can, so the choice has to come from somewhere. Refusing and telling the
    operator to type a name they already have on screen is worse than asking.

    `account_can_name` is for the OAuth path, where a new client does not have
    to be named by hand: sign in and the account supplies the name, which is
    what keeps a label and an account from drifting apart. Offering only "type
    a name" would have quietly removed that.

    Returns a client id, a new name, ACCOUNT_NAMES_IT, or None if they backed
    out.

    `ask` defaults to None rather than to `input`. `choose` takes the live
    arrow-key picker only when nothing was injected, so defaulting to the
    builtin meant every real invocation fell through to the numbered prompt and
    the picker was never reached outside its own tests. Passing `ask` is how a
    test forces the numbered path, and that is the only thing it should mean.
    """
    records = sorted(registry.clients(), key=lambda r: r.name.lower())

    # Nothing to choose from is not a choice. Asking "which client is this for?"
    # above a single line reading "a client not listed" is a menu with no items
    # on it, and the operator has to work out that the answer is `n` before they
    # can type the name they already knew.
    if not records:
        print("No clients yet, so this one is new.", file=sys.stderr)
        return _name_typed(ask)

    options = [(record.name, record.domain or "") for record in records]
    if account_can_name:
        options.append(("a new client, named after the account I sign in to", ""))

    def resolve(answer: str) -> int | None:
        """An id or a name typed straight in, for somebody who already knows
        the client and does not want to read the list.

        The `n` and `a` letter shortcuts are gone. They existed because the rows
        they stood for could not be selected any other way; both are ordinary
        rows now, with numbers, that the arrow keys reach like everything else.
        Two ways to pick the same row is one more than a list needs.
        """
        for index, record in enumerate(records):
            if answer in (record.id, record.name):
                return index
        return None

    # `allow_new` is what removed the "a client not listed" row. Choosing that
    # row only ever led to a second prompt asking for the name, so the operator
    # had to announce they were about to type a name before typing it. Typing it
    # is the announcement.
    picked = choose("Which client is this for?", options, ask=ask,
                    resolve=resolve, allow_new=True,
                    new_hint="a name for a new client")
    if picked is None:
        return None
    if isinstance(picked, str):
        return picked                       # a name for a client not yet known
    if picked < len(records):
        return records[picked].id
    return ACCOUNT_NAMES_IT


def _name_typed(ask=None) -> str | None:
    print("Name for this client: ", end="", file=sys.stderr, flush=True)
    try:
        name = (ask or input)().strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return None
    return name or None


def adopt_provisional(registry, provider: str, ask=None):
    """Who does this session belong to, when the provider will not say.

    Returns the client record to file it under, or None if there is nobody to
    ask or the operator backed out. Creating a client here is deliberate: the
    login has already happened, and refusing because the name is new would mean
    doing it again for no reason.
    """
    if not sys.stdin.isatty():
        print(f"{provider} did not say which account was authorised, and there "
              f"is no terminal to ask on. Nothing was kept. Run it again with a "
              f"name: munim connect \"<client>\" {provider}", file=sys.stderr)
        return None

    # The reason was given before the browser opened, which is the only moment
    # it could have changed anything. Repeating it here and again at the end
    # said the same sentence three times in one command.
    chosen = ask_which_client(registry, ask or input)
    if chosen is None:
        print("Nothing connected.", file=sys.stderr)
        return None

    try:
        return registry.get(chosen)
    except UnknownClient:
        record = ClientRecord(name=chosen)
        registry.add(record)
        print(f"Added {record.name!r}.", file=sys.stderr)
        return record


def add_client(name: str, domain: str | None = None) -> int:
    """Write down a business you look after, before deciding what to connect.

    Connecting used to be the only way a client came into being, which meant
    you could not record "I look after this business" until you had an account
    of theirs in front of you. Both orders reach the same place now.
    """
    registry = _registry()
    try:
        existing = registry.get(name)
    except UnknownClient:
        existing = None
    if existing is not None:
        print(f"{existing.name!r} is already registered. Two rows for one "
              f"business is the split identity `munim clients merge` exists to "
              f"repair, so nothing was added.", file=sys.stderr)
        return 2

    record = ClientRecord(name=name, domain=domain or "")
    registry.add(record)
    print(f"Added {record.name!r}. Nothing is connected yet:",
          file=sys.stderr)
    print(f'  munim connect "{record.name}" cloudflare', file=sys.stderr)
    return 0


def config(action: str, provider: str | None, client_id: str | None) -> int:
    """The application credential for providers that will not issue one.

    Stored in the keychain rather than a file, because a file has a location
    and an installed package cannot know which directory you will run from.
    See munim/appcreds.py.

    The id is a parameter: it is not a secret, it is in the Cloud Console and in
    every authorize URL. The secret is prompted, because an argument lands in
    shell history and is visible to anyone who can run `ps` at the time.
    """
    from munim.appcreds import forget as forget_app
    from munim.appcreds import remember, stored
    from munim.env import load as load_env
    from munim.remote.servers import SERVERS

    # doctor loads this and config did not, so `config list` said "not set" for
    # a provider `doctor` reported as configured. Two commands disagreeing about
    # the same fact is worse than either answer alone.
    load_env()

    needs_one = sorted(n for n, srv in SERVERS.items() if srv.auth == "app")

    if action == "list":
        found = stored(needs_one)
        for name in needs_one:
            entry = found.get(name)
            if entry is None:
                print(f"  {name:10} not set", file=sys.stderr)
            else:
                secret = "with a secret" if entry["secret"] else "no secret"
                print(f"  {name:10} {entry['client_id']}  ({secret}, from the "
                      f"{entry['from']})", file=sys.stderr)
        if not needs_one:
            print("No provider needs an application registered by hand.",
                  file=sys.stderr)
        return 0

    if not provider:
        print(f"name a provider: {', '.join(needs_one)}", file=sys.stderr)
        return 2

    if action == "unset":
        if forget_app(provider):
            print(f"Removed the {provider} application.", file=sys.stderr)
        else:
            print(f"Nothing stored for {provider}.", file=sys.stderr)
        return 0

    if not client_id:
        print(f"--client-id is required. Find it at "
              f"{SERVERS[provider].register_at or 'the provider console'}",
              file=sys.stderr)
        return 2

    # Prompted, never an argument. An empty secret is legitimate: Google
    # documents an installed-app secret as not confidential and some providers
    # issue none at all.
    secret = getpass(f"{provider} client secret (leave empty if none): ")
    remember(provider, client_id, secret)
    print(f"Stored the {provider} application in your keychain. It works from "
          f"any directory.", file=sys.stderr)
    return 0


def config_ai(action: str | None, names: list[str]) -> int:
    """The agent switch, the model host, the model id and the key.

    Under `config` rather than a noun of its own because `config` is already the
    settings command: it writes the same `__munim__` keychain account, prompts
    secrets through getpass, and never echoes one back. A second command doing
    all three against the same account is the duplication this file warns about
    where `config` loads the env, and two commands disagreeing about one fact is
    worse than either answer alone.
    """
    from munim import settings

    hosts = ", ".join(settings.ORDER)

    if action is None:
        return _show_ai()

    if action in ("on", "off"):
        try:
            settings.set_enabled(action == "on")
        except settings.Unreadable as exc:
            print(str(exc), file=sys.stderr)
            return 2
        state = settings.ai()
        if action == "on":
            chosen = state.chosen()
            if chosen:
                print(f"Agents on, using {chosen}. This takes effect on the next "
                      f"tool call: no need to reconnect your coding agent.",
                      file=sys.stderr)
            else:
                print("Agents on, but no model host can be built yet.",
                      file=sys.stderr)
                for line in _missing_hosts():
                    print(f"  {line}", file=sys.stderr)
        else:
            print("Agents off. Munim is local: the checks, the audit and the "
                  "mail plan all still work, and nothing reaches a model host.",
                  file=sys.stderr)
        return 0

    if action == "host":
        if len(names) != 1:
            print(f"name a host: {settings.AUTO}, {hosts}", file=sys.stderr)
            return 2
        wanted = names[0]
        if wanted != settings.AUTO and wanted not in settings.HOSTS:
            print(f"{wanted!r} is not a host Munim knows. Choose from: "
                  f"{settings.AUTO}, {hosts}", file=sys.stderr)
            return 2
        settings.set_host(wanted)
        print(f"Host set to {wanted}.", file=sys.stderr)
        if wanted != settings.AUTO and not settings.installed(wanted):
            spec = settings.HOSTS[wanted]
            print(f"  It is not installed here: pip install 'munim[{spec.extra}]'",
                  file=sys.stderr)
        return 0

    if action == "model":
        # Two positionals, like `servers add`. One shared model id would be a
        # bug rather than a shortcut: set a Gemini id, switch to Bedrock, and it
        # is handed to BedrockModel(model_id=...).
        if len(names) != 2:
            print(f"config ai model takes a host and a model id: "
                  f"munim config ai model gemini gemini-2.5-pro\n"
                  f"  hosts: {hosts}", file=sys.stderr)
            return 2
        host, model_id = names
        if host not in settings.HOSTS:
            print(f"{host!r} is not a host Munim knows. Choose from: {hosts}",
                  file=sys.stderr)
            return 2
        settings.set_model(host, model_id)
        print(f"{host} will use {model_id}.", file=sys.stderr)
        return 0

    if action == "key":
        if len(names) != 1:
            print(f"name a host: {hosts}", file=sys.stderr)
            return 2
        host = names[0]
        spec = settings.HOSTS.get(host)
        if spec is None:
            print(f"{host!r} is not a host Munim knows. Choose from: {hosts}",
                  file=sys.stderr)
            return 2
        if not spec.keys:
            print(f"{host} authenticates with AWS credentials rather than an "
                  f"API key, so there is nothing to store here.", file=sys.stderr)
            return 2
        secret = getpass(f"{host} API key: ")
        if not secret.strip():
            print("Nothing pasted; not storing anything.", file=sys.stderr)
            return 2
        settings.remember_key(host, secret.strip())
        print(f"Stored the {host} key in your keychain. It works from any "
              f"directory.", file=sys.stderr)
        # The obvious sequence should do the obvious thing. Without this,
        # `key gemini` then `on` picks Bedrock, because auto prefers it and
        # constructing a model does not authenticate.
        if settings.ai().host == settings.AUTO:
            settings.set_host(host)
            print(f"  Host was {settings.AUTO}, so it is now {host}.",
                  file=sys.stderr)
        return 0

    if action == "unset":
        if len(names) != 1:
            print(f"name a host: {hosts}", file=sys.stderr)
            return 2
        if settings.forget_key(names[0]):
            print(f"Removed the {names[0]} key.", file=sys.stderr)
        else:
            print(f"Nothing stored for {names[0]}.", file=sys.stderr)
        return 0

    print(f"unknown: config ai {action}. Try: on, off, host, model, key, unset",
          file=sys.stderr)
    return 2


def _missing_hosts() -> list[str]:
    from munim import settings

    lines = []
    for name in settings.ORDER:
        spec = settings.HOSTS[name]
        if not settings.installed(name):
            lines.append(f"{name}: not installed"
                         + (f", run pip install 'munim[{spec.extra}]'"
                            if spec.extra else ""))
        elif spec.keys and not settings.resolve_key(name)[0]:
            lines.append(f"{name}: no key, run munim config ai key {name}")
    return lines


def _show_ai() -> int:
    """What is on, on what, and where each answer came from. Never a key."""
    from munim import settings
    from munim.env import load as load_env

    load_env()
    state = settings.ai()
    chosen = state.chosen()

    print(f"  agents     {'on' if state.enabled else 'off'}"
          f"  (from the {state.where['enabled']})", file=sys.stderr)
    print(f"  host       {state.host}  (from the {state.where['host']})"
          + (f"  -> {chosen}" if state.host == settings.AUTO and chosen else ""),
          file=sys.stderr)
    for name in settings.ORDER:
        spec = settings.HOSTS[name]
        if not settings.installed(name):
            note = (f"not installed, run pip install 'munim[{spec.extra}]'"
                    if spec.extra else "not installed")
        elif not spec.keys:
            note = f"ready, model {settings.model_for(name)}"
        else:
            secret, source = settings.resolve_key(name)
            note = (f"key from the {source}, model {settings.model_for(name)}"
                    if secret else f"no key, run munim config ai key {name}")
        print(f"    {name:10} {note}", file=sys.stderr)
    for problem in state.problems:
        print(f"  ! {problem}", file=sys.stderr)
    if not state.enabled:
        print("  Munim is local. Turn agents on with: munim config ai on",
              file=sys.stderr)
    return 0


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

    # Resolve the label to an id before anything is stored. Credentials are
    # filed by identity (D26), and this was still handing the store a label:
    # tokens went under "Kloudfirst" while the account marker went under the
    # id, so one session lived in two places and a rename would have orphaned
    # half of it. The migration that runs on every command kept moving the
    # tokens across afterwards, which is why it never looked broken.
    registry = _registry()
    record = None
    if not naming:
        try:
            record = registry.get(client)
        except UnknownClient:
            record = ClientRecord(name=client)
            registry.add(record)
            print(f"{client!r} was not registered yet. Added it.",
                  file=sys.stderr)
        client = record.name  # the stored label, not whatever was typed

    # Without a name there is no id yet: the account has to be authorised
    # before there is anything to call it. The session waits under a
    # provisional key and moves to the id once the provider answers.
    working_key = record.id if record else PROVISIONAL

    if naming:
        from munim.remote.identity import can_name_itself

        if can_name_itself(provider):
            print(f"Opening your browser. Sign in to the {provider} account you "
                  f"want to add, and the client will be named after it.",
                  file=sys.stderr)
        else:
            # Promising a name this provider cannot supply, and then saying so
            # once the login is already done, wastes the one moment the operator
            # could have decided differently.
            print(f"Opening your browser. Sign in to the {provider} account you "
                  f"want to add.", file=sys.stderr)
            print(f"  {provider} does not report which account was authorised, "
                  f"so you will be asked which client this is for.",
                  file=sys.stderr)
    else:
        print(f"Opening your browser to log in to {provider} as {client}.",
              file=sys.stderr)
        print(f"The consent screen will name the application "
              f"\"Munim ({client})\".", file=sys.stderr)

    try:
        tools, account = asyncio.run(
            connect_and_identify(working_key, provider, label=client or PROVISIONAL))
    except NoRemoteServer as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Remember which account this turned out to be. Without it, connecting the
    # same account under a second label makes a second client and nothing can
    # tell: the sessions look different because the labels are.
    from munim.remote.accounts import holder_of
    from munim.remote.storage import KeychainTokenStorage

    current_id = record.id if record else None

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
            # The provider authorised us and will not say who it authorised.
            # Vercel grants `openid offline_access` and nothing that names an
            # account, which is the narrowest scope of any provider here.
            #
            # This used to print "run it again with a name" and return 2, which
            # threw away a completed browser login and left its tokens filed
            # under the provisional key, where nothing could name them and
            # nothing would ever clean them up. A live credential orphaned by a
            # command that reported failure.
            #
            # Ask instead. The operator knows which client this is, the session
            # is already open, and `ask_which_client` is the same picker
            # `connect` uses when a URL cannot name itself.
            record = adopt_provisional(registry, provider)
            if record is None:
                # Backed out, or nothing to ask on. Either way the session goes:
                # keeping tokens nobody chose an owner for is how the orphans
                # this project already had to sweep up came to exist.
                KeychainTokenStorage(PROVISIONAL, provider).forget()
                return 2
            KeychainTokenStorage(PROVISIONAL, provider).move_to(record.id)
            print(f"Connected {provider} for {record.name}: {len(tools)} tools.",
                  file=sys.stderr)
            return 0
        # The record first, so there is an id to move the session onto. This
        # used to move it onto the account string, which is another label.
        try:
            record = registry.get(account)
        except UnknownClient:
            record = ClientRecord(name=account)
            registry.add(record)
        KeychainTokenStorage(PROVISIONAL, provider).move_to(record.id)
        client = record.name
        KeychainTokenStorage(record.id, provider).remember_account(account)

    # The account the provider says was authorised, beside the name it was
    # stored under. This is the only moment the two can be compared, and until
    # now nothing compared them: a typo at the prompt stored a real token under
    # a name that had nothing to do with it.
    if account and not naming and current_id is not None:
        store = KeychainTokenStorage(current_id, provider)
        was = store.account()
        store.remember_account(account)
        if was and was != account:
            # Said out loud rather than swapped quietly. Rebinding a client to
            # a different account is sometimes the point and sometimes the
            # accident that brought them here.
            print(f"  This client was previously connected as {was!r}. "
                  f"It is now {account!r}.", file=sys.stderr)

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
    from munim.container import KEY_PROVIDERS, KeychainBackend
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
    parser = argparse.ArgumentParser(
        prog="munim", description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # -V as well as --version, because both are what people try first.
    parser.add_argument("--version", "-V", action="version",
                        version=f"munim {installed_version()}")
    # Not required. Running the bare name to find out what a tool does is the
    # first thing anyone does with it, and answering that with an error and
    # exit 2 treats a reasonable question as a mistake. Help, and exit 0.
    sub = parser.add_subparsers(dest="command")

    c = sub.add_parser("connect", help="log in to a provider as one client")
    c.add_argument("client", nargs="?",
                   help="what you call this client. Leave it out and the "
                        "account you sign in to supplies the name")
    # Whatever is known, built in or added by the operator. A fixed list here
    # meant adding a server did not make it connectable.
    from munim.remote.servers import all_servers
    known = sorted({*all_servers(), *KEY_PROVIDERS})
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

    # Two nouns, and every command reads as one of them. The surface grew a
    # command at a time and ended up flat, with `add-server` and no `add-client`
    # beside it, so from the terminal a client could only come into being as a
    # side effect of connecting something. There was no way to write down "I
    # look after this business" before deciding what to connect.
    #
    # `connect` stays a verb, because it is an event rather than a thing.
    ls = sub.add_parser("clients", help="the businesses you look after")
    ls.add_argument("action", nargs="?",
                    choices=["add", "rename", "forget", "merge"],
                    help="omit to list them")
    ls.add_argument("names", nargs="*", metavar="NAME",
                    help="the client, plus a second name for rename and merge")
    ls.add_argument("--domain", help="their site, for `add`")
    ls.add_argument("--verbose", action="store_true")
    ls.add_argument("--json", action="store_true", dest="as_json",
                    help="machine-readable, for scripts")

    # 0.1.0 shipped these spellings. Breaking a published surface to tidy it is
    # a bad trade when an alias costs a line, so they still work and only the
    # grouped form is advertised.
    d = sub.add_parser("disconnect", help="remove stored credentials")
    d.add_argument("client", nargs="?")
    d.add_argument("provider", nargs="?")
    d.add_argument("--all", action="store_true", dest="everything",
                   help="every client and every provider. Asks first")
    d.add_argument("--yes", "-y", action="store_true", dest="assume_yes",
                   help="skip the confirmation, for scripts")
    d.add_argument("--dry-run", "-n", action="store_true", dest="dry_run",
                   help="print exactly what would be removed, and stop")

    sv = sub.add_parser("servers", help="what a client can be connected to")
    sv.add_argument("action", nargs="?", choices=["add"],
                    help="omit to list them")
    sv.add_argument("names", nargs="*", metavar="ARG",
                    help="a name and a URL, for `add`")

    c = sub.add_parser("config", help="settings: the agent switch and model "
                                      "host, plus the gmail and stitch "
                                      "application credential")
    c.add_argument("subject", nargs="?", choices=["ai", "app"],
                   help="omit to show everything")
    c.add_argument("action", nargs="?",
                   help="ai: on, off, host, model, key, unset. "
                        "app: set, list, unset")
    c.add_argument("names", nargs="*", metavar="ARG")
    c.add_argument("--client-id", dest="client_id",
                   help="the application's client id, for `app set`. The "
                        "secret is prompted, never passed as an argument")

    dr = sub.add_parser("doctor", help="what is wrong with this installation")
    dr.add_argument("--verbose", "-v", action="store_true",
                    help="also list what is connected")

    # The flat spellings 0.1.0 shipped, rewritten to the grouped form before
    # parsing. Kept as a rewrite rather than as hidden subparsers because
    # argparse prints `==SUPPRESS==` for a suppressed subcommand in this
    # version rather than hiding it, and a help listing that shows the string
    # ==SUPPRESS== is worse than showing the command.
    LEGACY = {"rename": "clients", "forget": "clients", "merge": "clients",
              "add-server": "servers"}
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in LEGACY:
        old = argv[0]
        argv = [LEGACY[old], "add" if old == "add-server" else old, *argv[1:]]

    # `config` grew a subject when the agent settings landed beside the
    # application credential. The old spelling is published (docs/providers/
    # gmail.md tells people to run `munim config set gmail --client-id ...`), so
    # it is rewritten rather than broken.
    if len(argv) >= 2 and argv[0] == "config" and argv[1] in ("set", "list", "unset"):
        argv = ["config", "app", *argv[1:]]

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

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
        if args.client in {*all_servers(), *KEY_PROVIDERS}:
            args.client, args.provider = None, args.client
        else:
            parser.error(f"unknown provider {args.client!r}. Choose from: "
                         + ", ".join(sorted({*all_servers(), *KEY_PROVIDERS})))

    if args.command == "disconnect":
        if not args.everything and not args.client:
            parser.error("name a client, or pass --all")
        return disconnect(args.client, args.provider, args.everything,
                          args.assume_yes, args.dry_run)

    if args.command == "servers":
        if args.action == "add":
            if len(args.names) != 2:
                parser.error("servers add takes a name and a URL")
            return add_server(*args.names)
        return list_servers()

    if args.command == "config":
        if args.subject == "ai":
            return config_ai(args.action, args.names)
        if args.subject == "app":
            provider = args.action if args.action in ("set", "unset", "list") else None
            # `app set gmail`: action is the verb, the provider is the first name.
            verb = args.action or "list"
            name = args.names[0] if args.names else None
            return config(verb, name, args.client_id)
        # No subject: show everything, because "what is configured" is one
        # question even though it has two answers.
        print("Applications:", file=sys.stderr)
        config("list", None, None)
        print("Agents:", file=sys.stderr)
        return config_ai(None, [])

    if args.command == "doctor":
        from munim.doctor import run as doctor_run
        return doctor_run(_registry(), verbose=args.verbose)

    if args.command == "clients":
        # Accepted-and-ignored is worse than refused. `--json` only shapes the
        # listing, and `--verbose` is read by nothing at all.
        if args.as_json and args.action is not None:
            parser.error(f"--json applies to the listing, not to "
                         f"`clients {args.action}`")
        if args.action == "add":
            if len(args.names) != 1:
                parser.error('clients add takes one name: '
                             'munim clients add "Ivy & Fern"')
            return add_client(args.names[0], args.domain)
        if args.action == "rename":
            if len(args.names) != 2:
                parser.error("clients rename takes the old name and the new one")
            return rename(*args.names)
        if args.action == "forget":
            if len(args.names) != 1:
                parser.error("clients forget takes one name")
            return forget(args.names[0])
        if args.action == "merge":
            if len(args.names) != 2:
                parser.error("clients merge takes a source and a target")
            return merge(*args.names)

        from munim.connected import connections, describe
        backend = KeychainBackend()
        records = _registry().clients()

        if args.as_json:
            # Data on stdout, one object, so `munim clients --json | jq` works.
            # The table is for reading and is not a format anything should have
            # to parse.
            import json as json_module

            out = []
            for record in records:
                keys, sessions = connections(record.id, backend)
                out.append({"id": record.id, "name": record.name,
                            "domain": record.domain or None,
                            "api_keys": keys, "mcp_sessions": sessions})
            print(json_module.dumps(out, indent=2))
            return 0

        for record in records:
            print(f"{record.name:32} {record.domain or '-':32} "
                  f"{describe(record.id, backend)}")
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

    # Connecting a second provider for a client you already have is the common
    # case after the first day, and with no name this went straight to "let the
    # account name a new client", quietly making another one. The only way to
    # avoid that was to retype a name already on screen.
    #
    # Not asked when there is nothing to choose from, because a prompt with one
    # option is worse than the zero-setup path it replaces, and not asked
    # without a terminal, because a prompt nobody can answer is a hang.
    if args.client is None and sys.stdin.isatty():
        if _registry().clients():
            from munim.remote.identity import can_name_itself

            picked = ask_which_client(
                _registry(), account_can_name=can_name_itself(args.provider))
            if picked is None:
                print("Nothing connected.", file=sys.stderr)
                return 2
            # None keeps the old behaviour: authorise first, name after.
            args.client = None if picked == ACCOUNT_NAMES_IT else picked

    # A header-authenticated server has nothing to open a browser for. Saying
    # so beats starting an OAuth flow against a server that will not answer it.
    _server = server_for(args.provider)
    if _server is not None and _server.auth == "header" and not args.token:
        parser.error(
            f"{args.provider} authenticates with an API key in "
            f"{_server.header}, not a browser login. Paste one with: "
            f"munim connect \"{args.client or '<client>'}\" {args.provider} --token")

    # `--token` never reaches here: it is handled above and stores a pasted key.
    if not args.via_app and server_for(args.provider) is not None:
        return connect_via_mcp(args.client, args.provider)
    return connect(args.client, args.provider)


if __name__ == "__main__":
    raise SystemExit(main())
