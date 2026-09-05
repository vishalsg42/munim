"""`munim doctor`: what is set up, what is not, and the exact next step.

For a tool strangers are meant to install, "it does not work" is the failure that
loses them. Every check here reports the specific missing thing and the one
command or URL that fixes it, rather than a stack trace.
"""

import os
import platform
import shutil
import subprocess
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


_LISTING: list[str] | None = None


def _mcp_listing() -> str:
    """`claude mcp list`, run at most once.

    Two checks need it and each was shelling out separately, which cost about
    fifteen seconds apiece: the whole of `munim doctor` was thirty-three seconds
    to run one subprocess twice. Everything else in the report totals thirty
    milliseconds.
    """
    global _LISTING
    if _LISTING is not None:
        return _LISTING[0]

    executable = shutil.which("claude")
    if not executable:
        _LISTING = [""]
        return ""
    try:
        out = subprocess.run([executable, "mcp", "list"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:
        out = ""
    _LISTING = [out]
    return out


def _mcp_registered() -> Finding:
    # shutil.which resolves the real thing, which on Windows is claude.cmd and
    # would not have been found by passing the bare name to subprocess.
    if not shutil.which("claude"):
        return Finding(WARN, "Coding agent", "claude CLI not found",
                       fix="add munim-mcp to your agent's MCP config by hand")
    out = _mcp_listing()
    for line in out.splitlines():
        if line.strip().startswith("munim"):
            if "✔" in line or "Connected" in line:
                return Finding(OK, "Coding agent", "munim connected")
            return Finding(BAD, "Coding agent", line.strip()[:60],
                           fix="claude mcp remove munim && claude mcp add "
                               "--scope user munim -- "
                               f"{Path(sys.executable).parent / 'munim-mcp'}")
    # --scope user, not the default. Registering per project means the next
    # directory you work in reports munim as missing, which is exactly what
    # somebody hits the first time they use it outside this repo.
    return Finding(BAD, "Coding agent", "munim not registered",
                   fix=f"claude mcp add --scope user munim -- "
                       f"{Path(sys.executable).parent / 'munim-mcp'}"
                       f"   (--scope user makes it available in every project)")


def _mcp_command() -> str:
    """The path the coding agent is configured to spawn, or "".

    Read from `claude mcp list` rather than from the config file, because the
    file layout is the agent's business and the listing is the interface.
    """
    for line in _mcp_listing().splitlines():
        stripped = line.strip()
        if not stripped.startswith("munim"):
            continue
        _, _, rest = stripped.partition(":")
        # `munim: /path/to/munim-mcp  - ✔ Connected`
        return rest.split(" - ")[0].strip()
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
    """Whether there is anywhere to keep a credential.

    Reads degrade to "nothing connected" without one, which is right for a
    library and wrong for a diagnosis: a client that is connected and reads as
    disconnected is the most confusing state this tool can be in, and it should
    say so rather than let somebody reconnect and watch it not stick.
    """
    import keyring
    import keyring.errors

    try:
        keyring.get_password("munim:probe", "probe")
    except keyring.errors.KeyringError as exc:
        return Finding(
            BAD, "Keychain", f"no backend available: {exc}",
            fix="on a headless Linux box, install `keyrings.alt` or run a "
                "secret service. Until then nothing can be connected, and "
                "anything already connected reads as disconnected.")
    return Finding(OK, "Keychain", f"{keyring.get_keyring().name}")


def _clients(registry: Registry) -> list[Finding]:
    records = registry.clients()
    if not records:
        return [Finding(WARN, "Clients", "none registered yet",
                        fix='ask your agent: check <a domain you look after>')]

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
    slow = shutil.which("claude") is not None and sys.stderr.isatty()
    if slow:
        print("  asking your coding agent which MCP servers are registered…",
              end="\r", file=sys.stderr, flush=True)

    health = [timed("config", _config), timed("settings", _settings_file),
              *timed("agents", _agents), timed("coding agent", _mcp_registered),
              *timed("interpreter", _one_interpreter), timed("control room", _room),
              timed("keychain", _keychain)]
    inventory = ([*timed("providers", _oauth_apps),
                  *timed("clients", lambda: _clients(registry))]
                 if verbose else [])

    if slow:
        print(" " * 60, end="\r", file=sys.stderr, flush=True)

    print()

    shown = [f for f in health if f.status != OK or verbose] + inventory
    if shown:
        width = max(len(f.what) for f in shown) + 2
        for f in shown:
            print(f"{MARK[f.status]} {f.what.ljust(width)}{f.detail}")
            if f.fix:
                print(f"{' ' * (width + 2)}→ {f.fix}")
        print()

    bad = sum(1 for f in health if f.status == BAD)
    warn = sum(1 for f in health if f.status == WARN)

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
