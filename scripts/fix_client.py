"""Check a client's domain, then repair what can be repaired safely.

The same graph the `fix` MCP tool runs, with no agent in front of it.

    uv run python scripts/fix_client.py "Acme Ltd"
"""

import asyncio
import sys
from pathlib import Path

from munim.agent.graph import fix
from munim.container import Container, KeychainBackend
from munim.registry import Registry
from munim.runlog import RunLog, new_run_id


async def main() -> int:
    who = sys.argv[1]
    registry = Registry(Path.home() / ".munim" / "registry.json")
    record = registry.get(who)
    container = Container.for_client(registry, who, KeychainBackend())
    log = RunLog(new_run_id())

    out = await fix(record.domain, record.name, client_id=record.id,
                    container=container, log=log)

    print(f"\n  {out['client']} · {out['domain']}\n")
    if out["failing"]:
        for f in out["failing"]:
            print(f"  FAIL  {f['says'] if isinstance(f, dict) else f}")
        print()
    print(f"  {out['why']}\n")
    if out.get("said"):
        head, _, body = str(out["said"]).partition(": ")
        print(f"  {head.upper()} SAYS\n")
        import textwrap
        for para in body.split("\n\n"):
            for line in textwrap.wrap(para.strip(), width=96):
                print(f"  {line}")
            print()
    return 0


raise SystemExit(asyncio.run(main()))
