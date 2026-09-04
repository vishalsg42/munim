"""Which clients exist, and what each one has.

The registry holds *references* - a client's name, its domain, and which
providers it has connected. It never holds a credential; those live in the
keychain, reached through a Container (docs/DECISIONS.md D14, D15).
"""

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class UnknownClient(Exception):
    """No client is registered under this name."""


class ClientRecord(BaseModel):
    """One client. Deliberately has nowhere to put a secret.

    `extra="forbid"` is load-bearing: it makes storing a token here a
    construction-time error rather than a code review question.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    domain: str | None = None


class Registry:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    # Registries written before the keychain became the single source of truth
    # carry a `providers` list. It was a second copy of a fact the keychain
    # already held, and `munim connect` never updated it, so it was wrong for
    # anyone who used the documented path. Dropped on load rather than migrated:
    # `extra="forbid"` would otherwise take every client down at once.
    _LEGACY_KEYS = ("providers",)

    def _load(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        records = json.loads(self._path.read_text())
        for record in records.values():
            for key in self._LEGACY_KEYS:
                record.pop(key, None)
        return records

    def _save(self, records: dict[str, dict]) -> None:
        """Atomic. The agent, the room and interactive tools all write here;
        an interrupted write_text leaves truncated JSON that takes every client
        down at once."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(records, indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def clients(self) -> list[ClientRecord]:
        return [ClientRecord(**r) for r in self._load().values()]

    def get(self, name: str) -> ClientRecord:
        records = self._load()
        if name not in records:
            raise UnknownClient(f"no client registered as {name!r}")
        return ClientRecord(**records[name])

    def add(self, record: ClientRecord) -> None:
        records = self._load()
        if record.name in records:
            raise ValueError(f"client {record.name!r} is already registered")
        records[record.name] = record.model_dump()
        self._save(records)

    def update(self, record: ClientRecord) -> None:
        """Replace an existing client. `add` refuses to overwrite, so
        connect_provider needs this to append to `providers`."""
        records = self._load()
        if record.name not in records:
            raise UnknownClient(f"no client registered as {record.name!r}")
        records[record.name] = record.model_dump()
        self._save(records)

    def find_by_domain(self, hostname: str) -> ClientRecord | None:
        """Resolve a hostname to its client, matching subdomains.

        Longest domain wins, so a client on `shop.example` is preferred over
        one on `example` for `checkout.shop.example`.
        """
        hostname = hostname.lower().rstrip(".")
        best: ClientRecord | None = None
        for record in self.clients():
            if not record.domain:
                continue
            domain = record.domain.lower().rstrip(".")
            if hostname == domain or hostname.endswith("." + domain):
                if best is None or len(domain) > len(best.domain or ""):
                    best = record
        return best
