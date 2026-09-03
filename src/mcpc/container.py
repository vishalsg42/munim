"""Per-client credential isolation.

A Container is bound to exactly one client at construction and can never widen.
Backends are swappable: KeychainBackend now, an AgentCore Identity backend when
hosted (see docs/DECISIONS.md D14).
"""

from typing import Protocol

import keyring


class UnknownCredential(Exception):
    """No credential is stored for this client and provider."""


class CredentialBackend(Protocol):
    def get(self, client: str, provider: str) -> str | None: ...


class KeychainBackend:
    """OS keychain. Credentials never leave the machine (D14)."""

    def __init__(self, service_prefix: str = "mcpc") -> None:
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

    @property
    def client(self) -> str:
        return self._client

    def credential(self, provider: str) -> str:
        secret = self._backend.get(self._client, provider)
        if secret is None:
            raise UnknownCredential(
                f"no {provider} credential for client {self._client!r}"
            )
        return secret

    def __repr__(self) -> str:
        # Never render a secret, and never render another client's name.
        return f"<Container client={self._client!r}>"
