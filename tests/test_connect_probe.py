"""Calling one tool so a provider asks who you are.

`munim connect personal gmail` opened no browser and stored no token, and the
reason was not configuration. The SDK starts an OAuth flow when a request comes
back 401 with a challenge. Measured against Gmail on 2026-09-15:

    tools/list                     200  no challenge
    tools/call list_labels         401  www-authenticate: Bearer ...
    tools/call <no such tool>      200  JSON-RPC error
    resources/list                 404

The third line is why this exists at all: authorisation is checked after the
tool is dispatched, so a made-up name provokes nothing and only a real call
works. The tool is declared on the provider, never guessed, and checked against
the live listing before it is called.
"""

import pytest

from munim.remote.servers import RemoteServer, server_for
from munim.remote.session import _ask_for_credentials


def annotated(read_only=None, destructive=False):
    if read_only is None:
        return None
    return type("A", (), {"readOnlyHint": read_only,
                          "destructiveHint": destructive})()


def tool(name, *, read_only=None, destructive=False, schema=None):
    return type("T", (), {"name": name,
                          "annotations": annotated(read_only, destructive),
                          "inputSchema": schema or {"type": "object"}})()


class Recorder:
    """Only what the probe touches: which tool was called, with what."""

    def __init__(self, fails=None):
        self.called = []
        self._fails = fails

    async def call_tool(self, name, arguments):
        self.called.append((name, arguments))
        if self._fails:
            raise self._fails
        return type("R", (), {"content": [], "isError": True})()


async def _probe(provider, tools, fails=None):
    session = Recorder(fails)
    await _ask_for_credentials(session, provider, tools)
    return session


# ---- the declared tool ---------------------------------------------------

async def test_gmail_declares_the_tool_it_needs_called():
    assert server_for("gmail").probe_tool == "list_labels"


async def test_the_declared_tool_is_called_once_with_no_arguments():
    session = await _probe("gmail", [tool("list_labels", read_only=True)])
    assert session.called == [("list_labels", {})]


async def test_a_provider_that_declares_nothing_calls_nothing():
    """The regression that matters. Three providers already connect, and this
    must not add a tool call to any of them."""
    assert server_for("cloudflare").probe_tool == ""
    session = await _probe("cloudflare", [tool("execute", read_only=False)])
    assert session.called == []


# ---- what it refuses to call ---------------------------------------------

async def test_a_tool_the_provider_does_not_annotate_is_never_called(capsys):
    """`_read_only` is three-valued and None means the provider said nothing.
    Silence is not permission."""
    session = await _probe("gmail", [tool("list_labels", read_only=None)])

    assert session.called == []
    assert "not marked read-only" in capsys.readouterr().err


async def test_a_destructive_tool_is_never_called(capsys):
    """readOnlyHint and destructiveHint together: `_read_only` returns False,
    and the probe respects it rather than reading the first hint alone."""
    session = await _probe(
        "gmail", [tool("list_labels", read_only=True, destructive=True)])

    assert session.called == []
    assert "not marked read-only" in capsys.readouterr().err


async def test_a_tool_that_needs_arguments_is_never_called(capsys):
    session = await _probe("gmail", [tool(
        "list_labels", read_only=True,
        schema={"type": "object", "required": ["userId"]})])

    assert session.called == []
    assert "needs arguments" in capsys.readouterr().err


async def test_a_declared_tool_that_is_gone_is_not_substituted(capsys):
    """No fallback. If Google renames it, say so rather than quietly calling
    something the operator was never told about."""
    session = await _probe("gmail", [tool("search_threads", read_only=True),
                                     tool("list_drafts", read_only=True)])

    assert session.called == []
    said = capsys.readouterr().err
    assert "list_labels" in said and "is not in its tool list" in said


# ---- failure is not failure ----------------------------------------------

async def test_a_refusal_is_reported_and_does_not_raise(capsys):
    """When Google refuses because the account is not a test user, this line is
    the only account of why. Swallowing it leaves the operator with a generic
    'finish the consent screen' for a problem the consent screen cannot fix."""
    session = await _probe("gmail", [tool("list_labels", read_only=True)],
                           fails=RuntimeError("access_denied"))

    assert session.called == [("list_labels", {})]
    assert "access_denied" in capsys.readouterr().err


async def test_an_error_result_is_not_a_failure():
    """The token is the artifact. Whether labels came back is not this
    function's business, and `Recorder` returns isError=True throughout."""
    session = await _probe("gmail", [tool("list_labels", read_only=True)])
    assert session.called == [("list_labels", {})]


async def test_an_unknown_provider_calls_nothing():
    session = await _probe("not-a-provider", [tool("x", read_only=True)])
    assert session.called == []


# ---- the field survives being written down -------------------------------

def test_remember_round_trips_every_field(tmp_path, monkeypatch):
    """`remember` hand-wrote five keys and had already lost three. A field that
    survives only if somebody remembers to add it here will not survive."""
    from munim.remote import servers

    monkeypatch.setattr(servers, "USER_SERVERS", tmp_path / "servers.json")
    servers.remember(RemoteServer(
        provider="mine", url="https://example.test", public_client=True,
        probe_tool="ping", rest_takes_session=True, scopes=("a", "b"),
        header="X-Key"))

    back = servers._user_servers()["mine"]
    assert back.probe_tool == "ping"
    assert back.rest_takes_session is True
    assert back.scopes == ("a", "b"), "JSON has no tuples and the field is one"
    assert back.header == "X-Key"
