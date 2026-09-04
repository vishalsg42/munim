"""Read two real provider accounts in one process, with no logout between them.

D15's defensible claim is that no prior work performs a task spanning two
client accounts. This is the probe that makes that claim checkable rather than
asserted: it holds a grant per client, reads both concurrently, and fails if
the two accounts turn out to share anything.

Run it against your own accounts:

    munim connect "Client A" cloudflare
    # sign out of the provider in your browser, then
    munim connect "Client B" cloudflare
    uv run python scripts/cross_account_probe.py

It reads only account and project names, and it writes nothing.

It used to understand one route: a Vercel API key pasted in with --token. That
is the path almost nobody takes, so on a machine where two Cloudflare accounts
were connected by browser login, the probe that exists to prove the central
claim reported that it had nothing to test. It now takes whichever route each
client is connected by, and it looks credentials up by client id, because the
name is a label and this script was reading credentials with it.
"""

import asyncio
import sys
import time
from pathlib import Path

from munim.connected import connections
from munim.container import Container, KeychainBackend
from munim.env import load as load_env
from munim.registry import Registry

# The smallest read that names an account, per provider, over an MCP session.
# Read-only on purpose: a probe that proves isolation by writing would be a
# strange thing to run against a client's production account.
_ACCOUNTS = {
    "cloudflare": ("execute", """async () => {
  const r = await cloudflare.request({ method: 'GET', path: '/accounts' });
  return (r.result || []).map(a => a.id + ' ' + a.name);
}"""),
}


async def _via_session(record, provider: str) -> set[str]:
    """What this client can see, asked over their own MCP session."""
    from munim.remote.identity import _first_named
    from munim.remote.session import session_for

    # allow_login=False on purpose. This script verifies a claim and changes
    # nothing; a version of it that opens a browser and waits five minutes for
    # a callback is not verifying anything. An expired token is reported as
    # "reconnect this client", which is what it is.
    async with session_for(record.id, provider, label=record.name,
                           allow_login=False) as session:
        plan = _ACCOUNTS.get(provider)
        if plan is None:
            from munim.remote.identity import identity_of
            found = await identity_of(session, provider)
            return {found} if found else set()

        tool, code = plan
        answer = await session.call_tool(tool, {"code": code})
        seen: set[str] = set()
        for chunk in getattr(answer, "content", []) or []:
            text = getattr(chunk, "text", "") or ""
            import json
            import re
            match = re.search(r"\[.*\]", text, re.S)
            if not match:
                name = _first_named(text)
                if name:
                    seen.add(name)
                continue
            try:
                for item in json.loads(match.group(0)):
                    seen.add(item if isinstance(item, str) else str(item))
            except ValueError:
                pass
        return seen


async def _via_key(registry, record, provider: str) -> set[str]:
    """What this client can see, using a credential Munim calls with."""
    from munim.adapters.vercel import Vercel

    box = Container.for_client(registry, record.id, KeychainBackend())
    if provider != "vercel":
        raise RuntimeError(f"no key-route reader for {provider}")
    return {p["name"] for p in await Vercel(box).projects()}


async def _look(registry, record, provider: str, route: str):
    from munim.remote.session import NeedsLogin
    try:
        if route == "session":
            return record.name, await _via_session(record, provider)
        return record.name, await _via_key(registry, record, provider)
    except NeedsLogin as exc:
        return record.name, exc


async def main() -> int:
    load_env()
    registry = Registry(Path.home() / ".munim" / "registry.json")
    backend = KeychainBackend()

    # Which provider do at least two clients hold, and by which route each.
    routes: dict[str, dict[str, str]] = {}
    for record in registry.clients():
        keys, sessions = connections(record.id, backend)
        for provider in keys:
            routes.setdefault(provider, {})[record.id] = "key"
        for provider in sessions:
            # A session is the better test: it is a live grant, not a stored
            # string, and it is the route the product actually ships.
            routes.setdefault(provider, {})[record.id] = "session"

    shared = {p: who for p, who in routes.items() if len(who) >= 2}
    if not shared:
        held = {p: len(w) for p, w in routes.items()}
        print("needs one provider connected for two clients. Have: "
              f"{held or 'nothing connected'}", file=sys.stderr)
        return 2

    provider = sorted(shared, key=lambda p: (-len(shared[p]), p))[0]
    who = shared[provider]
    records = [r for r in registry.clients() if r.id in who]
    print(f"provider: {provider}")
    for record in records:
        print(f"  {record.name}: connected by {who[record.id]}")
    print()

    started = time.perf_counter()
    results = await asyncio.gather(
        *(_look(registry, r, provider, who[r.id]) for r in records)
    )
    elapsed = time.perf_counter() - started

    from munim.remote.session import NeedsLogin

    seen: dict[str, set[str]] = {}
    stale = []
    for client, found in results:
        if isinstance(found, NeedsLogin):
            stale.append((client, found))
            print(f"{client}: session expired")
            continue
        seen[client] = found
        print(f"{client}: {len(found)} account(s)/project(s)")
        for item in sorted(found):
            print(f"    {item}")

    if stale:
        print(file=sys.stderr)
        for client, exc in stale:
            print(f"  {exc}", file=sys.stderr)
        print("\nA client whose session has expired proves nothing either way.",
              file=sys.stderr)
        return 2

    print(f"\nread concurrently in {elapsed:.2f}s, no logout between them")

    empty = [c for c, f in seen.items() if not f]
    if empty:
        print(f"FAIL: an empty result proves nothing: {empty}", file=sys.stderr)
        return 1

    # Two grants returning the same thing are one account wearing two names,
    # which would make the whole claim vacuous. This is the assertion.
    names = [r.name for r in records]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = seen[a] & seen[b]
            if overlap:
                print(f"FAIL: {a} and {b} share {sorted(overlap)}",
                      file=sys.stderr)
                return 1

    print(f"PASS: {len(records)} accounts, disjoint, live, in one process")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
