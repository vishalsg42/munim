"""The one source of truth for a launch.

Every consumer reads this file: the terminal renderer, the control room, the
`launch_status` tool, and resume-after-failure. It exists because the MCP server
speaks JSON-RPC over stdout (`mcp/server/stdio.py` owns it), so the agent cannot
print progress there without corrupting the protocol, and because a stdio
subprocess dies whenever the coding agent reconnects.

Writing events to a file instead means:
  - the room survives an MCP restart, and can open mid-launch with full replay;
  - "one source, two consumers" is literally true rather than a claim;
  - a launch interrupted halfway leaves a record of what it changed, which is what
    stops a re-run re-adding an SPF record and causing the exact fault this
    product exists to catch.
"""

import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

RUNS_DIR = Path.home() / ".munim" / "runs"

Kind = Literal[
    "stage_start",     # a stage began
    "stage_done",      # a stage completed
    "observation",     # something was read (a DNS answer, an API response)
    "mutation",        # something was changed in a client's account
    "finding",         # a check failed
    "resolved",        # a finding was fixed
    "escalated",       # a human is needed; the agent has stopped
    "awaiting_confirm",# paused for approval
    "run_done",
]


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


class LaunchEvent(BaseModel):
    """One thing that happened. Rendered twice: `detail` for the operator,
    `human_text` for the business owner (D7 - the model writes the second)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    seq: int
    ts: float = Field(default_factory=time.time)
    client: str
    stage: str
    kind: Kind
    human_text: str
    detail: dict = {}

    @property
    def when(self) -> datetime:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc)


class RunLog:
    """Append-only JSONL, one file per run.

    Append-only is the point: readers tail it, and a partially written run is
    still a valid prefix rather than a corrupt document.
    """

    def __init__(self, run_id: str, runs_dir: Path | None = None) -> None:
        self.run_id = run_id
        self._dir = Path(runs_dir or RUNS_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self.path = self._dir / f"{run_id}.jsonl"
        self._seq = self._last_seq()

    def _last_seq(self) -> int:
        if not self.path.exists():
            return 0
        last = 0
        for event in self.read():
            last = max(last, event.seq)
        return last

    def append(self, *, client: str, stage: str, kind: Kind,
               human_text: str, detail: dict | None = None) -> LaunchEvent:
        self._seq += 1
        event = LaunchEvent(
            run_id=self.run_id, seq=self._seq, client=client, stage=stage,
            kind=kind, human_text=human_text, detail=detail or {},
        )
        # One line, flushed, so a tailing reader sees it immediately and never
        # sees half a record. The fsync stays: it is what makes the log the one
        # source of truth after a crash, and it is not the cost it looks like.
        # Measured 2026-09-04: 0.017 ms per append, so a fifteen-event run pays
        # 0.3 ms against 30-300 ms for a single DNS lookup.
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read(self, after_seq: int = 0) -> Iterator[LaunchEvent]:
        """Replay. `after_seq` is what makes SSE Last-Event-ID work."""
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = LaunchEvent.model_validate_json(line)
            except Exception:
                continue  # a torn final line from a killed process
            if event.seq > after_seq:
                yield event


def latest_run(runs_dir: Path | None = None) -> str | None:
    directory = Path(runs_dir or RUNS_DIR)
    runs = sorted(directory.glob("*.jsonl")) if directory.exists() else []
    return runs[-1].stem if runs else None


def all_runs(runs_dir: Path | None = None) -> list[str]:
    directory = Path(runs_dir or RUNS_DIR)
    return sorted(p.stem for p in directory.glob("*.jsonl")) if directory.exists() else []
