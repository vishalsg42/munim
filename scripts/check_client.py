"""Run the check catalogue against one client and write the owner's report.

The product's own surface is the MCP server: a coding agent calls `check`.
This is the same code path with no agent in front of it, for a terminal and
for anyone who wants to see the catalogue run without wiring up a model.

    uv run python scripts/check_client.py "Acme Ltd"
"""

import asyncio
import sys
import time
from pathlib import Path

from munim.agent.launch import run_checks
from munim.container import Container, KeychainBackend
from munim.registry import Registry
from munim.report import write as write_report
from munim.runlog import RunLog, new_run_id


async def main() -> int:
    if len(sys.argv) < 2:
        print('usage: check_client.py "<client>"', file=sys.stderr)
        return 2

    who = sys.argv[1]
    registry = Registry(Path.home() / ".munim" / "registry.json")
    record = registry.get(who)
    container = Container.for_client(registry, who, KeychainBackend())
    log = RunLog(new_run_id())

    began = time.time()
    results = await run_checks(record.domain, record.name, log,
                               container=container, client_id=record.id)
    failed = [r for r in results if r.status == "fail"]
    page = write_report(log, domain=record.domain, business=record.name)
    log.append(client=record.name, stage="verify", kind="run_done",
               human_text=f"Finished with {record.domain}.")

    passed = sum(r.status == "pass" for r in results)
    ran = sum(r.status != "skip" for r in results)
    print(f"\n  {record.name} · {record.domain} · {time.time() - began:.1f}s")
    print(f"  {passed} of {ran} checks passed\n")
    for r in failed:
        print(f"  FAIL  {r.human_text}")
    print(f"\n  report  {page}")
    print(f"  watch   http://127.0.0.1:8977/\n")
    return 1 if failed else 0


raise SystemExit(asyncio.run(main()))
