"""A per-installation address and a login are two facts, not one.

`auth="url"` used to mean both "each installation has its own address" and "the
address is the credential, so there is no login". Zoho is both halves of the
first and neither of the second: measured 2026-09-15, its endpoint answers
tools/list with 401 and a Bearer challenge, and the protected resource metadata
names a per-installation authorization server under mcp.zoho.in/baas/ that
advertises a registration endpoint.

Conflating the two left no route in. `connect --url` refused anything the probe
did not call `url`, and connecting without `--url` had no address to connect to
because the table has none. So `per_client_url` is now its own field and
nothing reads an address out of the table for a provider that has no one
address.
"""

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry
from munim.remote.servers import SERVERS, RemoteServer
from munim.remote.session import endpoint_for
from munim.remote.storage import KeychainTokenStorage


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


def test_the_two_facts_are_two_fields():
    """The table can say "per installation" without saying "no login"."""
    zoho = SERVERS["zoho"]
    assert zoho.per_client_url, "zoho has no one address"
    assert zoho.url == "", "so the table must not carry one"
    assert zoho.auth == "registers", "and it still wants a login"
    assert not zoho.ready, "which the operator has to supply an address for"


def test_two_clients_hold_two_installations():
    """The point of the whole thing: one client's address is not another's."""
    ring = Ring()
    KeychainTokenStorage("c_1", "zoho", ring).remember_endpoint(
        "https://books-one.zohomcp.in/mcp/" + "a" * 32)
    KeychainTokenStorage("c_2", "zoho", ring).remember_endpoint(
        "https://mail-two.zohomcp.in/mcp/" + "b" * 32)

    assert endpoint_for("c_1", "zoho", ring).startswith("https://books-one.")
    assert endpoint_for("c_2", "zoho", ring).startswith("https://mail-two.")


def test_a_stored_endpoint_wins_over_the_table():
    """`--url` is explicit, so it beats a shared address rather than being
    ignored. This used to be consulted only for `url` providers, which is the
    assumption that made a per-installation OAuth provider unreachable."""
    ring = Ring()
    mine = "https://mcp.cloudflare.test/mine"
    KeychainTokenStorage("c_1", "cloudflare", ring).remember_endpoint(mine)

    assert endpoint_for("c_1", "cloudflare", ring) == mine
    assert endpoint_for("c_2", "cloudflare", ring) == SERVERS["cloudflare"].url


def test_with_no_endpoint_at_all_the_refusal_names_the_flag():
    ring = Ring()
    from munim.remote.session import NoRemoteServer

    with pytest.raises(NoRemoteServer) as raised:
        endpoint_for("c_1", "zoho", ring)
    assert "--url" in str(raised.value)


@pytest.fixture
def world(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "r.json")
    ring = Ring()
    monkeypatch.setattr(cli, "_registry", lambda: registry)
    monkeypatch.setattr("munim.remote.storage.vault", ring)
    return registry, ring


def _probes_as(monkeypatch, auth):
    async def probe(url, name=""):
        return RemoteServer(provider=name or "zoho", url=url,
                            public_client=True, auth=auth, note="a test")
    monkeypatch.setattr("munim.remote.discover.probe", probe)


def test_an_endpoint_that_challenges_is_recorded_and_then_logged_in(
        world, monkeypatch):
    """The refusal this replaces sent the operator to a command with no address
    to use, so there was no order in which the two could be run."""
    registry, ring = world
    _probes_as(monkeypatch, "registers")

    went_to = {}
    monkeypatch.setattr(cli, "connect_via_mcp",
                        lambda c, p: went_to.update(client=c, provider=p) or 0)

    url = "https://books-acme.zohomcp.in/mcp/" + "a" * 32
    assert cli.connect_by_url("Acme Ltd", "zoho", url) == 0

    record = registry.get("Acme Ltd")
    assert KeychainTokenStorage(record.id, "zoho", ring).endpoint() == url, \
        "the login has nothing to log in against unless this is written first"
    assert went_to == {"client": "Acme Ltd", "provider": "zoho"}


def test_an_endpoint_that_needs_no_login_still_just_stores(world, monkeypatch):
    registry, ring = world
    _probes_as(monkeypatch, "url")
    monkeypatch.setattr(cli, "connect_via_mcp", lambda c, p: pytest.fail(
        "a credential-carrying URL has nothing to log in to"))

    url = "https://books-acme.zohomcp.in/mcp/" + "b" * 32
    assert cli.connect_by_url("Acme Ltd", "zoho", url) == 0
    assert KeychainTokenStorage(
        registry.get("Acme Ltd").id, "zoho", ring).endpoint() == url


def test_a_provider_with_one_address_for_everybody_is_refused(world):
    """`--url` on a shared-address provider is a misunderstanding worth saying
    out loud, rather than quietly filing one client's private address."""
    registry, ring = world
    assert cli.connect_by_url("Acme Ltd", "cloudflare",
                              "https://mcp.cloudflare.test/x") == 2
