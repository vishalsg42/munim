"""`munim doctor`: what is set up, what is not, and the exact next step.

For a tool strangers are meant to install, "it does not work" is the failure that
loses them. Every check here reports the specific missing thing and the one
command or URL that fixes it, rather than a stack trace.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from munim.connect.oauth import PROVIDERS as OAUTH_PROVIDERS
from munim.connect.oauth import REDIRECT_URI
from munim.connected import connections
from munim.container import KeychainBackend
from munim.env import load as load_env
from munim.registry import Registry


OK, WARN, BAD = "ok", "warn", "bad"
MARK = {OK: "✓", WARN: "!", BAD: "✗"}


@dataclass
class Finding:
    status: str
    what: str
    detail: str = ""
    fix: str = ""


def _model() -> Finding:
    load_env()
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return Finding(OK, "Model host", "Gemini")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Finding(OK, "Model host", "Anthropic")
    if os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ACCESS_KEY_ID"):
        return Finding(WARN, "Model host", "AWS credentials present; Bedrock untested",
                       fix="munim doctor --probe-model")
    return Finding(BAD, "Model host", "none configured",
                   fix="put GEMINI_API_KEY=... in .env (any Strands provider works)")


def _mcp_registered() -> Finding:
    # shutil.which resolves the real thing, which on Windows is claude.cmd and
    # would not have been found by passing the bare name to subprocess.
    executable = shutil.which("claude")
    if not executable:
        return Finding(WARN, "Coding agent", "claude CLI not found",
                       fix="add munim-mcp to your agent's MCP config by hand")
    try:
        out = subprocess.run([executable, "mcp", "list"], capture_output=True,
                             text=True, timeout=20).stdout
    except Exception:
        return Finding(WARN, "Coding agent", "could not list MCP servers")
    for line in out.splitlines():
        if line.strip().startswith("munim"):
            if "✔" in line or "Connected" in line:
                return Finding(OK, "Coding agent", "munim connected")
            return Finding(BAD, "Coding agent", line.strip()[:60],
                           fix="claude mcp remove munim && claude mcp add munim -- "
                               f"{Path(sys.executable).parent / 'munim-mcp'}")
    return Finding(BAD, "Coding agent", "munim not registered",
                   fix=f"claude mcp add munim -- {Path(sys.executable).parent / 'munim-mcp'}")


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
    for provider in sorted(OAUTH_PROVIDERS):
        client_id = os.environ.get(f"{provider.upper()}_OAUTH_CLIENT_ID")
        has_mcp = provider in SERVERS
        if client_id:
            out.append(Finding(OK, f"Login: {provider}",
                               "registered application"))
        elif has_mcp:
            out.append(Finding(
                OK, f"Login: {provider}",
                "ready, through the provider's own MCP server"))
        else:
            out.append(Finding(
                WARN, f"Login: {provider}", "no application, and no MCP server",
                fix=f"register an app with redirect {REDIRECT_URI}, then set "
                    f"{provider.upper()}_OAUTH_CLIENT_ID in .env, or paste a "
                    f"key with `munim connect <client> {provider} --token`"))

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


def run(registry: Registry | None = None) -> int:
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")
    findings = [_model(), _mcp_registered(), _room(), _keychain(),
                *_oauth_apps(), *_clients(registry)]

    width = max(len(f.what) for f in findings) + 2
    for f in findings:
        print(f"{MARK[f.status]} {f.what.ljust(width)}{f.detail}")
        if f.fix:
            print(f"{' ' * (width + 2)}→ {f.fix}")

    bad = sum(1 for f in findings if f.status == BAD)
    warn = sum(1 for f in findings if f.status == WARN)
    print()
    if bad:
        print(f"{bad} thing(s) need fixing before this works.")
        return 1
    if warn:
        print(f"Working. {warn} thing(s) would make it better.")
        return 0
    print("Everything is set up.")
    return 0
