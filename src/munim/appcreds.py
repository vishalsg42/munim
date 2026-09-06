"""The application credential for providers that will not issue one on demand.

Gmail and Stitch need an application registered by hand, because
`accounts.google.com` publishes no registration endpoint. The resulting client
id and secret identify Munim itself rather than any client, and one
registration serves every client connected.

Those two values were read from the environment only, which means a file, and a
file means a location. The package installs into site-packages and the operator
runs from wherever they happen to be, so "put it in .env" raises the question
"which .env", and the answer changed depending on the directory.

The keychain has no folder. It is also where Munim already puts every provider
credential, so an application credential living in a dotfile was the exception
rather than the rule.

Stored under the reserved client name `__munim__`, because these belong to the
installation rather than to any client. That name cannot collide: `new_client_id`
mints `c_<hex>`, and a label typed at the prompt is stored under an id.

The environment still wins. CI exports these, and a value already exported is a
deliberate act rather than something to be quietly overridden by a keychain
entry somebody forgot about.
"""

import os

# Not a client. These identify Munim to a provider, and the same pair serves
# every client, so filing them under a client id would be a lie about scope.
APPLICATION = "__munim__"


def default_backend():
    from munim.container import KeychainBackend
    return KeychainBackend()


def _names(provider: str) -> tuple[str, str]:
    prefix = provider.upper().replace("-", "_")
    return f"{prefix}_OAUTH_CLIENT_ID", f"{prefix}_OAUTH_CLIENT_SECRET"


def remember(provider: str, client_id: str, client_secret: str = "",
             backend=None) -> None:
    """Store an application credential where the working directory cannot
    affect whether it is found."""
    backend = backend or default_backend()
    backend.set(APPLICATION, f"{provider}:app_id", client_id)
    backend.set(APPLICATION, f"{provider}:app_secret", client_secret or "")


def resolve(provider: str, backend=None) -> tuple[str, str] | None:
    """(client id, secret), or None if this provider has no application.

    Environment first. A missing secret is an empty string rather than a
    failure: Google documents an installed-app secret as not confidential, and
    some providers issue none at all.
    """
    id_name, secret_name = _names(provider)
    from_env = os.environ.get(id_name)
    if from_env:
        return from_env, os.environ.get(secret_name, "")

    backend = backend or default_backend()
    client_id = backend.get(APPLICATION, f"{provider}:app_id")
    if not client_id:
        return None
    return client_id, backend.get(APPLICATION, f"{provider}:app_secret") or ""


def client_id_of(provider: str, backend=None) -> str | None:
    """The application's client id, and never the secret beside it.

    Separate from `resolve` on purpose. `resolve` returns both, so any value
    taken out of it carries the secret's provenance: `config list` printed the
    client id and a scanner read that as logging a credential, correctly by its
    own rules even though a client id is public by design and appears in the
    authorize URL the operator's own browser shows.

    `stored` reports what is configured and has always said it never returns the
    secret. Reading the id through here makes that structural rather than a
    promise in a docstring.
    """
    id_name, _ = _names(provider)
    from_env = os.environ.get(id_name)
    if from_env:
        return from_env
    backend = backend or default_backend()
    return backend.get(APPLICATION, f"{provider}:app_id") or None


def has_secret_for(provider: str, backend=None) -> bool:
    """Whether an application secret is stored. Never the secret."""
    _, secret_name = _names(provider)
    if os.environ.get(_names(provider)[0]):
        return bool(os.environ.get(secret_name, ""))
    backend = backend or default_backend()
    return bool(backend.get(APPLICATION, f"{provider}:app_secret"))


def stored(providers, backend=None) -> dict:
    """What is configured, for `munim config list`. Never the secret itself.

    A config command that echoes a secret puts it in the scrollback of whoever
    asked what was configured, and in whatever they paste it into.
    """
    backend = backend or default_backend()
    out = {}
    for provider in providers:
        # Two reads, not one tuple. Neither value here has ever been in the
        # same expression as the secret, so the promise above is a property of
        # the code rather than of the reader's care.
        client_id = client_id_of(provider, backend)
        out[provider] = None if client_id is None else {
            "client_id": client_id,
            "has_secret": has_secret_for(provider, backend),
            "from": "environment" if os.environ.get(_names(provider)[0])
                    else "keychain",
        }
    return out


def forget(provider: str, backend=None) -> bool:
    """Remove a stored application. True if there was one to remove.

    Only the keychain copy: an exported environment variable is the operator's,
    and a command that silently failed to remove what it said it removed would
    be worse than one that does less.
    """
    backend = backend or default_backend()
    removed = False
    for kind in ("app_id", "app_secret"):
        if backend.forget(APPLICATION, f"{provider}:{kind}"):
            removed = True
    return removed
