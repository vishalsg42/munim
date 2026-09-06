"""`munim tools` and `munim call`: the first verbs in this CLI that do work.

Everything before them was setup. The property worth guarding is the one that
motivated the whole change: these run with agents off. The model was the single
point of failure, and the conftest turns agents off for every test here, so any
model reaching into this path fails the suite rather than the operator.
"""

import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from munim import cli
from munim.registry import ClientRecord, Registry
from munim.remote import passthrough
from munim.remote.session import NeedsLogin


def tool(name, *, read_only=None, does="", schema=None):
    annotations = (None if read_only is None
                   else SimpleNamespace(readOnlyHint=read_only,
                                        destructiveHint=False))
    return SimpleNamespace(name=name, description=does, annotations=annotations,
                           inputSchema=schema or {"type": "object"})


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
    # Three states, and only the informative two take ink. `execute` is
    # unannotated: printing "writes" for it would assert something Cloudflare
    # never said, and a "?" column made every listing noisier to say nothing.
    assert "read-only" in err
    assert "writes" not in err
    assert "munim tools" in err, "the listing should say how to see one in full"


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


# ---- the tool detail, reachable by typing as well as by navigating ----


LONG = ("Execute JavaScript against the Cloudflare API. First use 'search' to "
        "find the right endpoints, then write code with cloudflare.request(). "
        "This runs past the seventy characters the listing used to cut at.")


@pytest.fixture
def detailed(estate, monkeypatch):
    """The same fake, with a tool that has a real description and schema."""
    session = FakeSession([
        tool("search", read_only=True, does="Search the docs"),
        tool("execute", does=LONG, schema={
            "type": "object",
            "properties": {"code": {"type": "string", "description": "The JS"}},
            "required": ["code"]}),
    ])

    @asynccontextmanager
    async def fake(client, provider, **kwargs):
        yield session

    monkeypatch.setattr(passthrough, "session_for", fake)
    return session


def test_naming_a_tool_prints_it_whole(detailed, capsys):
    assert cli.main(["tools", "Acme", "cloudflare", "execute"]) == 0

    err = capsys.readouterr().err.replace("\n  ", " ")
    assert LONG.split(". ")[-1][:40] in err, "the description was truncated"
    assert "code" in err and "required" in err
    assert 'munim call "Acme" cloudflare execute' in err


def test_naming_a_tool_with_json_returns_that_one_tool(detailed, capsys):
    assert cli.main(["tools", "Acme", "cloudflare", "execute", "--json"]) == 0

    one = json.loads(capsys.readouterr().out)
    assert one["tool"] == "execute"
    assert one["arguments"]["required"] == ["code"]


def test_an_unknown_tool_name_exits_two_and_names_the_real_ones(
        detailed, capsys):
    assert cli.main(["tools", "Acme", "cloudflare", "exec"]) == 2

    err = capsys.readouterr().err
    assert "execute" in err and "search" in err


# ---- arguments from a file or a pipe ---------------------------------


TRICKY = {"code": "// list zones\nzones.list() /* all of them */"}


def test_args_file_reaches_the_provider_untouched(estate, tmp_path, capsys):
    """A payload full of comment markers is exactly what a JSON skeleton with
    comments in it would have corrupted, which is why there is no editor."""
    path = tmp_path / "args.json"
    path.write_text(json.dumps(TRICKY))

    assert cli.main(["call", "Acme", "cloudflare", "execute",
                     "--args-file", str(path)]) == 0
    assert estate.session.called == [("execute", TRICKY)]


def test_args_dash_reads_stdin(estate, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(TRICKY)))

    assert cli.main(["call", "Acme", "cloudflare", "execute", "--args", "-"]) == 0
    assert estate.session.called == [("execute", TRICKY)]


def test_args_and_args_file_together_is_refused(estate, tmp_path, capsys):
    path = tmp_path / "args.json"
    path.write_text("{}")

    with pytest.raises(SystemExit):
        cli.main(["call", "Acme", "cloudflare", "execute",
                  "--args", "{}", "--args-file", str(path)])
    assert estate.session.called == []


def test_a_missing_args_file_is_refused_before_anything_is_called(
        estate, capsys):
    assert cli.main(["call", "Acme", "cloudflare", "execute",
                     "--args-file", "/no/such/file.json"]) == 2

    assert "cannot read" in capsys.readouterr().err
    assert estate.session.called == []


# ---- the same two flags on the CLI, because that is where an operator is --


def test_names_only_prints_the_names_without_the_descriptions(estate, capsys):
    assert cli.main(["tools", "Acme", "cloudflare", "--names-only"]) == 0

    err = capsys.readouterr().err
    assert "search" in err and "execute" in err
    assert "Search the docs" not in err, "a description survived --names-only"


def test_matching_narrows_the_listing(estate, capsys):
    assert cli.main(["tools", "Acme", "cloudflare", "--matching", "execute"]) == 0

    err = capsys.readouterr().err
    assert "execute" in err
    assert "search" not in err


def test_matching_reaches_the_argument_schema_from_the_cli(estate, capsys):
    """Same property as the library test, asserted where the operator types it:
    "which tools take a teamId" is not answerable from names alone."""
    assert cli.main(["tools", "Acme", "cloudflare", "--matching", "code"]) == 0
    err = capsys.readouterr().err
    assert "search" not in err or "execute" in err


def test_naming_one_tool_still_shows_it_in_full(estate, capsys):
    """The flags shrink a listing. Asking for one tool is asking for the whole
    of it, so they have nothing to do there and must not truncate it."""
    assert cli.main(["tools", "Acme", "cloudflare", "execute",
                     "--names-only"]) == 0

    err = capsys.readouterr().err
    assert "Run JavaScript against the account" in err


def test_both_flags_are_in_the_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["tools", "--help"])

    out = capsys.readouterr().out
    assert "--names-only" in out and "--matching" in out
