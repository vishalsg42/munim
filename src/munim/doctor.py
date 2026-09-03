"""`munim doctor` — what is set up, what is not, and the exact next step.

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
from munim.container import Container, KeychainBackend
from munim.env import load as load_env
from munim.registry import Registry

PROVIDERS = ("cloudflare", "vercel", "resend")

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
    if not shutil.which("claude"):
        return Finding(WARN, "Coding agent", "claude CLI not found",
                       fix="add munim-mcp to your agent's MCP config by hand")
    try:
        out = subprocess.run(["claude", "mcp", "list"], capture_output=True,
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


def _clients(registry: Registry) -> list[Finding]:
    records = registry.clients()
    if not records:
        return [Finding(WARN, "Clients", "none registered yet",
                        fix='ask your agent: check <a domain you look after>')]
    backend = KeychainBackend()
    out = [Finding(OK, "Clients", f"{len(records)} registered")]
    for record in records:
        container = Container(record.name, backend)
        connected = [p for p in PROVIDERS if container.has(p)]
        if connected:
            out.append(Finding(OK, f"  {record.name}", ", ".join(connected)))
        else:
            out.append(Finding(WARN, f"  {record.name}", "nothing connected",
                               fix=f'munim connect "{record.name}" cloudflare'))
    return out


def _oauth_apps() -> list[Finding]:
    out = []
    for provider in sorted(OAUTH_PROVIDERS):
        client_id = os.environ.get(f"{provider.upper()}_OAUTH_CLIENT_ID")
        if client_id:
            out.append(Finding(OK, f"OAuth app: {provider}", "registered"))
        else:
            out.append(Finding(
                WARN, f"OAuth app: {provider}", "not registered — key entry still works",
                fix=f"register an app with redirect {REDIRECT_URI}, then set "
                    f"{provider.upper()}_OAUTH_CLIENT_ID in .env"))
    out.append(Finding(OK, "OAuth app: resend",
                       "not applicable — Resend publishes no OAuth endpoint"))
    return out


def _room() -> Finding:
    static = Path(__file__).parent / "room" / "static" / "index.html"
    if static.exists():
        return Finding(OK, "Control room", "built")
    return Finding(WARN, "Control room", "not built",
                   fix="cd room && npm install && npm run build")


def run(registry: Registry | None = None) -> int:
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")
    findings = [_model(), _mcp_registered(), _room(),
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
