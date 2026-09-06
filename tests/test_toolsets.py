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
    ("Acme Ltd", "acme_ltd"),
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
    sets = toolsets_for(["Acme Ltd", "Kloudfirst"], "cloudflare",
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
    uses to say which account it means, and the client is its leading segment
    so `acme_ltd_*` still means Acme and nobody else."""
    ring = FakeKeyring()
    a = toolset_for("Acme Ltd", "cloudflare", keyring=ring)
    b = toolset_for("Kloudfirst", "cloudflare", keyring=ring)
    assert a is not b
    assert a._prefix == "acme_ltd_cloudflare"
    assert b._prefix == "kloudfirst_cloudflare"
    assert a._prefix.startswith("acme_ltd")


def test_one_client_two_providers_do_not_collide():
    """Found by running it, not by a test. Vercel and Supabase both publish
    `list_projects`, so a client connected to both produced the same prefixed
    name twice and Strands refused to build the agent at all:

        ValueError: Tool name 'acme_ltd_list_projects' already exists.

    `toolsets_for` guards against two clients colliding. Nothing guarded one
    client's providers colliding with each other."""
    ring = FakeKeyring()
    vercel = toolset_for("Acme Ltd", "vercel", keyring=ring)
    supabase = toolset_for("Acme Ltd", "supabase", keyring=ring)

    assert vercel._prefix != supabase._prefix, \
        "two providers under one client produced the same tool names"


def test_each_client_authenticates_as_itself():
    """The property underneath the prefix: separate credentials, so two
    toolsets cannot borrow each other's session even if the naming were wrong."""
    from munim.remote.session import auth_for

    ring = FakeKeyring()
    a = auth_for("Acme Ltd", "cloudflare", keyring=ring)
    b = auth_for("Kloudfirst", "cloudflare", keyring=ring)
    assert a is not b
    assert a.context.client_metadata.client_name == "Munim (Acme Ltd)"
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


# ---- a server is authenticated the way it says it wants to be ------------
#
# `toolset_for` built an OAuth provider against `server.url` whatever the server
# said. Right for the eight that register a client on demand; wrong for the two
# that do not. Latent until the token-or-endpoint rule in `connected_providers`
# made a URL-authenticated provider reachable from an agent at all, at which
# point Zoho got a client pointed at the empty string.
#
# MCPClient keeps its url and headers inside a transport closure, so these
# assert at the seam rather than on the object.


class _Made:
    """Captures how MCPClient was constructed."""

    last = None

    def __init__(self, **kwargs):
        _Made.last = kwargs
        self._prefix = kwargs.get("prefix")


@pytest.fixture
def made(monkeypatch):
    import munim.remote.toolsets as toolsets_mod
    _Made.last = None
    monkeypatch.setattr(toolsets_mod, "MCPClient", _Made)
    return _Made


class _Vault(FakeKeyring):
    """A store holding a Zoho endpoint and a Stitch key, the way connect
    leaves them: vault-shaped for sessions, backend-shaped for pasted keys."""

    def __init__(self, endpoint="", key=""):
        super().__init__()
        self._endpoint = endpoint
        self._key = key

    def get_password(self, service, account):
        if self._endpoint and service.endswith(":endpoint"):
            return self._endpoint
        return super().get_password(service, account)

    def get(self, client, provider):
        return self._key or None

    def set(self, client, provider, secret):
        self._key = secret


def test_a_url_authenticated_provider_uses_its_own_endpoint(made):
    """Zoho's address carries the credential, so it is per client and lives in
    the store. Its entry in the provider table has no URL at all."""
    from munim.remote.servers import server_for

    assert server_for("zoho").url == "", \
        "this test is about a provider whose table entry has no URL"

    endpoint = "https://books-acme.zohomcp.in/mcp/" + "a" * 32
    toolset_for("c_1", "zoho", keyring=_Vault(endpoint=endpoint))

    assert made.last["url"] == endpoint, \
        "the agent was pointed at the provider table's empty URL"
    assert made.last.get("auth_provider") is None, \
        "a URL-authenticated provider was also given an OAuth client"


def test_a_header_authenticated_provider_gets_its_header(made):
    """Stitch wants an API key in a header. An OAuth provider is not something
    it can use, and building one starts a flow nobody asked for."""
    toolset_for("c_1", "stitch", keyring=_Vault(key="sk-test"))

    assert made.last["headers"], "no header was sent"
    assert made.last.get("auth_provider") is None, \
        "a header-authenticated provider was given an OAuth client"


def test_a_header_provider_with_no_key_is_refused_before_the_agent_runs():
    """Building a client with no credential turns a sentence before the run
    into a 401 in the middle of it."""
    from munim.remote.session import NeedsLogin

    with pytest.raises(NeedsLogin, match="API key"):
        toolset_for("c_1", "stitch", keyring=_Vault())


def test_an_oauth_provider_is_unchanged(made):
    """The eight that register a client on demand must keep the path they had."""
    toolset_for("Acme", "cloudflare", keyring=FakeKeyring())

    assert made.last["url"] == "https://mcp.cloudflare.com/mcp"
    assert made.last["auth_provider"] is not None
    assert made.last.get("headers") is None
