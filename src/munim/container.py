"""Per-client credential isolation.

A Container is bound to exactly one client at construction and can never widen.
Backends are swappable: KeychainBackend now, AgentCore Identity when hosted (D14).

Two properties this module exists to hold:

  - The raw secret never becomes a value in adapter code. Adapters ask for an
    authenticated client, not a token, so no `logger.debug(token)` and no httpx
    traceback carrying `request.headers` can falsify D6 in a public repo.
  - A container cannot be constructed for a client that is not registered.
    "acme" vs "acme-uk" would otherwise be a *successful* mutation on the wrong
    account, which is the failure mode D5 exists to prevent.
"""

from typing import Protocol

import httpx
import keyring
import keyring.errors

# How each provider carries its credential. Adapters never see this.
_AUTH: dict[str, tuple[str, str, str]] = {
    # provider: (base_url, header, value template)
    "cloudflare": ("https://api.cloudflare.com/client/v4", "Authorization", "Bearer {}"),
    "vercel": ("https://api.vercel.com", "Authorization", "Bearer {}"),
    "resend": ("https://api.resend.com", "Authorization", "Bearer {}"),
}


# Providers this codebase can call with a pasted key. Derived from the auth
# table rather than written out again, because the two lists drifted: supabase
# was offered by `connect` and warned about by `doctor` while having no entry
# here, so a key stored for it could not be used by anything.
KEY_PROVIDERS = tuple(sorted(_AUTH))


class UnknownCredential(Exception):
    """No credential is stored for this client and provider."""


class UnknownClient(Exception):
    """No client is registered under this name."""


class UnsupportedProvider(Exception):
    """This provider has no authentication profile. An unimplemented provider
    is absent, not faked (D11)."""


class CredentialBackend(Protocol):
    def get(self, client: str, provider: str) -> str | None: ...


class KeychainBackend:
    """OS keychain. Credentials never leave the machine (D14)."""

    def __init__(self, service_prefix: str = "munim") -> None:
        self._prefix = service_prefix

    def get(self, client: str, provider: str) -> str | None:
        """None when nothing is stored, and also when there is nowhere to store.

        A machine with no keychain backend, which is most Linux servers and
        every CI runner, used to raise out of here and take `doctor` down with
        it. Reads degrade to "nothing connected"; `doctor` says why, once,
        rather than every caller discovering it as a stack trace.
        """
        try:
            return keyring.get_password(f"{self._prefix}:{provider}", client)
        except keyring.errors.KeyringError:
            return None

    def forget(self, client: str, provider: str) -> bool:
        """Remove a stored key. True if there was one."""
        try:
            if keyring.get_password(f"{self._prefix}:{provider}", client) is None:
                return False
            keyring.delete_password(f"{self._prefix}:{provider}", client)
            return True
        except keyring.errors.KeyringError:
            return False

    def set(self, client: str, provider: str, secret: str) -> None:
        """Writes still raise. Silently not storing a credential the operator
        just pasted would be worse than failing in front of them."""
        keyring.set_password(f"{self._prefix}:{provider}", client, secret)


class Container:
    """One client's world. Bound at construction; cannot widen."""

    def __init__(self, client: str, backend: CredentialBackend) -> None:
        self._client = client
        self._backend = backend

    @classmethod
    def for_client(cls, registry, client: str, backend: CredentialBackend) -> "Container":
        """Construct only for a client the registry knows, and bind to their id.

        Callers pass whatever they were given, usually a name. What gets bound
        is the id, because credentials are filed by identity and a name is a
        label: binding to the label meant renaming a client orphaned their
        credentials, and two labels for one account made two containers.

        Fails at construction with the name in hand, rather than later at use
        with a credential lookup miss that looks like a config problem.
        """
        wanted = client.strip()
        for record in registry.clients():
            if wanted in (record.id, record.name) or wanted.lower() == record.name.lower():
                box = cls(record.id, backend)
                box._label = record.name
                return box
        raise UnknownClient(f"no client registered as {client!r}")

    @property
    def client(self) -> str:
        """The identity. Use `label` for anything a person reads."""
        return self._client

    @property
    def label(self) -> str:
        """What this client is called, falling back to the id when unknown."""
        return getattr(self, "_label", None) or self._client

    def _credential(self, provider: str) -> str:
        """Private. Adapters use .http(); nothing else should reach a secret."""
        secret = self._backend.get(self._client, provider)
        if secret is None:
            # The label, not the id. The id is the right identity and the wrong
            # word for it: `no resend credential for client 'c_2db35f36a043bf0c'`
            # makes the operator map an opaque key back to a client before the
            # message helps at all. Falls back to the id when there is no label,
            # which is a container built without going through the registry.
            raise UnknownCredential(
                f"no {provider} credential for client {self.label!r}"
            )
        return secret

    def has(self, provider: str) -> bool:
        """Whether a credential exists, without revealing it."""
        return self._backend.get(self._client, provider) is not None

    def http(self, provider: str) -> httpx.AsyncClient:
        """An authenticated client for one provider, scoped to this container.

        The token is injected into the header here and never returned, so it
        never exists as a value anywhere an adapter could log it.
        """
        if provider not in _AUTH:
            raise UnsupportedProvider(f"no auth profile for provider {provider!r}")
        base_url, header, template = _AUTH[provider]
        return httpx.AsyncClient(
            base_url=base_url,
            headers={header: template.format(self._credential(provider))},
            timeout=httpx.Timeout(30.0),
        )

    def __repr__(self) -> str:
        # Never render a secret, and never render another client's name.
        return f"<Container client={self._client!r}>"
