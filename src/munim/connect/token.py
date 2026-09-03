"""Direct credential entry, for providers that offer no OAuth flow.

Resend is the honest case: it has no authorization endpoint at all, so a key is
the only thing on offer. This exists for that, not as the default.
"""

from munim.container import KeychainBackend


class TokenConnector:
    name = "token"

    def __init__(self, backend: KeychainBackend | None = None) -> None:
        self._backend = backend or KeychainBackend()

    def connect(self, client: str, provider: str, secret: str) -> None:
        """Store a credential for one client and one provider.

        The secret is written straight to the OS keychain and never returned,
        logged, or held in the registry.
        """
        if not secret or not secret.strip():
            raise ValueError("empty credential")
        self._backend.set(client, provider, secret.strip())
