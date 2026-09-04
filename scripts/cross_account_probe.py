"""Read two real provider accounts in one process, with no logout between them.

D15's defensible claim is that no prior work performs a task spanning two client
accounts. This is the probe that makes that claim checkable rather than asserted:
it holds a grant per client, reads both concurrently, and fails if the two
accounts turn out to share anything.

Run it against your own accounts:

    munim connect "Client A" vercel
    munim connect "Client B" vercel
    uv run python scripts/cross_account_probe.py

It reads only project names, and it writes nothing.
"""

import asyncio
import sys
import time
from pathlib import Path

from munim.adapters.vercel import Vercel
from munim.container import Container, KeychainBackend
from munim.env import load as load_env
from munim.registry import Registry


async def projects_for(registry: Registry, name: str) -> tuple[str, list[str]]:
    box = Container.for_client(registry, name, KeychainBackend())
    return name, [p["name"] for p in await Vercel(box).projects()]


async def main() -> int:
    load_env()
    registry = Registry(Path.home() / ".munim" / "registry.json")
    # The keychain is the only record of what is connected.
    backend = KeychainBackend()
    connected = [r.name for r in registry.clients()
                 if backend.get(r.name, "vercel")]
    if len(connected) < 2:
        print(f"needs two clients connected to vercel; have {len(connected)}: "
              f"{connected}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    results = await asyncio.gather(*(projects_for(registry, n) for n in connected))
    elapsed = time.perf_counter() - started

    seen: dict[str, set[str]] = {}
    for client, projects in results:
        seen[client] = set(projects)
        print(f"{client}: {len(projects)} projects")
        for project in sorted(projects):
            print(f"    {project}")

    print(f"\nread concurrently in {elapsed:.2f}s, no logout between them")

    empty = [c for c, p in seen.items() if not p]
    if empty:
        print(f"FAIL: an empty account proves nothing: {empty}", file=sys.stderr)
        return 1

    # Two grants that return the same projects are one account wearing two
    # names, which would make the whole claim vacuous.
    for i, a in enumerate(connected):
        for b in connected[i + 1:]:
            shared = seen[a] & seen[b]
            if shared:
                print(f"FAIL: {a} and {b} share {sorted(shared)}", file=sys.stderr)
                return 1

    print(f"PASS: {len(connected)} accounts, disjoint, live, in one process")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
