"""Credentials in a file, at mode 0600, instead of the OS keychain.

macOS binds a keychain item's access rule to a code-signing identity. Claude Code
is signed and never re-prompts; a pip-installed Python package's "application" is
the interpreter, which munim does not control and Homebrew ships ad-hoc signed.
So the keychain's protection is fragile here in a way it is not for a signed app:
it survives until the interpreter's identity changes, and then it asks again.

This is the same choice `gh`, `aws`, `docker`, `npm` and Claude Code's own
`~/.claude/.credentials.json` make. What it costs is stated plainly rather than
buried: any process running as you can read this file without a prompt, and it
is not encrypted, so a backup or a snapshot holds it in the clear. Encrypting it
with a key stored beside it would be theatre.

Exposes the keyring-module shape, `get_password` / `set_password` /
`delete_password`, because `KeychainTokenStorage` already takes an object of
that shape and `KeychainBackend` can be pointed at one. Nothing else in the
codebase changes shape.
"""

import errno
import json
import os
import stat
import tempfile
from pathlib import Path

try:
    import fcntl
    LOCKING = True
except ImportError:                     # Windows
    LOCKING = False

HOME = Path.home() / ".munim"
VERSION = 1


class StoreUnavailable(RuntimeError):
    """The file exists and cannot be used.

    Deliberately not None. The keychain had two states, "nothing stored" and
    "nowhere to store", and both were safe to read as "nothing connected". A
    file has a third: there is somewhere, and it cannot be read. Mapping that to
    None would report every client as disconnected while their credentials sit
    on disk, which `doctor` exists to stop being possible.
    """


def path() -> Path:
    """Where credentials live. MUNIM_CREDENTIALS is exclusive, for tests.

    Read on every call rather than captured at import, so a test that sets it
    cannot be defeated by import order. Same rule as env.MUNIM_ENV and
    settings.MUNIM_SETTINGS.
    """
    named = os.environ.get("MUNIM_CREDENTIALS")
    return Path(named).expanduser() if named else HOME / "credentials.json"


def _lock_path() -> Path:
    # A separate file, because os.replace swaps the inode out from under any
    # lock held on the data file itself.
    return path().with_name(path().name + ".lock")


class _Lock:
    """An inter-process lock over the whole read-modify-write.

    The MCP server refreshes tokens while the operator runs `munim connect`, and
    both now write one file. Without this the later writer saves a copy of the
    file it read before the other one landed, and the earlier write is gone.
    Advisory, so it binds munim and nothing else, which is all it needs to.
    """

    def __init__(self) -> None:
        self._handle = None

    def __enter__(self):
        if not LOCKING:
            return self
        target = _lock_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(target, "a+")
        os.chmod(target, 0o600)
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


def _read() -> dict:
    """Every record, or {} when there is no file. Raises when there is one and
    it cannot be used."""
    target = path()
    try:
        raw = target.read_text()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise StoreUnavailable(f"{target} could not be read: {exc}") from exc

    if not target.is_file() or target.is_symlink():
        raise StoreUnavailable(f"{target} is not a regular file")

    try:
        loaded = json.loads(raw)
    except ValueError as exc:
        raise StoreUnavailable(
            f"{target} is not valid JSON ({exc}). Fix or move it; munim will "
            f"not overwrite credentials it cannot read.") from exc

    if not isinstance(loaded, dict) or loaded.get("version") != VERSION:
        raise StoreUnavailable(f"{target} is not a munim credential store")
    records = loaded.get("records")
    return records if isinstance(records, dict) else {}


def _write(records: dict) -> None:
    """Whole file, atomic, 0600 before it is ever visible under that name."""
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)

    payload = json.dumps({"version": VERSION, "records": records},
                         indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)            # before the rename, not after
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        # The rename itself has to reach disk, or a crash can restore the
        # directory to a state where the old file is back and the new one is not.
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def get_password(service: str, account: str) -> str | None:
    return _read().get(service, {}).get(account)


def set_password(service: str, account: str, secret: str) -> None:
    with _Lock():
        records = _read()
        records.setdefault(service, {})[account] = secret
        _write(records)


def delete_password(service: str, account: str) -> None:
    with _Lock():
        records = _read()
        if service in records and account in records[service]:
            del records[service][account]
            if not records[service]:
                del records[service]
            _write(records)


def accounts() -> set[str]:
    """Every account name the store holds.

    The keychain could not be enumerated, which is why the orphan sweep had to
    shell out to `security dump-keychain` and only worked on macOS. A dict can.
    """
    return {account for holders in _read().values() for account in holders}


def readable() -> tuple[bool, str]:
    """(usable, why not). For doctor, which should say so rather than crash."""
    try:
        _read()
    except StoreUnavailable as exc:
        return False, str(exc)
    return True, ""


# Everything munim ever put in the keychain, so a 0.3.0 install can be moved
# across. Deliberately does not delete: leaving a copy behind is untidy, and
# deleting something that failed to arrive is unrecoverable. The operator is
# told what remains and how to remove it.
KEYCHAIN_SERVICES = ("munim-mcp:{provider}:{kind}", "munim:{provider}")
KEYCHAIN_KINDS = ("client", "tokens", "account", "endpoint")


def adopt_keychain(clients, providers, extra_accounts=()) -> list[str]:
    """Copy credentials out of the OS keychain into this store. Idempotent.

    Returns what was moved. Nothing is deleted from the keychain: a copy left
    behind can be removed later, and a credential deleted after a write that
    silently failed cannot be recovered. The consolidation attempt earlier in
    this project deleted items it had not successfully read, which is the
    mistake this refuses to repeat.
    """
    try:
        import keyring
    except ImportError:
        return []   # no keyring installed at all, so nothing to adopt

    accounts = [*clients, *extra_accounts]
    moved: list[tuple[str, str]] = []

    with _Lock():
        records = _read()
        for account in accounts:
            for provider in providers:
                names = [f"munim:{provider}"]
                names += [f"munim-mcp:{provider}:{kind}" for kind in KEYCHAIN_KINDS]
                for service in names:
                    if records.get(service, {}).get(account) is not None:
                        continue        # already here; never overwrite
                    try:
                        found = keyring.get_password(service, account)
                    except Exception:
                        continue        # no backend, denied, anything
                    if found is None:
                        continue
                    records.setdefault(service, {})[account] = found
                    moved.append((service, account))
        if moved:
            _write(records)

    # Read back the way a real caller would, so a write that reported success
    # and produced nothing is caught here rather than by somebody later
    # discovering a client is disconnected.
    return [f"{service} for {account}" for service, account in moved
            if get_password(service, account) is not None]
