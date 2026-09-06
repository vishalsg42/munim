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
                        keyring=FakeKeyring())
    assert len(sets) == 2


def test_two_clients_that_would_share_a_prefix_are_refused():
    """"acme-uk" and "Acme UK" both become acme_uk. Letting the second win
    means one client's tools answer for the other, which is a successful
    mutation on the wrong account: the fault D5 exists to prevent."""
    with pytest.raises(ValueError, match="both become"):
        toolsets_for(["acme-uk", "Acme UK"], "cloudflare", keyring=FakeKeyring())


def test_a_provider_with_no_mcp_server_is_refused():
    """Named a real provider once, and that provider turned out to have a
    server. A name that cannot acquire one keeps the assertion about the code."""
    with pytest.raises(NoRemoteServer):
        toolset_for("Acme", "a-provider-that-does-not-exist", keyring=FakeKeyring())


def test_two_toolsets_for_one_provider_are_told_apart_by_name():
    """Same server, same process, two clients. The prefix is what a tool call
    uses to say which account it means."""
    ring = FakeKeyring()
    a = toolset_for("Balaji Roofings", "cloudflare", keyring=ring)
    b = toolset_for("Kloudfirst", "cloudflare", keyring=ring)
    assert a is not b
    assert a._prefix == "balaji_roofings"
    assert b._prefix == "kloudfirst"


def test_each_client_authenticates_as_itself():
    """The property underneath the prefix: separate credentials, so two
    toolsets cannot borrow each other's session even if the naming were wrong."""
    from munim.remote.session import auth_for

    ring = FakeKeyring()
    a = auth_for("Balaji Roofings", "cloudflare", keyring=ring)
    b = auth_for("Kloudfirst", "cloudflare", keyring=ring)
    assert a is not b
    assert a.context.client_metadata.client_name == "Munim (Balaji Roofings)"
    assert b.context.client_metadata.client_name == "Munim (Kloudfirst)"
    # and their stores do not share a key
    assert a.context.storage._client != b.context.storage._client


class _Tool:
    def __init__(self, read_only=None, destructive=None, annotated=True):
        from types import SimpleNamespace
        annotations = (SimpleNamespace(readOnlyHint=read_only,
                                       destructiveHint=destructive)
                       if annotated else None)
        self.mcp_tool = SimpleNamespace(annotations=annotations)


def test_only_provably_read_only_tools_cross_clients():
    """Default deny. "Read across, write within" has to be a property of which
    tools exist, not an instruction the model is asked to follow: an
    instruction is not a boundary."""
    from munim.remote.toolsets import _is_read_only

    assert _is_read_only(_Tool(read_only=True)) is True
    assert _is_read_only(_Tool(read_only=False)) is False
    assert _is_read_only(_Tool(annotated=False)) is False, \
        "an unannotated tool is not provably read-only"
    assert _is_read_only(_Tool(read_only=None)) is False


def test_a_destructive_tool_is_excluded_even_if_it_claims_read_only():
    from munim.remote.toolsets import _is_read_only

    assert _is_read_only(_Tool(read_only=True, destructive=True)) is False


def test_a_cross_client_toolset_carries_the_filter_and_a_single_client_does_not():
    """Write within: naming one client is what unlocks its writes."""
    across = toolset_for("Acme", "cloudflare", keyring=FakeKeyring(), read_only=True)
    within = toolset_for("Acme", "cloudflare", keyring=FakeKeyring())
    assert across._tool_filters is not None
    assert within._tool_filters is None
