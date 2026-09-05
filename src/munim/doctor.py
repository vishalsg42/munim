"""`munim doctor`: what is set up, what is not, and the exact next step.

For a tool strangers are meant to install, "it does not work" is the failure that
loses them. Every check here reports the specific missing thing and the one
command or URL that fixes it, rather than a stack trace.
"""

import os
import platform
import shutil
import json
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from munim.connect.oauth import PROVIDERS as OAUTH_PROVIDERS
from munim.connect.oauth import REDIRECT_URI
from munim.connected import connections
from munim.container import KeychainBackend
from munim.env import load as load_env
from munim.registry import Registry
from munim.settings import read as read_settings


OK, WARN, BAD = "ok", "warn", "bad"
MARK = {OK: "✓", WARN: "!", BAD: "✗"}


@dataclass
class Finding:
    status: str
    what: str
    detail: str = ""
    fix: str = ""


def _config() -> Finding:
    """Which file the configuration came from, or where to put one.

    Named rather than implied, because the loader consults several places and
    "it works in one directory and not another" is a mystery until you know
    which file was read. An installed package finds nothing in site-packages,
    so this is also how somebody discovers ~/.munim/.env exists.
    """
    from munim.env import CONFIG_HOME, load, sources

    used = load()
    if used:
        home = Path.home()
        shown = f"~/{used.relative_to(home)}" if used.is_relative_to(home) else str(used)
        return Finding(OK, "Config", shown)

    # Not a problem. A fresh install has no .env and does not need one: agents
    # are off, and nothing else reads it until you configure a provider that
    # does. Reporting the normal state of a working install as a warning is how
    # people learn to ignore the whole report.
    return Finding(OK, "Config", f"none yet, and nothing needs one "
                                 f"(would read {CONFIG_HOME})")


def _settings_file() -> Finding:
    """The other config file, named for the same reason as the first.

    `_config` reports the .env and used to be the only answer to "where does
    Munim read from". Since the agent settings landed there are two files, and a
    doctor that names one while silently reading two is the mystery this whole
    pair of findings exists to prevent.
    """
    from munim.settings import _path

    path = _path()
    home = Path.home()
    shown = f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)
    if not path.is_file():
        return Finding(OK, "Settings", f"{shown} (none yet, so defaults)",
                       fix="")
    _, problem = read_settings()
    if problem:
        return Finding(WARN, "Settings", problem,
                       fix=f"fix or delete {shown}. Agents stay off until it "
                           f"parses, which is the safe way round")
    return Finding(OK, "Settings", shown)


def _agents() -> list[Finding]:
    """Whether Munim may think, on what, and what is stopping it.

    Replaces `_model`, which asked only "is a key set" and answered OK for
    Gemini whenever GEMINI_API_KEY existed, without checking the backend could
    be imported. It could not, on a bare install: Strands ships Gemini and
    Anthropic as extras. So doctor reported a working host for something that
    raised ModuleNotFoundError at the first call.

    "No model host" is no longer BAD. Off is the default and the intended state,
    and a fresh install reporting itself broken for behaving as designed teaches
    people to ignore the report.
    """
    from munim import settings
    from munim.env import ignored_in

    load_env()
    state = settings.ai()
    out: list[Finding] = []

    # Anything that made a setting unreadable. Each is already phrased as a
    # sentence by settings.ai, because it knows which value was wrong.
    for problem in state.problems:
        out.append(Finding(WARN, "Agents", problem,
                           fix="munim config ai  shows what is set"))

    for path, name in ignored_in():
        out.append(Finding(WARN, "Agents",
                           f"{name} is set in {path}, and a file cannot carry it",
                           fix=f"remove it and use: munim config ai on"))

    # A shell variable changes what this command reports and not what the MCP
    # server does: the server is a subprocess and does not inherit this shell.
    if os.environ.get("MUNIM_AI") is not None:
        out.append(Finding(WARN, "Agents",
                           f"MUNIM_AI is set in this shell, so it decides what "
                           f"this command reports",
                           fix="the MCP server does not inherit this shell, so "
                               "it reads settings.json. Use: munim config ai on"))

    if not state.enabled:
        out.append(Finding(OK, "Agents", "off, so Munim is local",
                           fix="munim config ai on  to let check, "
                               "work_on_client and ask_across_clients reason"))
        # The upgrade case: somebody on 0.2.1 had a key and got explanations.
        # Without this the prose just quietly stops appearing.
        holding = [h for h in settings.ORDER
                   if settings.HOSTS[h].keys and settings.resolve_key(h)[0]]
        if holding:
            out.append(Finding(WARN, "Agents",
                               f"a {', '.join(holding)} key is configured but "
                               f"agents are off, so it is unused",
                               fix="munim config ai on, or munim config ai "
                                   f"unset {holding[0]} to remove the key"))
        return out

    chosen = state.chosen()
    if chosen:
        out.append(Finding(OK, "Agents",
                           f"on, {chosen} {settings.model_for(chosen)}"))
        return out

    from munim.agent.model import _why_nothing_is_usable
    out.append(Finding(BAD, "Agents", "on, but no model host can be built",
                       fix=_why_nothing_is_usable(state)))
    return out


# Every MCP client's own config, because munim is an MCP server and MCP is not
# one vendor's protocol. `docs/ARCHITECTURE.md` has always drawn the client as
# "Claude Code, Codex, Cursor", while this check shelled out to `claude` alone
# and called it a problem to fix when munim was not registered there. For an
# operator driving munim from Codex that verdict is meaningless, and it cost
# eighteen of the command's eighteen and a half seconds to be wrong.
#
# Reading the files is also what makes `doctor` instant. `claude mcp list` takes
# about fifteen seconds to start; every check here now totals milliseconds.
MCP_CLIENTS = (
    ("Claude Code", "~/.claude.json"),
    ("Claude Desktop",
     "~/Library/Application Support/Claude/claude_desktop_config.json"),
    ("Codex", "~/.codex/config.toml"),
    ("Cursor", "~/.cursor/mcp.json"),
    ("Antigravity", "~/.gemini/antigravity/mcp_config.json"),
    ("Gemini CLI", "~/.gemini/config/mcp_config.json"),
    ("Windsurf", "~/.codeium/windsurf/mcp_config.json"),
)


def _servers_in(path: Path) -> dict:
    """The MCP servers one client has configured, as {name: command}.

    Two shapes. JSON clients keep an `mcpServers` object, and Claude Code also
    nests one per project under `projects`, which is how a server can be
    registered in one directory and missing in the next. Codex uses TOML with a
    `[mcp_servers.name]` table per server.

    The TOML is scanned rather than parsed: `tomllib` is 3.11 and this package
    supports 3.10, and all that is wanted here is the names and commands.
    """
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return {}

    if path.suffix == ".toml":
        found = {}
        for name in re.findall(r"\[mcp_servers\.([A-Za-z0-9_.-]+)\]", text):
            block = text.split(f"[mcp_servers.{name}]", 1)[1].split("\n[", 1)[0]
            command = re.search(r'command\s*=\s*"([^"]*)"', block)
            found[name] = command.group(1) if command else ""
        return found

    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}

    found = {}
    for holder in [data, *(data.get("projects") or {}).values()]:
        if not isinstance(holder, dict):
            continue
        for name, entry in (holder.get("mcpServers") or {}).items():
            command = entry.get("command", "") if isinstance(entry, dict) else ""
            found.setdefault(name, command)
    return found


def _registrations() -> list[tuple[str, dict]]:
    """(client name, its servers) for every MCP client present on this machine."""
    out = []
    for name, raw in MCP_CLIENTS:
        path = Path(raw).expanduser()
        if path.is_file():
            out.append((name, _servers_in(path)))
    return out


def _mcp_registered() -> Finding:
    """Whether any coding agent on this machine knows about munim.

    A note rather than a verdict when it does not. munim cannot see every MCP
    client that exists, so "not registered in the ones I know about" is not the
    same as broken, and reporting it as a problem was wrong for anybody using an
    agent this list does not name.
    """
    found = _registrations()
    if not found:
        return Finding(OK, "Coding agent", "no MCP client config found here")

    holding = [client for client, servers in found if "munim" in servers]
    if holding:
        return Finding(OK, "Coding agent", f"registered in {', '.join(holding)}")

    seen = ", ".join(client for client, _ in found)
    return Finding(WARN, "Coding agent", f"not registered in {seen}",
                   fix=f"point your agent at "
                       f"{Path(sys.executable).parent / 'munim-mcp'}. For Claude "
                       f"Code: claude mcp add --scope user munim -- that path "
                       f"(--scope user makes it available in every project)")


def _mcp_command() -> str:
    """The command a coding agent is configured to spawn for munim, or "".

    Read from the config rather than from `claude mcp list`, which only knew
    about one client and took fifteen seconds to say so.
    """
    for _, servers in _registrations():
        command = servers.get("munim", "")
        if command:
            return command
    return ""


def _interpreter_of(script: str) -> str:
    """Which Python runs a console script, resolved through symlinks.

    A venv's `bin/python` is usually a symlink to the real interpreter, and it
    is the resolved one macOS files its access rule against: a pipx venv
    pointing at Homebrew's python is Homebrew's python as far as the keychain
    is concerned, which is why reinstalling a tool does not cost the approvals
    and upgrading Python does.
    """
    try:
        first = Path(script).read_text(errors="ignore").splitlines()[0]
    except (OSError, IndexError):
        return ""
    if not first.startswith("#!"):
        return ""
    named = first[2:].strip().split(" ")[0]
    try:
        return os.path.realpath(named)
    except OSError:
        return ""


def _one_interpreter() -> list[Finding]:
    """Whether the MCP server and this command run on the same Python.

    macOS files a keychain access rule per item per binary. The interpreter
    that stores a credential can read it back with no prompt, so a single
    install never asks for anything. Two installs is a different matter: each
    one is a separate binary to the keychain, so each asks for approval for
    every item the other created, and neither ever inherits the other's. That
    is not a bounded number of clicks, it is a permanent condition, and it is
    invisible from either side.

    Only reported on macOS. Linux Secret Service and Windows Credential Manager
    have no per-item, per-binary rule, so a mismatch there costs nothing and
    saying so would be noise.
    """
    if platform.system() != "Darwin":
        return []

    command = _mcp_command()
    if not command:
        return []

    theirs = _interpreter_of(command)
    ours = os.path.realpath(sys.executable)
    if not theirs:
        return []

    if theirs == ours:
        return [Finding(OK, "One interpreter",
                        f"the MCP server and this command share "
                        f"{Path(ours).name}")]

    return [Finding(WARN, "One interpreter",
                    "the MCP server and this command are different Pythons, "
                    "so the keychain will keep asking for your password",
                    fix=f"point them at one. Either register this one: "
                        f"claude mcp remove munim && claude mcp add munim "
                        f"{Path(sys.executable).parent / 'munim-mcp'}  "
                        f"(or run the CLI from {Path(theirs).parent})")]


def _keychain() -> Finding:
    """Where credentials are, and whether that place can be used.

    Named `_keychain` still, because three tests and two documents refer to it
    by that name and the thing it reports is the same question. What it reports
    is the file store now: see munim/vault.py for why.
    """
    from munim import vault

    where = vault.path()
    home = Path.home()
    shown = f"~/{where.relative_to(home)}" if where.is_relative_to(home) else str(where)

    usable, why = vault.readable()
    if not usable:
        return Finding(BAD, "Credentials", why,
                       fix=f"fix or move {shown}. munim will not overwrite "
                           f"credentials it cannot read")
    if not where.exists():
        return Finding(OK, "Credentials", f"{shown} (none stored yet)")

    mode = stat.S_IMODE(where.stat().st_mode)
    if mode & 0o077:
        return Finding(WARN, "Credentials",
                       f"{shown} is mode {mode:o}, readable by others",
                       fix=f"chmod 600 {shown}")
    return Finding(OK, "Credentials", f"{shown}, mode {mode:o}")


def _clients(registry: Registry) -> list[Finding]:
    records = registry.clients()
    if not records:
        return [Finding(WARN, "Clients", "none registered yet",
                        fix='ask your agent: check <a domain you look after>')]

    from munim import vault

    # The names live in the registry and are worth showing even when the
    # credentials cannot be read. `connections` raises rather than reporting
    # everybody as disconnected, which is right for a library and wrong for a
    # diagnosis: `_keychain` above already says what is wrong with the store, so
    # repeating it once per client would bury it.
    usable, _ = vault.readable()
    if not usable:
        return [Finding(OK, "Clients", f"{len(records)} registered"),
                *[Finding(WARN, f"  {r.name}", "cannot tell, the store is "
                          "unreadable") for r in records]]

    backend = KeychainBackend()
    out = [Finding(OK, "Clients", f"{len(records)} registered")]
    for record in records:
        # Two ways a client can be connected, and they are not the same thing:
        # a stored API credential this tool calls with, or a session with the
        # provider's own MCP server. Reporting only the first hid the second.
        # `doctor` was the only reader that knew; now they all ask one function.
        keys, sessions = connections(record.id, backend)

        parts = []
        if keys:
            parts.append(", ".join(keys))
        if sessions:
            parts.append(", ".join(f"{p} (mcp)" for p in sessions))

        if parts:
            out.append(Finding(OK, f"  {record.name}", " · ".join(parts)))
        else:
            out.append(Finding(
                WARN, f"  {record.name}", "nothing connected",
                fix=f'munim connect "{record.name}" cloudflare'))
    return out


def _oauth_apps() -> list[Finding]:
    """Whether a provider can be logged in to, and by which of the two routes.

    A registered application is no longer the only way in. Every provider that
    runs its own MCP server registers a client on demand, so connecting needs
    nothing set up at all, and telling someone to go and register an
    application when they do not have to is worse than saying nothing.
    """
    from munim.remote.servers import SERVERS

    out = []

    # Both lists, because they answer different halves of the question. A
    # provider in OAUTH_PROVIDERS can be reached by registering an application;
    # a provider whose auth kind is `app` *must* be. Reading only the first is
    # how doctor came to say "Everything is set up" on a machine where gmail
    # and stitch could not be connected at all.
    needs_app = {name for name, server in SERVERS.items() if server.auth == "app"}

    for provider in sorted(set(OAUTH_PROVIDERS) | needs_app):
        client_id = os.environ.get(f"{provider.upper()}_OAUTH_CLIENT_ID")
        has_mcp = provider in SERVERS and provider not in needs_app
        if client_id:
            out.append(Finding(OK, f"Login: {provider}",
                               "registered application"))
        elif has_mcp:
            out.append(Finding(
                OK, f"Login: {provider}",
                "ready, through the provider's own MCP server"))
        elif provider in needs_app:
            # accounts.google.com publishes no registration endpoint, so this
            # one cannot be issued on demand however long you wait.
            server = SERVERS[provider]
            out.append(Finding(
                WARN, f"Login: {provider}",
                "needs an application registered by hand",
                # Led with `uv run python scripts/setup_google_oauth.py`, which
                # only exists in a source checkout: pyproject ships src/munim
                # and nothing else. The advice was undoable by exactly the
                # person reading it, somebody who installed the package.
                fix=f"{server.register_at}, Desktop app, redirect "
                    f"{REDIRECT_URI}, then `munim config app set {provider} "
                    f"--client-id ...`, which prompts for the secret and stores "
                    f"both in your keychain. From a source checkout, "
                    f"scripts/setup_google_oauth.py does the first half"))
        else:
            out.append(Finding(
                WARN, f"Login: {provider}", "no application, and no MCP server",
                fix=f"register an app with redirect {REDIRECT_URI}, then "
                    f"`munim config set {provider} --client-id ...`, or paste "
                    f"a key with `munim connect <client> {provider} --token`"))

    # Resend publishes no OAuth authorization endpoint of its own, so it is not
    # in OAUTH_PROVIDERS and would otherwise go unmentioned. It runs an MCP
    # server, which is the whole reason it needs no setup.
    if "resend" in SERVERS:
        out.append(Finding(OK, "Login: resend",
                           "ready, through the provider's own MCP server"))
    else:
        out.append(Finding(OK, "Login: resend",
                           "key only: Resend publishes no OAuth endpoint"))
    return out


def _room() -> Finding:
    """There is nothing to build. The room is one page and one module, shipped
    as they are written, so the only way this fails is a broken install."""
    static = Path(__file__).parent / "room" / "static" / "index.html"
    if static.exists():
        return Finding(OK, "Control room", "ready")
    return Finding(WARN, "Control room", "missing",
                   fix="reinstall munim; the control room ships with it")


# How long one provider gets to answer before the probe gives up on it. Short
# on purpose: this runs on every `doctor`, and a provider that has not answered
# in this long is not going to make the report more useful by answering later.
PROBE_TIMEOUT = 8.0


async def _probe_one(client_id: str, name: str, provider: str) -> tuple | None:
    """(name, provider, why) if this session cannot be opened, else None."""
    import asyncio

    from munim.remote.session import NeedsLogin, NoRemoteServer, session_for

    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            async with session_for(client_id, provider, allow_login=False,
                                   verify=False) as session:
                await session.list_tools()
        return None
    except NeedsLogin:
        return (name, provider, "the session expired")
    except NoRemoteServer:
        # Nothing to probe rather than something broken.
        return None
    except (TimeoutError, asyncio.TimeoutError):
        return (name, provider, f"no answer in {PROBE_TIMEOUT:.0f}s")
    except Exception as other:
        # Offline, DNS down, a provider having an outage. Reported as what it
        # is rather than as an expired session, because telling somebody to
        # reconnect when their wifi is off sends them through a browser login
        # for nothing.
        return (name, provider, f"could not be reached ({type(other).__name__})")


def _sessions(registry: Registry) -> list[Finding]:
    """Which stored sessions actually still open.

    Everything else in this file reads local state. This one goes out to each
    provider, because a dead session is not visible any other way: OAuth grants
    a token and says nothing more, and the only authority on whether a
    credential still works is the party that issued it.

    That is a real cost and it is why the checks run concurrently. Serially
    this is one round trip after another and grows with every client; together
    it is bounded by the slowest provider, so a person with eight clients waits
    about as long as a person with one.
    """
    import asyncio

    backend = KeychainBackend()
    work = []
    for record in registry.clients():
        try:
            _, sessions = connections(record.id, backend)
        except Exception:
            continue    # _keychain already reports an unreadable store
        work += [(record.id, record.name, p) for p in sessions]

    if not work:
        return []

    async def everything():
        return await asyncio.gather(*(_probe_one(*item) for item in work))

    try:
        results = asyncio.run(everything())
    except RuntimeError:
        # Already inside a loop, which doctor never is from the CLI. Skipping
        # beats crashing the whole report over one check.
        return []

    dead = [r for r in results if r is not None]
    if not dead:
        return [Finding(OK, "Sessions",
                        f"{len(work)} checked, all still open")]

    # One line each rather than a single finding listing them. Each dead
    # session has its own fix, and a semicolon-separated run of commands is
    # something a person has to unpick before they can act on any of it.
    return [Finding(WARN, "Session", f"{name}/{provider}: {why}",
                    f'munim connect "{name}" {provider}')
            for name, provider, why in dead]


def run(registry: Registry | None = None, verbose: bool = False) -> int:
    """What is wrong with this installation, and nothing else.

    This used to print thirteen lines on a healthy machine: every provider's
    login route, every client, the keychain backend, the control room. All true,
    none of it a problem, each with a fix beside it, closing on "1 thing(s) need
    fixing before this works" when the thing worked fine.

    `audit_all_clients` has been documented from the start as silent when
    everything passes and a list when it does not. `doctor` now behaves the same
    way. What is connected is inventory rather than health, `munim clients`
    already answers it, and it is behind --verbose here.
    """
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")

    from munim import settings
    from munim.cli import installed_version

    # Timed, because one of these dominates and it is not ours. `claude mcp
    # list` takes about fifteen seconds to start, which is most of the runtime
    # of this command, and a report that sits silent for that long looks hung
    # rather than busy. Saying which check is slow also stops somebody
    # optimising the wrong thing, which is how it came to run twice.
    timings: list[tuple[str, float]] = []

    def timed(label, fn):
        started = time.perf_counter()
        try:
            return fn()
        finally:
            timings.append((label, time.perf_counter() - started))

    print(f"munim {installed_version()}, python "
          f"{sys.version_info.major}.{sys.version_info.minor}, agents "
          f"{'on' if settings.ai().enabled else 'off'}"
          f"{'' if settings.ai().enabled else ' (local)'}", flush=True)

    # Only on a terminal. A progress line redrawn with \r is noise in a pipe or
    # a log, where the carriage return is not honoured and the half-erased text
    # survives into whatever reads it.
    health = [timed("config", _config), timed("settings", _settings_file),
              *timed("agents", _agents)]

    health.append(timed("coding agent", _mcp_registered))
    health += timed("interpreter", _one_interpreter)
    health += [timed("control room", _room), timed("keychain", _keychain)]
    # The one check that leaves the machine. Stored credentials say nothing
    # about whether they still work, so every other report here called two dead
    # sessions "connected" and only a failed call ever revealed otherwise.
    health += timed("sessions", lambda: _sessions(registry))
    inventory = ([*timed("providers", _oauth_apps),
                  *timed("clients", lambda: _clients(registry))]
                 if verbose else [])

    print()

    shown = [f for f in health if f.status != OK or verbose] + inventory
    if shown:
        width = max(len(f.what) for f in shown) + 2
        for f in shown:
            print(f"{MARK[f.status]} {f.what.ljust(width)}{f.detail}")
            if f.fix:
                print(f"{' ' * (width + 2)}→ {f.fix}")
        print()

    # Counted over what was printed, not over the health checks alone. With
    # --verbose the inventory findings are shown and were not counted, so the
    # report displayed two `!` lines and then closed with "No problems found".
    # A summary that describes a different set of findings than the one on
    # screen is worse than no summary.
    counted = health + inventory
    bad = sum(1 for f in counted if f.status == BAD)
    warn = sum(1 for f in counted if f.status == WARN)

    total = sum(seconds for _, seconds in timings)
    slowest, took = max(timings, key=lambda pair: pair[1])
    took_note = (f" ({total:.0f}s, most of it the {slowest} check)"
                 if total >= 3 and took > total / 2 else f" ({total:.1f}s)")

    if bad:
        print(f"{bad} problem{'s' if bad > 1 else ''} to fix"
              + (f", and {warn} thing{'s' if warn > 1 else ''} worth a look"
                 if warn else "") + f".{took_note}")
        return 1
    if warn:
        print(f"Working. {warn} thing{'s' if warn > 1 else ''} worth a "
              f"look.{took_note}")
        return 0
    print("No problems found." + ("" if verbose else
          "  Run with --verbose to see what is connected.") + took_note)
    return 0
