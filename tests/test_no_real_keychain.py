"""The suite must not be able to reach the operator's login keychain.

There are two doors and only one was ever watched. `munim.container.keyring` is
the API-key backend; `munim.remote.storage.keyring` is the session store. More
than twenty test files patched neither, so anything calling
`connected.connections()` or constructing a `KeychainTokenStorage` read the real
thing. On macOS a read of an item owned by a different interpreter is a password
dialog, and one run of the suite asked for the login password dozens of times
before this was found.

Asserted rather than assumed, because the failure is invisible from inside a
passing test: reading a real credential succeeds, so nothing goes red. The only
symptom is a dialog on somebody's screen.
"""

import keyring

import munim.container
import munim.remote.storage


def test_the_session_store_cannot_reach_the_real_keychain():
    assert munim.remote.storage.keyring is not keyring, \
        "a test can read the operator's real sessions"


def test_the_api_key_backend_cannot_reach_the_real_keychain():
    assert munim.container.keyring is not keyring, \
        "a test can read and delete the operator's real API keys"


def test_both_doors_lead_to_the_same_sandbox():
    """One store, so a test writing through one backend can read it through the
    other, which is what `disconnect` does when it removes a key and a session
    for the same provider."""
    assert munim.container.keyring is munim.remote.storage.keyring


def test_the_sandbox_actually_stores_and_returns():
    """A stub that silently returns None would make every connectivity test
    pass by reporting nothing connected, which is the wrong kind of green."""
    munim.container.keyring.set_password("probe", "acct", "value")
    assert munim.container.keyring.get_password("probe", "acct") == "value"
    munim.container.keyring.delete_password("probe", "acct")
    assert munim.container.keyring.get_password("probe", "acct") is None
