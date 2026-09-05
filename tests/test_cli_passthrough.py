"""`munim tools` and `munim call`: the first verbs in this CLI that do work.

Everything before them was setup. The property worth guarding is the one that
motivated the whole change: these run with agents off. The model was the single
point of failure, and the conftest turns agents off for every test here, so any
model reaching into this path fails the suite rather than the operator.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry
from munim.remote import passthrough
from munim.remote.session import NeedsLogin


def tool(name, *, read_only=None, does=""):
    annotations = (None if read_only is None
                   else SimpleNamespace(readOnlyHint=read_only,
                                        destructiveHint=False))
    return SimpleNamespace(name=name, description=does, annotations=annotations,
                           inputSchema={"type": "object"})


class FakeSession:
    def __init__(self, tools, answer=None, fails=False):
        self._tools = tools
        self._answer = {"ok": True} if answer is None else answer
        self._fails = fails
        self.called = []

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.called.append((name, arguments))
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._answer))],
            structuredContent=None, isError=self._fails)


@pytest.fixture
def estate(tmp_path, monkeypatch):
    """One client called Acme, and a fake Cloudflare behind it."""
    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme", domain="acme.test"))
    monkeypatch.setattr(cli, "_registry", lambda: reg)
    # The run log has to land in tmp_path. `munim call` builds its own, and
    # RunLog's default is the real ~/.munim/runs.
    monkeypatch.setattr("munim.runlog.RUNS_DIR", tmp_path / "runs")

    session = FakeSession([
        tool("search", read_only=True, does="Search the docs"),
        tool("execute", does="Run JavaScript against the account"),
    ])

    @asynccontextmanager
    async def fake(client, provider, **kwargs):
        if provider != "cloudflare":
            raise NeedsLogin(f"{provider} is not connected. Run: munim connect")
        yield session

    monkeypatch.setattr(passthrough, "session_for", fake)
    return SimpleNamespace(registry=reg, session=session, runs=tmp_path / "runs")


def test_tools_lists_what_the_provider_exposes(estate, capsys):
    assert cli.main(["tools", "Acme", "cloudflare"]) == 0

    err = capsys.readouterr().err
    assert "search" in err and "execute" in err
    assert "Search the docs" in err
    # Three states shown, not two. `execute` is unannotated, and printing
    # "write" for it would assert something Cloudflare never said.
    assert "read " in err and "?" in err
    assert "munim call" in err, "the listing should say how to use what it lists"


def test_tools_as_json_is_machine_readable(estate, capsys):
    assert cli.main(["tools", "Acme", "cloudflare", "--json"]) == 0

    listed = json.loads(capsys.readouterr().out)
    by_name = {t["tool"]: t for t in listed}
    assert by_name["search"]["read_only"] is True
    assert by_name["execute"]["read_only"] is None


def test_call_runs_the_tool_and_prints_the_result_on_stdout(estate, capsys):
    """stdout is the result and stderr is everything else, so `| jq` works."""
    code = cli.main(["call", "Acme", "cloudflare", "execute",
                     "--args", '{"code": "zones.list()"}'])
    assert code == 0

    out, err = capsys.readouterr()
    assert json.loads(out) == {"ok": True}
    assert estate.session.called == [("execute", {"code": "zones.list()"})]
    assert "Recorded as" in err


def test_the_call_is_written_to_the_run_log(estate, capsys):
    cli.main(["call", "Acme", "cloudflare", "execute", "--args", '{"code": "x"}'])

    logs = list(estate.runs.glob("*.jsonl"))
    assert len(logs) == 1
    events = [json.loads(line) for line in logs[0].read_text().splitlines()]
    assert len(events) == 1
    assert events[0]["kind"] == "mutation"
    assert events[0]["detail"]["tool"] == "execute"
    assert events[0]["detail"]["arguments"] == {"code": "x"}


def test_no_arguments_is_allowed(estate, capsys):
    assert cli.main(["call", "Acme", "cloudflare", "search"]) == 0
    assert estate.session.called == [("search", {})]


def test_bad_json_is_refused_before_anything_is_called(estate, capsys):
    assert cli.main(["call", "Acme", "cloudflare", "execute",
                     "--args", "{not json"]) == 2

    assert "not JSON" in capsys.readouterr().err
    assert estate.session.called == []


def test_a_json_array_is_refused_because_tool_arguments_are_named(estate, capsys):
    assert cli.main(["call", "Acme", "cloudflare", "execute",
                     "--args", '["a", "b"]']) == 2

    assert "JSON object" in capsys.readouterr().err
    assert estate.session.called == []


def test_an_unknown_client_is_refused(estate, capsys):
    assert cli.main(["tools", "Nobody", "cloudflare"]) == 2
    assert "Nobody" in capsys.readouterr().err


def test_a_provider_that_is_not_connected_says_how_to_connect(estate, capsys):
    assert cli.main(["tools", "Acme", "vercel"]) == 2

    err = capsys.readouterr().err
    assert "munim connect" in err and "Acme" in err


def test_an_unknown_tool_points_at_the_listing(estate, capsys):
    assert cli.main(["call", "Acme", "cloudflare", "exec"]) == 2

    err = capsys.readouterr().err
    assert "execute" in err, "the message should name the real tools"
    assert "munim tools" in err


def test_a_refused_call_exits_nonzero_but_still_returns_the_body(
        tmp_path, monkeypatch, estate, capsys):
    """A provider saying no is information, so it is printed, not swallowed."""
    refusing = FakeSession([tool("execute")], answer={"error": "rate limited"},
                           fails=True)

    @asynccontextmanager
    async def fake(client, provider, **kwargs):
        yield refusing

    monkeypatch.setattr(passthrough, "session_for", fake)

    assert cli.main(["call", "Acme", "cloudflare", "execute"]) == 1
    out, err = capsys.readouterr()
    assert json.loads(out) == {"error": "rate limited"}
    assert "refused" in err


def test_none_of_this_needs_agents(estate, capsys):
    """The point of the whole change, asserted rather than described.

    conftest clears every model variable and points settings at tmp_path, so
    agents are off here exactly as they are on a fresh install. A path that
    quietly needed a model would fail this.
    """
    from munim import settings

    assert settings.ai().enabled is False
    assert cli.main(["tools", "Acme", "cloudflare"]) == 0
    assert cli.main(["call", "Acme", "cloudflare", "execute"]) == 0


def test_both_verbs_are_in_the_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    out = capsys.readouterr().out
    assert "tools" in out and "call" in out
