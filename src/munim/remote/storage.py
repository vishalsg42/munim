"""Where a session's tokens live: the OS keychain, keyed by client and provider.

The whole multi-account property rests on this being per client. One client id
sharing one token store is what makes a coding agent hold a single account at a
time; a registration and a token set per client is what removes it.
"""

import json

import keyring
from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

SERVICE = "munim-mcp"


class KeychainTokenStorage(TokenStorage):
    """One client's session with one provider.

    Bound at construction like a Container, and for the same reason: a store
    that can be pointed at another client after the fact is a store that will
    be, and the failure is silent.
    """

    def __init__(self, client: str, provider: str, backend=None) -> None:
        self._client = client
        self._provider = provider
        # Resolved here, not as a default argument. A default is bound when the
        # module is imported, so `keyring` could never be substituted after
        # that: a caller passing nothing always reached the real OS keychain,
        # including from a test that had replaced it.
        self._backend = backend if backend is not None else keyring

    def _service(self, kind: str) -> str:
        return f"{SERVICE}:{self._provider}:{kind}"

    def _read(self, kind: str) -> dict | None:
        raw = self._backend.get_password(self._service(kind), self._client)
        return json.loads(raw) if raw else None

    def _write(self, kind: str, payload) -> None:
        self._backend.set_password(self._service(kind), self._client,
                                   payload.model_dump_json())

    async def get_tokens(self) -> OAuthToken | None:
        data = self._read("tokens")
        return OAuthToken(**data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write("tokens", tokens)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = self._read("client")
        return OAuthClientInformationFull(**data) if data else None

    def move_to(self, client: str) -> "KeychainTokenStorage":
        """Re-file this session under another client name.

        Connecting without naming a client has to authorise first and find out
        who it authorised second, so the session begins under a provisional name
        and moves once the provider has answered. Copy then delete, because a
        delete that fails after a successful copy costs a stale entry, and one
        that fails before costs the session.
        """
        moved = KeychainTokenStorage(client, self._provider, self._backend)
        for kind in ("client", "tokens"):
            raw = self._backend.get_password(self._service(kind), self._client)
            if raw is not None:
                self._backend.set_password(moved._service(kind), client, raw)
        for kind in ("client", "tokens"):
            try:
                self._backend.delete_password(self._service(kind), self._client)
            except Exception:
                pass  # a leftover provisional entry is harmless
        return moved

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        # This carries the client secret for providers that require one. It goes
        # to the keychain for the same reason a provider token does, and it is
        # per client, because each client is a separate registration.
        self._write("client", info)
