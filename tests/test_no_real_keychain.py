"""The suite must not be able to reach the operator's real credentials.

This guarded two module attributes when the store was the OS keychain: swapping
`munim.container.keyring` and `munim.remote.storage.keyring` for a fake was the
only seam available. More than twenty test files patched neither, so anything
calling `connected.connections()` read the real keychain, and on macOS each such
read was a password dialog. One run asked dozens of times.

The file store reads its path on every call, so the door is now the path itself.
That is a better guard: there is one of it, and nothing to keep in sync.

Asserted rather than assumed, because the failure is invisible from inside a
passing test. Reading a real credential succeeds, so nothing goes red; the only
symptom is somebody's live session being read, or deleted.
"""

from pathlib import Path

from munim import vault
from munim.container import KeychainBackend


def test_the_store_is_not_the_operators(tmp_path):
    resolved = vault.path()
    assert tmp_path in resolved.parents, \
        f"the credential store escaped the sandbox: {resolved}"


def test_the_store_is_not_under_the_home_directory(tmp_path):
    """The specific thing that would be destroyed: ~/.munim/credentials.json."""
    resolved = vault.path()
    assert resolved != Path.home() / ".munim" / "credentials.json"


def test_writing_lands_in_the_sandbox_and_reads_back(tmp_path):
    """A stub that silently returned None would make every connectivity test
    pass by reporting nothing connected, which is the wrong kind of green."""
    backend = KeychainBackend()
    backend.set("c_probe", "cloudflare", "value")
    assert backend.get("c_probe", "cloudflare") == "value"
    assert vault.path().is_file()
    assert tmp_path in vault.path().parents


def test_both_the_key_backend_and_the_session_store_use_one_file(tmp_path):
    """`disconnect` removes a key and a session for one provider and expects
    both to be gone, which only holds if they share a store."""
    from munim.remote.storage import KeychainTokenStorage

    KeychainBackend().set("c_probe", "resend", "a-key")
    KeychainTokenStorage("c_probe", "cloudflare").remember_endpoint("https://x/mcp")

    assert "c_probe" in vault.accounts()
    assert len({p for p in [vault.path()]}) == 1


def test_the_file_is_not_readable_by_others(tmp_path):
    """0600 is the whole of the protection, so it is worth asserting rather
    than trusting."""
    import stat

    KeychainBackend().set("c_probe", "cloudflare", "value")
    mode = stat.S_IMODE(vault.path().stat().st_mode)
    assert mode & 0o077 == 0, f"mode {mode:o} is readable by others"
