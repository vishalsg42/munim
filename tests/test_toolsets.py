"""Every client's provider tools in one agent, told apart by name.

The prefix is the only thing between "update this DNS record" and doing it in
the wrong account, so it is derived from the registered client name and a
collision is an error rather than something resolved quietly.
"""

import pytest

from munim.remote.session import NoRemoteServer
from munim.remote.toolsets import prefix_for, toolset_for, toolsets_for


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret


@pytest.mark.parametrize("name,expected", [
    ("Balaji Roofings", "balaji_roofings"),
    ("Ivy & Fern Studio", "ivy_fern_studio"),
    ("  Kloudfirst  ", "kloudfirst"),
    ("acme-uk", "acme_uk"),
])
def test_a_prefix_comes_from_the_client_name(name, expected):
    assert prefix_for(name) == expected


def test_a_name_that_leaves_nothing_is_refused():
    with pytest.raises(ValueError, match="nothing to name tools with"):
        prefix_for("   ")


def test_each_client_gets_its_own_prefix():
    sets = toolsets_for(["Balaji Roofings", "Kloudfirst"], "cloudflare",
                        backend=FakeKeyring())
    assert len(sets) == 2


def test_two_clients_that_would_share_a_prefix_are_refused():
    """"acme-uk" and "Acme UK" both become acme_uk. Letting the second win
    means one client's tools answer for the other, which is a successful
    mutation on the wrong account: the fault D5 exists to prevent."""
    with pytest.raises(ValueError, match="both become"):
        toolsets_for(["acme-uk", "Acme UK"], "cloudflare", backend=FakeKeyring())


def test_a_provider_with_no_mcp_server_is_refused():
    with pytest.raises(NoRemoteServer):
        toolset_for("Acme", "supabase", backend=FakeKeyring())


def test_two_toolsets_for_one_provider_are_told_apart_by_name():
    """Same server, same process, two clients. The prefix is what a tool call
    uses to say which account it means."""
    ring = FakeKeyring()
    a = toolset_for("Balaji Roofings", "cloudflare", backend=ring)
    b = toolset_for("Kloudfirst", "cloudflare", backend=ring)
    assert a is not b
    assert a._prefix == "balaji_roofings"
    assert b._prefix == "kloudfirst"


def test_each_client_authenticates_as_itself():
    """The property underneath the prefix: separate credentials, so two
    toolsets cannot borrow each other's session even if the naming were wrong."""
    from munim.remote.session import auth_for

    ring = FakeKeyring()
    a = auth_for("Balaji Roofings", "cloudflare", backend=ring)
    b = auth_for("Kloudfirst", "cloudflare", backend=ring)
    assert a is not b
    assert a.context.client_metadata.client_name == "Munim (Balaji Roofings)"
    assert b.context.client_metadata.client_name == "Munim (Kloudfirst)"
    # and their stores do not share a key
    assert a.context.storage._client != b.context.storage._client
