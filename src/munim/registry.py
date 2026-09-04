"""Which clients exist, and what each one has.

The registry holds *references* - a client's name, its domain, and which
providers it has connected. It never holds a credential; those live in the
keychain, reached through a Container (docs/DECISIONS.md D14, D15).
"""

import json
import secrets
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class UnknownClient(Exception):
    """No client is registered under this name."""


def new_client_id() -> str:
    """A stable handle for a client, unrelated to what they are called."""
    return "c_" + secrets.token_hex(8)


class ClientRecord(BaseModel):
    """One client. Deliberately has nowhere to put a secret.

    `id` is the identity; `name` is a label.

    They used to be the same thing, and everything keyed on the label:
    credentials in the keychain, sessions, registry rows. Two consequences,
    both bad. Renaming a client had to physically move their credentials, and
    a half-done rename left a client that looked connected and was not.
    Connecting one real account under two labels made two clients, so a call
    could go to either, which is the split identity D5 exists to prevent.

    `extra="forbid"` is load-bearing: it makes storing a token here a
    construction-time error rather than a code review question.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_client_id)
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
        migrated: dict[str, dict] = {}
        changed = False
        for key, record in records.items():
            for legacy in self._LEGACY_KEYS:
                if record.pop(legacy, None) is not None:
                    changed = True
            # Registries written while the name was the identity are keyed by
            # it and carry no id. Give them one, keeping the name as the label
            # it should always have been.
            record.setdefault("name", key)
            if "id" not in record:
                record["id"] = new_client_id()
                changed = True
            migrated[record["id"]] = record

        if changed:
            # Written back immediately, and this is the whole point. An id
            # minted on every read is not an identity: nothing filed under one
            # can ever be found again, and every client reads as disconnected
            # while its credentials sit there untouched.
            self._save(migrated)
        return migrated

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

    def get(self, key: str) -> ClientRecord:
        """By id or by name. Callers hold whichever they were given, and the
        distinction matters to storage, not to whoever is asking."""
        records = self._load()
        if key in records:
            return ClientRecord(**records[key])
        for record in records.values():
            if record.get("name") == key:
                return ClientRecord(**record)
        raise UnknownClient(f"no client registered as {key!r}")

    def add(self, record: ClientRecord) -> None:
        records = self._load()
        if any(r.get("name") == record.name for r in records.values()):
            raise ValueError(f"client {record.name!r} is already registered")
        records[record.id] = record.model_dump()
        self._save(records)

    def update(self, record: ClientRecord) -> None:
        """Replace an existing client, matched by id.

        By id, so this is also how a client is renamed: the label changes and
        the identity does not, which is the whole point of having both.
        """
        records = self._load()
        if record.id not in records:
            raise UnknownClient(f"no client with id {record.id!r}")
        records[record.id] = record.model_dump()
        self._save(records)

    def rename(self, key: str, new_name: str) -> ClientRecord:
        """Change what a client is called. Nothing else moves.

        This used to relocate the registry row and every credential filed under
        the old name, and a failure part-way left a client that looked
        connected and was not. Now the identity never changes, so a rename is
        one field.
        """
        record = self.get(key)
        if any(r.name == new_name and r.id != record.id for r in self.clients()):
            raise ValueError(f"{new_name!r} is already registered; pick another name")
        record.name = new_name
        self.update(record)
        return record

    def remove(self, key: str) -> ClientRecord:
        """Forget a client. Credentials are not this file's to delete, so the
        caller deals with those first: removing the row while a token remains
        leaves a credential nothing can reach and nothing can name."""
        record = self.get(key)
        records = self._load()
        records.pop(record.id, None)
        self._save(records)
        return record

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
