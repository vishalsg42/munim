"""Where a session's tokens live: the OS keychain, keyed by client and provider.

The whole multi-account property rests on this being per client. One client id
sharing one token store is what makes a coding agent hold a single account at a
time; a registration and a token set per client is what removes it.
"""

import json

import keyring
import keyring.errors
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
        try:
            raw = self._backend.get_password(self._service(kind), self._client)
        except keyring.errors.KeyringError:
            # Nowhere to store means nothing stored. See KeychainBackend.get.
            return None
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
        if not data:
            return None
        data.pop("_seeded", None)   # our bookkeeping, not the provider's
        return OAuthClientInformationFull(**data)

    def seed_client_info(self, client_id: str, client_secret: str,
                         redirect_uri: str) -> None:
        """Record an application the operator registered, so the flow uses it.

        Written straight in rather than through set_client_info, which is async
        and would drag a coroutine into building an httpx.Auth. Only ever
        overwrites what a previous seed wrote: a registration the provider
        issued is not ours to replace.
        """
        existing = self._read("client")
        if existing and not existing.get("_seeded"):
            return
        self._backend.set_password(self._service("client"), self._client,
                                   json.dumps({
                                       "client_id": client_id,
                                       "client_secret": client_secret or None,
                                       "redirect_uris": [redirect_uri],
                                       "token_endpoint_auth_method":
                                           "client_secret_post" if client_secret else "none",
                                       "grant_types": ["authorization_code",
                                                       "refresh_token"],
                                       "response_types": ["code"],
                                       "_seeded": True,
                                   }))

    def remember_endpoint(self, url: str) -> None:
        """Where this client's server lives, when the URL is the credential.

        Zoho issues a per-installation endpoint whose path carries a secret, so
        there is no token to store and no OAuth to run: the address is the
        thing to keep. It goes in the keychain beside the tokens rather than in
        servers.json, because that file is a list of servers and this is a
        credential belonging to one client.
        """
        self._backend.set_password(self._service("endpoint"), self._client, url)

    def endpoint(self) -> str | None:
        try:
            return self._backend.get_password(self._service("endpoint"), self._client)
        except keyring.errors.KeyringError:
            return None

    def remember_account(self, account: str) -> None:
        """Record which provider account this session turned out to be.

        Cached beside the token rather than in the registry, because it is the
        provider's answer about this session, not something the operator
        maintains. Two copies of a fact one of them can never update is how
        `ClientRecord.providers` came to be wrong about everything.
        """
        self._backend.set_password(self._service("account"), self._client, account)

    def account(self) -> str | None:
        try:
            return self._backend.get_password(self._service("account"), self._client)
        except keyring.errors.KeyringError:
            return None

    def move_to(self, client: str) -> "KeychainTokenStorage":
        """Re-file this session under another client name.

        Connecting without naming a client has to authorise first and find out
        who it authorised second, so the session begins under a provisional name
        and moves once the provider has answered. Copy then delete, because a
        delete that fails after a successful copy costs a stale entry, and one
        that fails before costs the session.
        """
        moved = KeychainTokenStorage(client, self._provider, self._backend)
        for kind in ("client", "tokens", "account", "endpoint"):
            raw = self._backend.get_password(self._service(kind), self._client)
            if raw is not None:
                self._backend.set_password(moved._service(kind), client, raw)
        for kind in ("client", "tokens", "account", "endpoint"):
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
