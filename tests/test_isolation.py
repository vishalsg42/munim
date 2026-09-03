"""The security claim of the project, tested on day one rather than day eight.

These assert the two properties D5 and D6 actually promise:
  - a container cannot reach another client's credentials, and cannot be
    constructed for a client that is not registered;
  - the raw secret never becomes a value adapter code can touch or log.
"""

import pytest

from munim.container import (
    Container,
    UnknownClient,
    UnknownCredential,
    UnsupportedProvider,
)
from munim.registry import ClientRecord, Registry


class FakeBackend:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def get(self, client: str, provider: str):
        self.calls.append((client, provider))
        return self.store.get((client, provider))


def _two_clients():
    return FakeBackend(
        {
            ("acme", "cloudflare"): "acme-token",
            ("bharat", "cloudflare"): "bharat-token",
        }
    )


def test_a_container_authenticates_as_its_own_client():
    backend = _two_clients()
    client = Container("acme", backend).http("cloudflare")
    assert client.headers["Authorization"] == "Bearer acme-token"


def test_a_container_cannot_reach_another_clients_credential():
    backend = _two_clients()
    acme = Container("acme", backend)
    with pytest.raises(UnknownCredential):
        acme.http("resend")
    # Every lookup this container made was scoped to its own client.
    assert all(name == "acme" for name, _ in backend.calls)
    assert not any(name == "bharat" for name, _ in backend.calls)


def test_the_raw_secret_is_never_returned_to_caller_code():
    """D6: adapters get an authenticated client, never a token. There is no
    public method on Container that hands back a secret."""
    backend = _two_clients()
    acme = Container("acme", backend)
    public = [n for n in dir(acme) if not n.startswith("_")]
    for name in public:
        attr = getattr(acme, name)
        if callable(attr):
            continue
        assert "acme-token" not in str(attr)
    assert "credential" not in public  # it is _credential, and stays that way


def test_has_reports_presence_without_revealing_the_value():
    backend = _two_clients()
    acme = Container("acme", backend)
    assert acme.has("cloudflare") is True
    assert acme.has("resend") is False


def test_an_unregistered_client_fails_at_construction_not_at_use():
    """'acme' vs 'acme-uk' would otherwise be a successful mutation on the
    wrong account (F5)."""
    backend = _two_clients()
    registry = Registry.__new__(Registry)
    registry._path = None
    registry.clients = lambda: [ClientRecord(name="acme")]

    assert Container.for_client(registry, "acme", backend).client == "acme"
    with pytest.raises(UnknownClient):
        Container.for_client(registry, "acme-uk", backend)


def test_an_unsupported_provider_is_absent_not_faked():
    """D11: an unimplemented provider raises rather than silently doing nothing."""
    with pytest.raises(UnsupportedProvider):
        Container("acme", _two_clients()).http("supabase")


def test_container_never_exposes_secrets_in_its_repr():
    acme = Container("acme", _two_clients())
    assert "acme-token" not in repr(acme)
    assert "bharat" not in repr(acme)
