"""Credentials in a file, and the properties that make that defensible.

macOS binds a keychain item's access rule to a code-signing identity. A signed
application keeps that identity across updates; a pip-installed Python package
cannot have one, because the application macOS sees is the interpreter. The
protection was real and fragile in a way it is not for a signed app, and this
project broke it three times in a day: two installs, an interpreter upgrade, and
scripts run under the wrong Python.

What the file costs is not hidden: anything running as the operator can read it.
What it must not do is lose credentials, expose them wider than the operator, or
report a client as disconnected when it simply could not read the store.
"""

import json
import os
import stat

import pytest

import time

from munim import vault


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MUNIM_CREDENTIALS", str(tmp_path / "credentials.json"))
    return tmp_path / "credentials.json"


# ---- the basics -----------------------------------------------------------

def test_a_credential_survives_a_round_trip(store):
    vault.set_password("munim-mcp:cloudflare", "c_1", "tok")
    assert vault.get_password("munim-mcp:cloudflare", "c_1") == "tok"


def test_nothing_stored_is_not_an_error(store):
    """A fresh install has no file, which is the ordinary state."""
    assert vault.get_password("munim-mcp:cloudflare", "c_1") is None
    assert not store.exists()


def test_deleting_removes_only_that_one(store):
    vault.set_password("munim:resend", "c_1", "a")
    vault.set_password("munim:resend", "c_2", "b")
    vault.delete_password("munim:resend", "c_1")

    assert vault.get_password("munim:resend", "c_1") is None
    assert vault.get_password("munim:resend", "c_2") == "b"


def test_two_clients_never_share_a_record(store):
    """Per client is the whole product. Nesting by service then account is what
    makes that true by construction rather than by string formatting."""
    vault.set_password("munim-mcp:cloudflare", "c_1", "one")
    vault.set_password("munim-mcp:cloudflare", "c_2", "two")

    assert vault.get_password("munim-mcp:cloudflare", "c_1") == "one"
    assert vault.get_password("munim-mcp:cloudflare", "c_2") == "two"


def test_a_client_name_with_spaces_is_not_ambiguous(store):
    """Accounts are not always `c_` hex: sessions are filed under the operator's
    own label during a rename, and the provisional key is "…connecting"."""
    vault.set_password("munim-mcp:vercel", "Acme Ltd", "a")
    vault.set_password("munim-mcp:vercel", "…connecting", "b")

    assert vault.get_password("munim-mcp:vercel", "Acme Ltd") == "a"
    assert vault.get_password("munim-mcp:vercel", "…connecting") == "b"


# ---- permissions ----------------------------------------------------------

def test_the_file_is_readable_only_by_its_owner(store):
    """0600 is the entire protection, so it is asserted rather than trusted."""
    vault.set_password("munim:resend", "c_1", "secret")
    assert stat.S_IMODE(store.stat().st_mode) & 0o077 == 0


def test_the_directory_is_not_world_readable(store):
    vault.set_password("munim:resend", "c_1", "secret")
    assert stat.S_IMODE(store.parent.stat().st_mode) & 0o077 == 0


def test_no_world_readable_window_before_the_rename(store, monkeypatch):
    """The mode is set on the temporary file, not after the rename. Setting it
    afterwards leaves an instant where the credentials exist under the final
    name with whatever the umask allowed."""
    seen = []
    real = os.replace

    def watch(src, dst):
        seen.append(stat.S_IMODE(os.stat(src).st_mode))
        return real(src, dst)

    monkeypatch.setattr(vault.os, "replace", watch)
    vault.set_password("munim:resend", "c_1", "secret")

    assert seen and all(mode & 0o077 == 0 for mode in seen), \
        f"the temporary file was readable by others: {[oct(m) for m in seen]}"


# ---- durability -----------------------------------------------------------

def test_a_failed_write_leaves_the_previous_contents(store, monkeypatch):
    vault.set_password("munim:resend", "c_1", "first")
    before = store.read_text()

    def explode(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(vault.os, "replace", explode)
    with pytest.raises(OSError):
        vault.set_password("munim:resend", "c_2", "second")

    assert store.read_text() == before
    assert vault.get_password("munim:resend", "c_1") == "first"


def test_a_failed_write_leaves_no_temporary_file(store, monkeypatch):
    vault.set_password("munim:resend", "c_1", "first")

    monkeypatch.setattr(vault.os, "replace",
                        lambda s, d: (_ for _ in ()).throw(OSError("nope")))
    with pytest.raises(OSError):
        vault.set_password("munim:resend", "c_2", "second")

    # The lock file is expected and lives beside the store on purpose: locking
    # the data file is wrong, because os.replace swaps its inode out.
    strays = [p.name for p in store.parent.iterdir()
              if p.name != store.name and not p.name.endswith(".lock")]
    assert strays == [], f"left behind: {strays}"


def test_the_bytes_and_the_rename_both_reach_disk(store, monkeypatch):
    """`os.replace` being durable is not the same as what it points at being
    durable, and the directory entry is a third thing again."""
    synced = []
    monkeypatch.setattr(vault.os, "fsync", lambda fd: synced.append(fd))
    vault.set_password("munim:resend", "c_1", "secret")
    assert len(synced) >= 2, "the file and its directory should both be synced"


# ---- an unusable store ----------------------------------------------------

def test_an_unreadable_store_raises_rather_than_reading_as_empty(store):
    """The keychain had two states, "nothing stored" and "nowhere to store", and
    both were safe to read as "nothing connected". A file has a third: there is
    somewhere and it cannot be read. Reporting that as empty would show every
    client as disconnected while their credentials sit on disk."""
    store.write_text("{not json")
    with pytest.raises(vault.StoreUnavailable):
        vault.get_password("munim:resend", "c_1")


def test_an_unreadable_store_is_never_overwritten(store):
    """Starting fresh would destroy every credential in it."""
    broken = '{"version": 1, "records": {"munim:resend"'
    store.write_text(broken)

    with pytest.raises(vault.StoreUnavailable):
        vault.set_password("munim:resend", "c_1", "secret")
    assert store.read_text() == broken


def test_a_store_from_a_future_version_is_refused(store):
    store.write_text(json.dumps({"version": 99, "records": {}}))
    with pytest.raises(vault.StoreUnavailable):
        vault.get_password("munim:resend", "c_1")


def test_readable_reports_rather_than_raising(store):
    """`doctor` needs to say what is wrong, not inherit the exception."""
    assert vault.readable() == (True, "")
    store.write_text("{not json")
    usable, why = vault.readable()
    assert usable is False and str(store) in why


# ---- enumeration, which the keychain could not do -------------------------

def test_every_account_can_be_listed(store):
    """The orphan sweep used to shell out to `security dump-keychain` and only
    work on macOS, because `keyring` cannot list what it holds."""
    vault.set_password("munim-mcp:cloudflare", "c_1", "a")
    vault.set_password("munim:resend", "c_2", "b")
    assert vault.accounts() == {"c_1", "c_2"}


# ---- adoption from the keychain -------------------------------------------

def test_adoption_copies_and_never_deletes(store, monkeypatch):
    """A copy left behind is untidy. A credential deleted after a write that
    silently failed is not recoverable, and the consolidation attempt earlier in
    this project deleted items it had not successfully read."""
    held = {("munim-mcp:cloudflare:tokens", "c_1"): '{"access_token": "t"}'}
    deleted = []

    class FakeKeyring:
        errors = type("errors", (), {"KeyringError": Exception})

        @staticmethod
        def get_password(service, account):
            return held.get((service, account))

        @staticmethod
        def delete_password(service, account):
            deleted.append((service, account))

    monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
    moved = vault.adopt_keychain(["c_1"], ["cloudflare"])

    assert moved, "nothing was adopted"
    assert vault.get_password("munim-mcp:cloudflare:tokens", "c_1")
    assert deleted == [], "adoption deleted from the keychain"


def test_adoption_never_overwrites_what_is_already_here(store, monkeypatch):
    vault.set_password("munim-mcp:cloudflare:tokens", "c_1", "mine")

    class FakeKeyring:
        errors = type("errors", (), {"KeyringError": Exception})
        get_password = staticmethod(lambda s, a: "theirs")

    monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
    vault.adopt_keychain(["c_1"], ["cloudflare"])

    assert vault.get_password("munim-mcp:cloudflare:tokens", "c_1") == "mine"


# ---- a write waits for another process, but not forever -----------------


def test_a_held_store_gives_up_with_a_sentence_rather_than_stalling(
        tmp_path, monkeypatch):
    """Reproduced against a live MCP server: another process holding the store
    stalled the server's event loop for exactly as long as it held it, 8.07s
    for 8s of contention, and the client saw a server that had stopped
    answering. `flock(LOCK_EX)` with no timeout waits forever, and every store
    write takes it, including the ones the server makes when a probe refreshes
    a token."""
    import fcntl

    monkeypatch.setenv("MUNIM_CREDENTIALS", str(tmp_path / "credentials.json"))
    monkeypatch.setattr(vault, "WAIT_FOR_STORE", 0.3)

    held = open(vault._lock_path(), "a+")
    fcntl.flock(held.fileno(), fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        with pytest.raises(vault.StoreUnavailable, match="held the credential"):
            with vault._Lock():
                pass
        waited = time.monotonic() - started
    finally:
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        held.close()

    assert waited < 3, f"it waited {waited:.1f}s past its own bound"


def test_an_uncontended_write_is_not_slowed_by_the_bound(tmp_path, monkeypatch):
    """The bound is a ceiling, not a delay. Polling must not cost anything in
    the ordinary case, which is every write that is not contended."""
    monkeypatch.setenv("MUNIM_CREDENTIALS", str(tmp_path / "credentials.json"))

    started = time.monotonic()
    for _ in range(20):
        vault.set_password("munim:test", "c_1", "secret")
    took = time.monotonic() - started

    assert vault.get_password("munim:test", "c_1") == "secret"
    assert took < 2, f"twenty uncontended writes took {took:.1f}s"


def test_the_lock_is_released_when_the_wait_gives_up(tmp_path, monkeypatch):
    """A failed acquire must not leave a file handle holding anything, or the
    next write in the same process inherits the problem."""
    import fcntl

    monkeypatch.setenv("MUNIM_CREDENTIALS", str(tmp_path / "credentials.json"))
    monkeypatch.setattr(vault, "WAIT_FOR_STORE", 0.2)

    held = open(vault._lock_path(), "a+")
    fcntl.flock(held.fileno(), fcntl.LOCK_EX)
    try:
        with pytest.raises(vault.StoreUnavailable):
            with vault._Lock():
                pass
    finally:
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        held.close()

    # And once the other process lets go, the next write succeeds.
    vault.set_password("munim:test", "c_1", "after")
    assert vault.get_password("munim:test", "c_1") == "after"
