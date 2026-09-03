# Multi-client MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local stdio MCP server that gives any coding agent per-client, credential-isolated access to several clients' Vercel / Cloudflare / Resend / Supabase accounts, with a Strands agent that launches a new client end to end and verifies the result.

**Architecture:** One `Container` per client holds that client's credentials, tools and memory, behind a backend interface (`KeychainBackend` now, `AgentCoreBackend` later). Provider adapters implement one contract and are the only code that talks to a provider. Enumeration and checks are deterministic; a Strands agent supplies judgement — polling, diagnosing, and deciding when to escalate. Cross-client reads fan out across containers; writes require naming one client.

**Tech Stack:** Python ≥3.10 · `strands-agents` 1.54.0 · `mcp` 1.x · `keyring` · `httpx` · `dnspython` · `pytest`

**Spec:** `docs/superpowers/specs/2026-09-03-multi-client-mcp-design.md`
**Decisions:** `docs/DECISIONS.md` · **Contest analysis:** `docs/HACKATHON.md`

## Global Constraints

- **Python ≥ 3.10.** The machine currently has 3.9.6. `strands-agents` requires `>=3.10`.
- **`mcp>=1.23.0,<2.0.0`.** `strands-agents` 1.54.0 pins this. PyPI's latest `mcp` is **2.1.1** — installing it breaks Strands. Pin explicitly.
- **No stubs.** No placeholder implementations, no fake data path dressed as real. An unimplemented provider is *absent*, not faked. (`web-mcp-2026/docs/PROJECT-RULES.md`)
- **No ambient client.** Every tool that touches a provider takes `client` as its first argument. An implicit "current client" is how the wrong account gets written to.
- **No credential ever crosses the MCP boundary.** No tool returns a token. Tokens are read at the point of the API call and never logged.
- **Licence: MIT or Apache-2.0**, detectable in the repo's About section (hackathon requirement).
- **Real secrets never committed.** `.gitignore` excludes `.env*`, `*.token`, `fixtures/real/`.

---

# Phase 0 — Day-one gates

These four tasks exist to falsify the design cheaply. **Do not build Phase 1 until all four pass.**
`google-agentic-cinema` D28: the miss was writing code against a schema nobody had queried.
Each gate is one command that settles a question currently answered by assumption.

---

### Task 1: Toolchain and a Strands agent that actually runs

**Files:**
- Create: `pyproject.toml`
- Create: `src/mcpc/__init__.py`
- Create: `scripts/gate_strands.py`
- Create: `LICENSE` (MIT)
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: an importable `mcpc` package; a working Bedrock credential chain

- [ ] **Step 1: Install Python 3.11 and uv**

```bash
brew install python@3.11
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

- [ ] **Step 2: Write `pyproject.toml` with the pinned dependency set**

```toml
[project]
name = "mcpc"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "strands-agents==1.54.0",
    "mcp>=1.23.0,<2.0.0",
    "keyring>=25.7.0",
    "httpx>=0.28.1",
    "dnspython>=2.7.0",
    "pydantic>=2.4.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "respx>=0.22"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mcpc"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Create the package and install**

```bash
mkdir -p src/mcpc tests scripts
touch src/mcpc/__init__.py
uv venv --python 3.11
uv pip install -e ".[dev]"
```

- [ ] **Step 4: Verify the mcp pin actually held**

```bash
uv pip show mcp | grep -i version
```

Expected: a `1.x` version. **If this prints 2.x, stop** — Strands will fail at import.

- [ ] **Step 5: Write the Bedrock gate script**

```python
# scripts/gate_strands.py
"""Day-one gate: does a Strands agent reach Bedrock and use a tool?"""
from strands import Agent, tool


@tool
def add_two_numbers(a: int, b: int) -> int:
    """Add two numbers together and return the sum."""
    return a + b


def main() -> None:
    agent = Agent(tools=[add_two_numbers])
    result = agent("What is 17 plus 25? Use the tool.")
    text = str(result)
    print(text)
    assert "42" in text, f"GATE FAILED: expected 42 in response, got: {text}"
    print("GATE PASSED: Strands reached Bedrock and called a tool.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run it**

```bash
uv run python scripts/gate_strands.py
```

Expected: `GATE PASSED`.
If it fails with `AccessDeniedException`, enable Claude Sonnet model access in the Bedrock console for your region and set `AWS_REGION`.

- [ ] **Step 7: Write LICENSE (MIT) and .gitignore**

```bash
cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
.env
.env.*
*.token
fixtures/real/
.pytest_cache/
EOF
```

Write an MIT `LICENSE` file with the current year and the author's name.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src tests scripts LICENSE .gitignore
git commit -m "Gate: a Strands agent reaches Bedrock and calls a tool"
```

---

### Task 2: An MCP server Claude Code actually connects to

**Files:**
- Create: `src/mcpc/server.py`
- Create: `tests/test_server.py`

**Interfaces:**
- Consumes: `mcpc` package from Task 1
- Produces: `mcpc.server:build_server() -> FastMCP`, and a `mcpc` console entry point

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
from mcpc.server import build_server


async def test_server_exposes_list_clients():
    server = build_server()
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert "list_clients" in names
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_server.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'mcpc.server'`

- [ ] **Step 3: Write the minimal server**

```python
# src/mcpc/server.py
"""The MCP surface. Transport only - no provider logic lives here."""
from mcp.server.fastmcp import FastMCP


def build_server() -> FastMCP:
    server = FastMCP("mcpc")

    @server.tool()
    def list_clients() -> list[str]:
        """List the client containers that are registered."""
        return []

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_server.py -v
```

Expected: PASS

- [ ] **Step 5: Add the console entry point to `pyproject.toml`**

Add this block, then re-install with `uv pip install -e ".[dev]"`:

```toml
[project.scripts]
mcpc = "mcpc.server:main"
```

- [ ] **Step 6: Register with Claude Code and confirm the connection**

```bash
claude mcp add mcpc -- "$(pwd)/.venv/bin/mcpc"
claude mcp list
```

Expected: `mcpc` listed and connected. **This is the gate** — if Claude Code cannot spawn it, nothing downstream matters.

- [ ] **Step 7: Commit**

```bash
git add src/mcpc/server.py tests/test_server.py pyproject.toml
git commit -m "Gate: Claude Code connects to the server over stdio"
```

---

### Task 3: Prove a container cannot see another client's credentials

**Files:**
- Create: `src/mcpc/container.py`
- Create: `tests/test_isolation.py`

This is the security claim of the whole project. It gets a test on day one, not day eight.

**Interfaces:**
- Consumes: nothing
- Produces:
  - `CredentialBackend` protocol: `get(client: str, provider: str) -> str | None`
  - `KeychainBackend(service_prefix: str)` implementing it
  - `Container(client: str, backend: CredentialBackend)` with `.credential(provider: str) -> str`
  - `UnknownCredential(Exception)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_isolation.py
import pytest
from mcpc.container import Container, UnknownCredential


class FakeBackend:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def get(self, client: str, provider: str):
        self.calls.append((client, provider))
        return self.store.get((client, provider))


def test_container_reads_its_own_credential():
    backend = FakeBackend({("acme", "vercel"): "acme-token"})
    assert Container("acme", backend).credential("vercel") == "acme-token"


def test_container_cannot_reach_another_clients_credential():
    backend = FakeBackend({
        ("acme", "vercel"): "acme-token",
        ("bharat", "vercel"): "bharat-token",
    })
    acme = Container("acme", backend)
    with pytest.raises(UnknownCredential):
        acme.credential("cloudflare")
    # Every lookup this container made was scoped to its own client.
    assert all(client == "acme" for client, _ in backend.calls)


def test_container_never_exposes_the_raw_backend():
    backend = FakeBackend({("acme", "vercel"): "acme-token"})
    acme = Container("acme", backend)
    assert "bharat-token" not in repr(acme)
    assert "acme-token" not in repr(acme)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_isolation.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'mcpc.container'`

- [ ] **Step 3: Write the implementation**

```python
# src/mcpc/container.py
"""Per-client credential isolation.

A Container is bound to exactly one client at construction and can never widen.
Backends are swappable: KeychainBackend now, AgentCoreBackend when hosted (D14).
"""
from typing import Protocol

import keyring


class UnknownCredential(Exception):
    """No credential is stored for this client and provider."""


class CredentialBackend(Protocol):
    def get(self, client: str, provider: str) -> str | None: ...


class KeychainBackend:
    """OS keychain. Credentials never leave the machine (D14)."""

    def __init__(self, service_prefix: str = "mcpc") -> None:
        self._prefix = service_prefix

    def get(self, client: str, provider: str) -> str | None:
        return keyring.get_password(f"{self._prefix}:{provider}", client)

    def set(self, client: str, provider: str, secret: str) -> None:
        keyring.set_password(f"{self._prefix}:{provider}", client, secret)


class Container:
    """One client's world. Bound at construction; cannot widen."""

    def __init__(self, client: str, backend: CredentialBackend) -> None:
        self._client = client
        self._backend = backend

    @property
    def client(self) -> str:
        return self._client

    def credential(self, provider: str) -> str:
        secret = self._backend.get(self._client, provider)
        if secret is None:
            raise UnknownCredential(
                f"no {provider} credential for client {self._client!r}"
            )
        return secret

    def __repr__(self) -> str:
        # Never render a secret, and never render another client's name.
        return f"<Container client={self._client!r}>"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_isolation.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/mcpc/container.py tests/test_isolation.py
git commit -m "Gate: a container cannot reach another client's credentials"
```

---

### Task 4: Probe the two provider APIs the launch depends on

**Files:**
- Create: `scripts/probe_vercel.py`
- Create: `scripts/probe_resend.py`
- Create: `docs/PROBES.md`

Both probes run against **real accounts you own**. The design assumes each provider hands
back what the next provider needs; §3 of the spec is currently wrong about Vercel and this
task establishes what is actually true.

**Interfaces:**
- Consumes: nothing
- Produces: `docs/PROBES.md` recording verbatim, real responses that Tasks 8 and 9 are written against

- [ ] **Step 1: Write the Vercel probe**

```python
# scripts/probe_vercel.py
"""What does Vercel return when a domain is added to a project?

Docs say `verification[]` is an ownership TXT challenge, NOT the A/CNAME
targets that point traffic. This settles what we actually get.
"""
import json
import os
import sys

import httpx

TOKEN = os.environ["VERCEL_TOKEN"]
PROJECT = os.environ["VERCEL_PROJECT"]
DOMAIN = os.environ["PROBE_DOMAIN"]
TEAM = os.environ.get("VERCEL_TEAM_ID")

params = {"teamId": TEAM} if TEAM else {}
headers = {"Authorization": f"Bearer {TOKEN}"}

add = httpx.post(
    f"https://api.vercel.com/v10/projects/{PROJECT}/domains",
    headers=headers, params=params, json={"name": DOMAIN}, timeout=30,
)
print("=== POST /v10/projects/{p}/domains ===")
print(add.status_code)
print(json.dumps(add.json(), indent=2))

cfg = httpx.get(
    f"https://api.vercel.com/v6/domains/{DOMAIN}/config",
    headers=headers, params=params, timeout=30,
)
print("=== GET /v6/domains/{d}/config ===")
print(cfg.status_code)
print(json.dumps(cfg.json(), indent=2))

print("\nANSWER THESE IN docs/PROBES.md:")
print("1. Does any response contain the A/CNAME target to point at Vercel?")
print("2. If not, are 76.76.21.21 / cname.vercel-dns.com the constants to use?")
print("3. What does config return while DNS is still wrong (misconfigured flag)?")
sys.exit(0)
```

- [ ] **Step 2: Run the Vercel probe**

```bash
VERCEL_TOKEN=... VERCEL_PROJECT=... PROBE_DOMAIN=... uv run python scripts/probe_vercel.py
```

Expected: two JSON bodies. Read them; do not assume.

- [ ] **Step 3: Write the Resend probe**

```python
# scripts/probe_resend.py
"""Does creating a Resend domain return the DKIM/SPF records programmatically?

Docs say yes - a `records` array with record/name/type/value/ttl/status.
This confirms it against a real account and captures the exact shape.
"""
import json
import os

import httpx

KEY = os.environ["RESEND_API_KEY"]
DOMAIN = os.environ["PROBE_DOMAIN"]

resp = httpx.post(
    "https://api.resend.com/domains",
    headers={"Authorization": f"Bearer {KEY}"},
    json={"name": DOMAIN},
    timeout=30,
)
print("=== POST /domains ===")
print(resp.status_code)
body = resp.json()
print(json.dumps(body, indent=2))

records = body.get("records", [])
print(f"\nrecords returned: {len(records)}")
for r in records:
    print(f"  {r.get('record'):10} {r.get('type'):6} {r.get('name')} -> {str(r.get('value'))[:60]}")

print("\nANSWER THESE IN docs/PROBES.md:")
print("1. Is every record needed present (SPF + all DKIM)?")
print("2. Is any DKIM value long enough to need TXT chunking?")
print("3. Do the names come back relative (e.g. 'send') or absolute?")
```

- [ ] **Step 4: Run the Resend probe**

```bash
RESEND_API_KEY=... PROBE_DOMAIN=... uv run python scripts/probe_resend.py
```

- [ ] **Step 5: Record the findings**

Create `docs/PROBES.md` with the real, verbatim responses and the answers to every
numbered question above. **If Vercel does not return the A/CNAME target, record the
constants used instead and why** — then correct §3 of the spec, which currently claims
"Vercel emits A/CNAME values."

- [ ] **Step 6: Commit**

```bash
git add scripts/probe_vercel.py scripts/probe_resend.py docs/PROBES.md
git commit -m "Gate: record what the provider APIs actually return"
```

---

## Phase 0 exit criteria

All four must hold before Phase 1 begins:

- [ ] `scripts/gate_strands.py` prints `GATE PASSED`
- [ ] `claude mcp list` shows `mcpc` connected
- [ ] `tests/test_isolation.py` — 3 passed
- [ ] `docs/PROBES.md` contains real responses, and §3 of the spec has been corrected if the Vercel finding requires it

**Phase 1 tasks are deliberately not written in detail yet.** Task 4 can invalidate the
adapter contract's shape, and writing detailed tasks against an unprobed API is precisely
the mistake recorded in `google-agentic-cinema` D28. Phase 1 is expanded once the gates pass.

---

# Phase 1 — Foundation (outline; expanded after Phase 0)

Interfaces are fixed now so Phase 0 work does not need rewriting.

**Task 5 — Client registry.** `src/mcpc/registry.py`. `Registry.clients() -> list[ClientRecord]`,
`ClientRecord(name: str, providers: list[str], domain: str | None)`. JSON at
`~/.mcpc/registry.json`. **Secret references only, never secrets** — the mcpwarden design is
right about this (D15).

**Task 6 — Adapter contract.** `src/mcpc/adapters/base.py`. `Adapter` protocol:
`name: str`, `enumerate(container: Container) -> list[Asset]`. `Asset` carries `client`,
`provider`, `kind`, `identifier` and optional facets (`expiry`, `reachability`, `exposure`,
`permission`, `freshness`) per spec §5.

**Tasks 7–10 — Adapters,** one per task, each with recorded-response tests via `respx`:
Cloudflare, Vercel, Resend, Supabase. Written against `docs/PROBES.md`, not against docs.

**Task 11 — Verification catalogue.** `src/mcpc/checks/`. Every check in spec §7 as a pure
function over assets plus live DNS: duplicate SPF, SPF lookup count > 10, DKIM proxied,
DKIM chunking, missing DMARC, nameserver delegation, Cloudflare SSL mode, missing www,
CAA block, env-var-without-redeploy, wrong environment scope, Supabase direct-port.
Deterministic — **no model involvement** (D7).

**Task 12 — The Strands launch agent.** `src/mcpc/agent/launch.py`. Adapter calls as Strands
tools, structured output, per-stage verification, escalation when a human is required.

**Task 13 — Cross-client reads.** `find_across_clients`, fanning out over containers in
parallel via a Strands multi-agent pattern. **Read-only** (D5).

## Deferred

`AgentCoreBackend` (Identity + Runtime) behind the same `CredentialBackend` protocol — D14.
The watcher — D8.
