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

# How each provider carries its credential. Adapters never see this.
_AUTH: dict[str, tuple[str, str, str]] = {
    # provider: (base_url, header, value template)
    "cloudflare": ("https://api.cloudflare.com/client/v4", "Authorization", "Bearer {}"),
    "vercel": ("https://api.vercel.com", "Authorization", "Bearer {}"),
    "resend": ("https://api.resend.com", "Authorization", "Bearer {}"),
}


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
        return keyring.get_password(f"{self._prefix}:{provider}", client)

    def set(self, client: str, provider: str, secret: str) -> None:
        keyring.set_password(f"{self._prefix}:{provider}", client, secret)


class Container:
    """One client's world. Bound at construction; cannot widen."""

    def __init__(self, client: str, backend: CredentialBackend) -> None:
        self._client = client
        self._backend = backend

    @classmethod
    def for_client(cls, registry, client: str, backend: CredentialBackend) -> "Container":
        """Construct only for a client the registry knows.

        Fails at construction with the name in hand, rather than later at use
        with a credential lookup miss that looks like a config problem.
        """
        known = {r.name: r.name for r in registry.clients()}
        resolved = known.get(client) or known.get(client.strip().lower())
        if resolved is None:
            raise UnknownClient(f"no client registered as {client!r}")
        return cls(resolved, backend)

    @property
    def client(self) -> str:
        return self._client

    def _credential(self, provider: str) -> str:
        """Private. Adapters use .http(); nothing else should reach a secret."""
        secret = self._backend.get(self._client, provider)
        if secret is None:
            raise UnknownCredential(
                f"no {provider} credential for client {self._client!r}"
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
