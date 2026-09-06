"""Which client already holds a given provider account.

Connecting an account that is already known under another label makes a second
client, and then a call could go to either: the split identity D5 exists to
prevent. Repairing that afterwards is what `munim merge` is for. Not creating it
is better, and it only needs one thing, which is that a session remembers which
account it turned out to be.
"""

from munim.registry import ClientRecord, Registry
from munim.remote.storage import KeychainTokenStorage


def holder_of(registry: Registry, provider: str, account: str,
              keyring=None, exclude: str | None = None) -> ClientRecord | None:
    """The client already holding this provider account, if any.

    `exclude` skips one client id, so re-connecting a client to the account it
    already has does not report itself as a clash.

    `keyring`, not `backend`: it goes straight into `KeychainTokenStorage`,
    which calls `get_password`. A caller who trusted the old name and passed a
    `CredentialBackend` would have got `AttributeError`. Same fault as the one
    that broke both agent paths; this was the fourth place it was spelled.
    """
    for record in registry.clients():
        if exclude is not None and record.id == exclude:
            continue
        if KeychainTokenStorage(record.id, provider, keyring).account() == account:
            return record
    return None
