"""The security claim of the project, tested on day one rather than day eight."""

import pytest

from mcpc.container import Container, UnknownCredential


class FakeBackend:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def get(self, client: str, provider: str):
        self.calls.append((client, provider))
        return self.store.get((client, provider))


def test_container_reads_its_own_credential():
    backend = FakeBackend({("acme", "vercel"): "acme-token"})
    assert Container("acme", backend).credential("vercel") == "acme-token"


def test_container_cannot_reach_another_clients_credential():
    backend = FakeBackend(
        {
            ("acme", "vercel"): "acme-token",
            ("bharat", "vercel"): "bharat-token",
        }
    )
    acme = Container("acme", backend)
    with pytest.raises(UnknownCredential):
        acme.credential("cloudflare")
    # Every lookup this container made was scoped to its own client.
    assert all(client == "acme" for client, _ in backend.calls)


def test_a_container_cannot_be_widened_to_another_client():
    backend = FakeBackend(
        {
            ("acme", "vercel"): "acme-token",
            ("bharat", "vercel"): "bharat-token",
        }
    )
    acme = Container("acme", backend)
    assert acme.credential("vercel") == "acme-token"
    # There is no API that returns another client's secret from this container.
    assert acme.client == "acme"
    assert all(client == "acme" for client, _ in backend.calls)


def test_container_never_exposes_secrets_in_its_repr():
    backend = FakeBackend({("acme", "vercel"): "acme-token"})
    acme = Container("acme", backend)
    assert "acme-token" not in repr(acme)
