"""One person's answer to one question about one plan.

The agent stops before replacing a record somebody already published, and this
is the channel the answer comes back through. Two things write to it: the
control room's button, and `apply_mail_setup(..., approved=true)` from the
coding agent. Nothing a model can reach writes to it at all, which is the whole
point: the approval is not a value the agent can produce.

**Why a file rather than something in memory.** The control room is a separate
process on purpose, because the MCP server is a stdio subprocess the coding
agent kills on every reconnect (see `room/server.py`). The two already share
`~/.munim/runs` and `~/.munim/plans`, and a file is the only channel that
survives one of them dying mid-question. If the server is killed while waiting,
the person's click still lands, and the next `apply_mail_setup` reads it.

**Why there is no lock.** `record` writes a temporary file and renames it, and
`os.replace` is atomic on POSIX, so a reader sees either no file or the whole
file and never half of one. The alternative was a lock, and reaching for a
locking primitive is exactly what cost this project 8.07 seconds of dead server
once already (see `vault._Lock`). The absence of a lock here is the fix, not an
oversight.
"""

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

HOME = Path.home() / ".munim"

# How long an answer stays good for. An approval is a statement about a moment:
# somebody looked at two records and said yes to those. Half an hour later the
# zone may not be what they looked at, and their answer should not still count.
GOOD_FOR = 15 * 60.0

# How long to wait for a person before giving up and saying so. Never approval:
# see `wait_for`.
WAIT = 300.0

POLL = 0.4


def directory() -> Path:
    """Where decisions live. MUNIM_DECISIONS is exclusive, for tests.

    Read on every call rather than captured at import, so a test that sets it
    cannot be defeated by import order. Same rule as `vault.path`,
    `env.MUNIM_ENV` and `settings.MUNIM_SETTINGS`. A decision file left behind
    in a real home by a test run would be a standing approval on a real plan,
    which is the worst artefact a suite could leave.
    """
    named = os.environ.get("MUNIM_DECISIONS")
    return Path(named).expanduser() if named else HOME / "decisions"


@dataclass
class Decision:
    run_id: str
    plan_id: str
    approved: bool
    by: str        # "room" | "cli" | "mcp"
    at: float

    @property
    def stale(self) -> bool:
        return time.time() - self.at > GOOD_FOR


def key(run_id: str, plan_id: str) -> str:
    """Both ids, because either alone would be wrong.

    Plan id alone would let an answer given in one run be reused by a later one
    against the same plan file. Run id alone would let one approval cover a
    second, different plan made later in the same run.
    """
    return f"{_safe(run_id)}.{_safe(plan_id)}"


def _safe(part: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in part)


def _folder() -> Path:
    out = directory()
    out.mkdir(parents=True, exist_ok=True)
    # Set every time rather than only on creation. `~/.munim/plans` is
    # world-readable today because `mailplan._save` only ever calls mkdir, and
    # it is safe purely because `~/.munim` happens to be 0700. Do not inherit
    # that luck.
    os.chmod(out, 0o700)
    return out


def _write(path: Path, payload: dict) -> None:
    """Atomically, and without a lock. See the module docstring."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def ask(run_id: str, plan_id: str, *, client: str, domain: str,
        changes: list[dict]) -> Path:
    """Post the question. The room reads this to render what would change.

    `changes` carries each record's current value beside its proposed one, so a
    person is deciding about a diff rather than about a sentence. These are DNS
    records, published to the world by construction, so there is no secret here
    to withhold. That is a different case from the Vercel environment values the
    adapter deliberately drops under D6, and the difference is worth stating
    because "the room now shows record contents" is a sentence a reviewer stops
    on.
    """
    target = _folder() / f"{key(run_id, plan_id)}.ask.json"
    _write(target, {"run_id": run_id, "plan_id": plan_id, "client": client,
                    "domain": domain, "changes": changes, "at": time.time()})
    return target


def question(run_id: str, plan_id: str) -> dict | None:
    """The pending question, for the CLI to print and the room to render."""
    target = _folder() / f"{key(run_id, plan_id)}.ask.json"
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read(run_id: str, plan_id: str) -> Decision | None:
    """The answer, or None if nobody has answered or the answer went stale."""
    target = _folder() / f"{key(run_id, plan_id)}.json"
    try:
        made = Decision(**json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None
    return None if made.stale else made


def record(run_id: str, plan_id: str, *, approved: bool, by: str) -> Decision:
    """Write one answer. Never called from anywhere a model can reach.

    Idempotent on purpose: an answer already given is returned unchanged rather
    than overwritten. Two clicks on the button, or a click racing the CLI, must
    not be able to turn a refusal into an approval.
    """
    standing = read(run_id, plan_id)
    if standing is not None:
        return standing
    made = Decision(run_id=run_id, plan_id=plan_id, approved=approved, by=by,
                    at=time.time())
    _write(_folder() / f"{key(run_id, plan_id)}.json", asdict(made))
    return made


async def wait_for(run_id: str, plan_id: str, *,
                   timeout: float = WAIT) -> Decision | None:
    """Wait for a person, without stalling the loop everything else runs on.

    Polling rather than watching the filesystem, because a poll is a `stat` and
    a watcher is a platform matrix. `await asyncio.sleep` between looks, so the
    server keeps answering while somebody reads a diff.

    **Running out of time is not approval.** Returning None means nobody said
    yes, and the caller has to treat that as a refusal that can be retried, not
    as consent that arrived quietly.
    """
    deadline = time.monotonic() + timeout
    while True:
        made = read(run_id, plan_id)
        if made is not None:
            return made
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(POLL)


def pending(run_id: str) -> list[dict]:
    """Questions asked during this run that nobody has answered yet.

    An operator has a run id, because that is what every tool result and every
    line of the run log carries. They do not have a plan id, and asking them to
    go and find one before they can say yes is the kind of step that makes a
    person reach for the dashboard instead.
    """
    folder = _folder()
    out = []
    for path in sorted(folder.glob(f"{_safe(run_id)}.*.ask.json")):
        try:
            asked = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if read(asked.get("run_id", ""), asked.get("plan_id", "")) is None:
            out.append(asked)
    return out


def forget(run_id: str, plan_id: str) -> None:
    """Drop both files. For tests, and for a run that ended another way."""
    folder = _folder()
    for suffix in (".json", ".ask.json"):
        try:
            (folder / f"{key(run_id, plan_id)}{suffix}").unlink()
        except OSError:
            pass
