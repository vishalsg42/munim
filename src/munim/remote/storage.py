"""Where a session's tokens live: the OS keychain, keyed by client and provider.

The whole multi-account property rests on this being per client. One client id
sharing one token store is what makes a coding agent hold a single account at a
time; a registration and a token set per client is what removes it.
"""

import json
import time

from mcp.client.auth import TokenStorage

from munim import vault
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

SERVICE = "munim-mcp"

# Munim's own key inside the stored token record. Underscored like
# `_seeded` so it reads as bookkeeping rather than something a provider sent.
ISSUED_AT = "_obtained_at"


# How Munim authenticates when a provider issues it a secret. Named once and
# imported by the session, which requests it at registration, and by the store,
# which falls back to it when the registration response omits the field. Two
# copies of this string is how the fallback ends up disagreeing with the ask.
CONFIDENTIAL_AUTH_METHOD = "client_secret_post"


class KeychainTokenStorage(TokenStorage):
    """One client's session with one provider.

    Bound at construction like a Container, and for the same reason: a store
    that can be pointed at another client after the fact is a store that will
    be, and the failure is silent.
    """

    def __init__(self, client: str, provider: str, keyring=None) -> None:
        self._client = client
        self._provider = provider
        # Resolved here, not as a default argument. A default is bound when the
        # module is imported, so the store could never be substituted after
        # that: a caller passing nothing always reached the real one, including
        # from a test that had replaced it.
        # Named `keyring`, not `backend`. A CredentialBackend is a different
        # object with different methods, and calling both of them "backend" put
        # the wrong one in here twice: once in health.py and once in the MCP
        # server, where every OAuth provider raised AttributeError on
        # get_password while the identical CLI command worked.
        self._keyring = keyring if keyring is not None else vault

    @property
    def client(self) -> str:
        return self._client

    @property
    def provider(self) -> str:
        return self._provider

    def _service(self, kind: str) -> str:
        return f"{SERVICE}:{self._provider}:{kind}"

    def _read(self, kind: str) -> dict | None:
        try:
            raw = self._keyring.get_password(self._service(kind), self._client)
        except vault.StoreUnavailable:
            # Nowhere to store means nothing stored. See KeychainBackend.get.
            return None
        return json.loads(raw) if raw else None

    def _write(self, kind: str, payload, **extra) -> None:
        # Written through the dict rather than the model so Munim's own
        # bookkeeping can ride along in the same record. `get_tokens` and
        # `get_client_info` pop their key back out, so nothing the provider
        # defined is touched and no model needs an extra field.
        record = payload.model_dump(mode="json")
        record.update(extra)
        self._keyring.set_password(self._service(kind), self._client,
                                   json.dumps(record))

    async def get_tokens(self) -> OAuthToken | None:
        data = self._read("tokens")
        if not data:
            return None
        data.pop(ISSUED_AT, None)   # our bookkeeping, not the provider's
        return OAuthToken(**data)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write("tokens", tokens, **{ISSUED_AT: time.time()})

    def expires_at(self) -> float | None:
        """When the stored access token stops being accepted, or None if unknown.

        The reason this exists is a bug that made every session look like it
        expired in a day. OAuth grants `expires_in`, a duration, and the SDK
        turns it into an absolute time on the object it is holding
        (`_TokenContext.update_token_expiry`). That object dies with the
        process. Nothing wrote the absolute time down, so the next run loaded a
        token with no idea how old it was.

        `is_token_valid()` treats "no expiry known" as valid, so a fresh
        process believed a day-old token, sent it, got a 401, and the SDK went
        straight to a full browser login without ever trying the refresh token
        sitting beside it. A one-hour token therefore read as "you must sign in
        again", daily, for as long as this was unfixed.

        Recording the issue time is the whole fix. Tokens stored before this
        existed have no issue time and return None, which reproduces exactly
        the old behaviour for them rather than guessing an age.
        """
        data = self._read("tokens")
        if not data:
            return None
        issued, lasts = data.get(ISSUED_AT), data.get("expires_in")
        if issued is None or lasts is None:
            return None
        return float(issued) + float(lasts)

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
        self._keyring.set_password(self._service("client"), self._client,
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
        self._keyring.set_password(self._service("endpoint"), self._client, url)

    def endpoint(self) -> str | None:
        try:
            return self._keyring.get_password(self._service("endpoint"), self._client)
        except vault.StoreUnavailable:
            return None

    def remember_account(self, account: str) -> None:
        """Record which provider account this session turned out to be.

        Cached beside the token rather than in the registry, because it is the
        provider's answer about this session, not something the operator
        maintains. Two copies of a fact one of them can never update is how
        `ClientRecord.providers` came to be wrong about everything.
        """
        self._keyring.set_password(self._service("account"), self._client, account)

    def account(self) -> str | None:
        try:
            return self._keyring.get_password(self._service("account"), self._client)
        except vault.StoreUnavailable:
            return None

    def holds(self) -> list[str]:
        """Which kinds this session actually has stored. Read only.

        The counterpart to `forget`, iterating the same four kinds, so that a
        caller can be told what removing this session would take before it takes
        it. Asking `_read("tokens")` instead was the mistake this exists to
        prevent: Zoho stores an endpoint and no tokens at all, so a session that
        looks empty by that test is a credential nobody can rebuild from a
        browser login.
        """
        found = []
        for kind in ("client", "tokens", "account", "endpoint"):
            try:
                if self._keyring.get_password(self._service(kind), self._client):
                    found.append(kind)
            except vault.StoreUnavailable:
                return []
        return found

    def forget(self) -> list[str]:
        """Remove this client's session with this provider. Returns what went.

        Everything, not just the token: a registration left behind is a client
        the provider still knows, and a remembered account left behind would be
        compared against the next session and refuse it.
        """
        gone = []
        for kind in ("client", "tokens", "account", "endpoint"):
            if self._keyring.get_password(self._service(kind), self._client):
                try:
                    self._keyring.delete_password(self._service(kind), self._client)
                    gone.append(kind)
                except Exception:
                    pass
        return gone

    def move_to(self, client: str) -> "KeychainTokenStorage":
        """Re-file this session under another client name.

        Connecting without naming a client has to authorise first and find out
        who it authorised second, so the session begins under a provisional name
        and moves once the provider has answered. Copy then delete, because a
        delete that fails after a successful copy costs a stale entry, and one
        that fails before costs the session.
        """
        moved = KeychainTokenStorage(client, self._provider, self._keyring)
        for kind in ("client", "tokens", "account", "endpoint"):
            raw = self._keyring.get_password(self._service(kind), self._client)
            if raw is not None:
                self._keyring.set_password(moved._service(kind), client, raw)
        for kind in ("client", "tokens", "account", "endpoint"):
            try:
                self._keyring.delete_password(self._service(kind), self._client)
            except Exception:
                pass  # a leftover provisional entry is harmless
        return moved

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        # This carries the client secret for providers that require one. It goes
        # to the keychain for the same reason a provider token does, and it is
        # per client, because each client is a separate registration.
        #
        # A registration that issued a secret and named no auth method is the
        # one combination that cannot be right, and it is what Supabase returns:
        # 44 characters of client_secret and a null token_endpoint_auth_method.
        # Stored as-is, the next token exchange reads that null, decides it is a
        # public client, sends no secret, and Supabase answers
        # `Required parameter: client_secret`. The secret was never missing.
        #
        # Filled in with what was asked for at registration, not with the RFC
        # 7591 default. The spec says an omitted method means
        # client_secret_basic, and trying that against Supabase failed the same
        # way: basic auth puts the secret in an Authorization header and takes
        # it out of the body, which is precisely the parameter Supabase says is
        # required. The server accepted a registration requesting
        # client_secret_post and then declined to echo the field, so the
        # request is better evidence than the default.
        #
        # Only the absent case is filled in. A server that states a method is
        # obeyed, and a public client is left alone, because inventing a method
        # for one would break a flow that works.
        # Set on the object rather than on a copy, deliberately. The SDK hands
        # the same instance it keeps in memory and then does the token exchange
        # with that instance, not with what it just stored:
        #
        #     client_information = await handle_registration_response(...)
        #     self.context.client_info = client_information
        #     await self.context.storage.set_client_info(client_information)
        #     token_response = yield await self._perform_authorization()
        #
        # Normalising a copy fixed the keychain and left the exchange using the
        # null, so the first connect after registering always failed and only a
        # second one worked. Mutating in place fixes both, because they are one
        # object.
        if info.client_secret and not info.token_endpoint_auth_method:
            info.token_endpoint_auth_method = CONFIDENTIAL_AUTH_METHOD
        self._write("client", info)
