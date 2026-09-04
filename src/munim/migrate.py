"""Move credentials from being filed under a client's name to under their id.

The name used to be the identity, so everything was filed by it: pasted keys,
sessions, registrations. That made a rename a data migration, and a half-done
one left a client that looked connected and was not.

Now the id is the identity and the name is a label. Anything filed under the
old scheme has to move once, and this is that move. Idempotent: it looks for
credentials under the id first and does nothing if they are already there, so
it is safe to run on every command and safe to run twice.
"""

from munim.container import KeychainBackend
from munim.registry import Registry
from munim.remote.servers import SERVERS

KEY_PROVIDERS = ("cloudflare", "vercel", "resend", "supabase")


def migrate(registry: Registry, backend=None, keyring_module=None) -> list[str]:
    """Returns a line per credential moved, for whoever wants to say so."""
    from munim.remote.storage import KeychainTokenStorage

    backend = backend or KeychainBackend()
    moved: list[str] = []

    for record in registry.clients():
        if record.id == record.name:
            continue  # nothing to move: never had a separate name

        for provider in KEY_PROVIDERS:
            if backend.get(record.id, provider) is None:
                secret = backend.get(record.name, provider)
                if secret is not None:
                    backend.set(record.id, provider, secret)
                    moved.append(f"{record.name}: {provider} key")

        for provider in sorted(SERVERS):
            under_id = KeychainTokenStorage(record.id, provider, keyring_module)
            if under_id._read("tokens") is not None:
                continue
            under_name = KeychainTokenStorage(record.name, provider, keyring_module)
            if under_name._read("tokens") is not None:
                under_name.move_to(record.id)
                moved.append(f"{record.name}: {provider} session")

    return moved
