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
from munim import vault

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
    """Credentials on this machine, in ~/.munim/credentials.json at mode 0600.

    Named for the keychain it used to wrap, and kept that way because the name
    appears in sixteen call sites and two published documents; what it means now
    is "the credential store". See munim/vault.py for why the keychain was left
    behind and what that costs.

    A missing file means nothing is stored, which is the ordinary state of a
    fresh install. A file that exists and cannot be read is not that, and raises
    rather than reporting every client as disconnected while their credentials
    sit on disk.
    """

    def __init__(self, service_prefix: str = "munim") -> None:
        self._prefix = service_prefix

    def get(self, client: str, provider: str) -> str | None:
        return vault.get_password(f"{self._prefix}:{provider}", client)

    def forget(self, client: str, provider: str) -> bool:
        """Remove a stored key. True if there was one."""
        if vault.get_password(f"{self._prefix}:{provider}", client) is None:
            return False
        vault.delete_password(f"{self._prefix}:{provider}", client)
        return True

    def set(self, client: str, provider: str, secret: str) -> None:
        vault.set_password(f"{self._prefix}:{provider}", client, secret)


class Container:
    """One client's world. Bound at construction; cannot widen."""

    def __init__(self, client: str, backend: CredentialBackend,
                 keyring=None) -> None:
        self._client = client
        self._backend = backend
        # The session store, and a seam so a test can watch it. `backend` holds
        # pasted API keys; `keyring` is where OAuth sessions live. Nothing here
        # reads a session's token, only whether one exists, and only to explain
        # a refusal. Without the seam that read would reach the module default
        # and `test_isolation` would keep asserting that every *backend* call
        # names one client while a second store went unwatched, which is worse
        # than a failing test.
        self._keyring = keyring

    @classmethod
    def for_client(cls, registry, client: str, backend: CredentialBackend,
                   keyring=None) -> "Container":
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
                box = cls(record.id, backend, keyring=keyring)
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

    def _has_session(self, provider: str) -> bool:
        """Whether an MCP session exists for this client and provider.

        Presence only: never the token. Deliberately the narrow
        `KeychainTokenStorage.holds()` rather than `connections()`, which walks
        every provider and re-parses the whole store for each, 14 to 25 file
        reads to answer a question about one. `connected.py:50` already records
        that going wider there took the suite from 47 seconds to 177.
        """
        from munim.remote.storage import KeychainTokenStorage

        try:
            return bool(KeychainTokenStorage(
                self._client, provider, self._keyring).holds())
        except Exception:
            # A store that cannot be read is not a session, and this is only
            # ever called to make a refusal more useful.
            return False

    def _session_token(self, provider: str) -> str | None:
        """The MCP session's access token, where that provider's REST API takes
        it. None everywhere else, which is the default.

        Whoever calls this is responsible for the token being fresh: nothing
        synchronous can refresh one. `remote/session.freshen` is the async step
        that does, and the tools that reach a REST path call it first.
        """
        from munim.remote.servers import server_for
        from munim.remote.storage import KeychainTokenStorage

        server = server_for(provider)
        if server is None or not getattr(server, "rest_takes_session", False):
            return None
        try:
            held = KeychainTokenStorage(
                self._client, provider, self._keyring)._read("tokens") or {}
        except Exception:
            return None
        token = held.get("access_token")
        return token if token else None

    def _credential(self, provider: str) -> str:
        """Private. Adapters use .http(); nothing else should reach a secret."""
        secret = self._backend.get(self._client, provider)
        if secret is None:
            # The label, not the id. The id is the right identity and the wrong
            # word for it: `no resend credential for client 'c_2db35f36a043bf0c'`
            # makes the operator map an opaque key back to a client before the
            # message helps at all. Falls back to the id when there is no label,
            # which is a container built without going through the registry.
            # Two stores, and saying only "no credential" while the other one
            # holds a live session is how an operator was told a client was
            # connected by `client_status` and not connected by
            # `plan_mail_setup`, in the same minute, both truthfully. The
            # difference is what this needs to say.
            # Where the provider's own REST API accepts the token its MCP
            # server issued, the session *is* the credential and asking for a
            # second one would be bureaucracy. Measured per provider, defaulting
            # to no, because it is false for two of the three: see
            # `RemoteServer.rest_takes_session`.
            borrowed = self._session_token(provider)
            if borrowed is not None:
                return borrowed
            if self._has_session(provider):
                raise UnknownCredential(
                    f"{provider} is connected for {self.label!r} as an MCP "
                    f"session, and this path uses {provider}'s REST API, which "
                    f"needs its own API key. The two are different credentials "
                    f"and one does not stand in for the other. Run: "
                    f'munim connect "{self.label}" {provider} --token'
                )
            raise UnknownCredential(
                f"no {provider} credential for client {self.label!r}"
            )
        return secret

    def has(self, provider: str) -> bool:
        """Whether a pasted key exists, without revealing it."""
        return self._backend.get(self._client, provider) is not None

    def can_reach(self, provider: str) -> bool:
        """Whether `http()` would produce a client that can actually call out.

        Three ways that is true and `has()` only knows about one: a pasted key,
        a session whose token the provider's own REST API accepts, and a
        session whose MCP server can carry the request. Anything asking "could
        a repair run for this client" wants this rather than `has`, which
        answered no for a client connected by OAuth to both providers, on a
        path that now works.
        """
        if provider not in _AUTH:
            return False
        if self.has(provider) or self._session_token(provider) is not None:
            return True
        if not self._has_session(provider):
            return False
        from munim.remote.rest import transport_for

        return transport_for(provider, self._client, keyring=self._keyring) is not None

    def http(self, provider: str) -> httpx.AsyncClient:
        """An authenticated client for one provider, scoped to this container.

        The token is injected into the header here and never returned, so it
        never exists as a value anywhere an adapter could log it.

        Where there is no pasted key and there is an MCP session, the requests
        go out as that provider's own MCP tool calls instead, over the session
        the operator already has. The adapter above is unchanged and cannot
        tell, which is the point: one connection per client was the claim, and
        "log in, then also paste an API key" was not that. See
        `remote/rest.py`.
        """
        if provider not in _AUTH:
            raise UnsupportedProvider(f"no auth profile for provider {provider!r}")
        base_url, header, template = _AUTH[provider]

        if self._backend.get(self._client, provider) is None \
                and self._session_token(provider) is None \
                and self._has_session(provider):
            from munim.remote.rest import transport_for

            through = transport_for(provider, self._client, keyring=self._keyring)
            if through is not None:
                # No Authorization header: there is no key to put in one, and
                # the session never becomes a value on this side.
                return httpx.AsyncClient(base_url=base_url, transport=through,
                                         timeout=httpx.Timeout(60.0))

        return httpx.AsyncClient(
            base_url=base_url,
            headers={header: template.format(self._credential(provider))},
            timeout=httpx.Timeout(30.0),
        )

    def __repr__(self) -> str:
        # Never render a secret, and never render another client's name.
        return f"<Container client={self._client!r}>"
