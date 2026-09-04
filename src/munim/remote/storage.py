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

    def __init__(self, client: str, provider: str, backend=keyring) -> None:
        self._client = client
        self._provider = provider
        self._backend = backend

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

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        # This carries the client secret for providers that require one. It goes
        # to the keychain for the same reason a provider token does, and it is
        # per client, because each client is a separate registration.
        self._write("client", info)
