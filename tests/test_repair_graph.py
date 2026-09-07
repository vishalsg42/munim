"""The edge is the boundary, so the edge is what gets tested.

An earlier draft of this graph had `condition=lambda _state: bool(findings)`
closing over a list computed before the graph was built. A reviewer pointed out
that `run_checks` returns every result regardless of status, so that list was
never empty and the condition was a constant `True`: an `if` statement wearing a
graph, and one that would have routed every clean domain into the repair node.

So these tests are about the predicate rather than about Strands. If the write
boundary is a function of DNS answers and stored credentials, it can be asserted
without a model, and it should be.
"""

from dataclasses import dataclass

import pytest

from munim.agent import graph as graph_mod
from munim.agent.repair import RepairRun
from munim.runlog import RunLog, new_run_id


@dataclass
class _Result:
    check: str
    status: str
    human_text: str = "something"
    operator_text: str = ""


class _Keys:
    """A container, as far as `can_write` is concerned."""

    def __init__(self, *held):
        self.held = set(held)

    def has(self, provider):
        return provider in self.held


def _run(tmp_path, *, results=(), holds=("cloudflare", "resend"),
         domain="acme.example"):
    return RepairRun(
        run_id=new_run_id(), client="Acme Ltd", client_id="c_1", domain=domain,
        log=RunLog(new_run_id(), tmp_path / "runs"),
        container=_Keys(*holds) if holds is not None else None,
        results=list(results))


def _may_repair(run):
    return graph_mod.mail_is_repairable(None, invocation_state={"run": run})


# ---- the predicate ---------------------------------------------------------


def test_a_repairable_failure_reaches_the_repair_node(tmp_path):
    run = _run(tmp_path, results=[_Result("dkim_present", "fail")])

    assert _may_repair(run) is True


def test_a_clean_domain_never_reaches_the_repair_node(tmp_path):
    """The regression. Every check passing must not route to a repair, and the
    first version of this could not tell the difference because it looked at
    how many results there were rather than at what they said."""
    run = _run(tmp_path, results=[_Result("dkim_present", "pass"),
                                  _Result("spf_single", "pass"),
                                  _Result("mx_present", "pass")])

    assert _may_repair(run) is False
    assert "nothing is failing" in graph_mod.why_repair_was_skipped(run)


def test_a_failure_this_path_cannot_fix_does_not_reach_it(tmp_path):
    """`mailplan` builds its changes from what Resend publishes for a sending
    domain. A certificate or CAA failure arriving at the repair node would find
    one tool that sets up mail and nothing that addresses the fault, and a model
    with a mismatched tool improvises."""
    run = _run(tmp_path, results=[_Result("cert_valid", "fail"),
                                  _Result("caa_allows", "fail")])

    assert _may_repair(run) is False
    why = graph_mod.why_repair_was_skipped(run)
    assert "cert_valid" in why and "caa_allows" in why


def test_a_client_with_no_api_key_never_reaches_the_repair_node(tmp_path):
    """The two-store split, as an edge condition.

    A client connected only through a browser has a session with Resend's MCP
    server and no API key, and those are not the same credential: measured, an
    MCP token sent to Resend's REST API answers 403. `mailplan` uses the REST
    API, so this is a real precondition.
    """
    run = _run(tmp_path, holds=(), results=[_Result("dkim_present", "fail")])

    assert _may_repair(run) is False


def test_one_missing_key_is_enough_to_stop_it(tmp_path):
    run = _run(tmp_path, holds=("cloudflare",),
               results=[_Result("dkim_present", "fail")])

    assert _may_repair(run) is False
    assert "resend" in graph_mod.why_repair_was_skipped(run)


def test_a_platform_domain_is_not_the_clients_to_change(tmp_path):
    run = _run(tmp_path, domain="acme.vercel.app",
               results=[_Result("dkim_present", "fail")])

    assert _may_repair(run) is False
    assert "platform domain" in graph_mod.why_repair_was_skipped(run)


def test_the_predicate_survives_being_asked_about_nothing(tmp_path):
    """Strands calls the condition with whatever invocation_state it was given.
    A predicate that raises inside the graph fails the whole run."""
    assert graph_mod.mail_is_repairable(None, invocation_state={}) is False
    assert graph_mod.mail_is_repairable(None, invocation_state=None) is False


# ---- the second edge --------------------------------------------------------


def test_the_recheck_only_runs_if_something_was_written(tmp_path):
    run = _run(tmp_path)

    assert graph_mod.something_was_published(
        None, invocation_state={"run": run}) is False
    run.applied = True
    assert graph_mod.something_was_published(
        None, invocation_state={"run": run}) is True


# ---- why a skipped repair is never silent ------------------------------------


def test_every_reason_to_skip_produces_a_sentence(tmp_path):
    """An untraversed edge is silent, and in the rail a silent step looks
    exactly like one that hung. That is the bug the ghost stage cells were, and
    reintroducing it one layer up would be worse, because here there really was
    a decision with a reason."""
    cases = [
        _run(tmp_path, holds=(), results=[_Result("dkim_present", "fail")]),
        _run(tmp_path, domain="x.pages.dev",
             results=[_Result("dkim_present", "fail")]),
        _run(tmp_path, results=[_Result("cert_valid", "fail")]),
        _run(tmp_path, results=[_Result("mx_present", "pass")]),
    ]

    for run in cases:
        assert not _may_repair(run)
        assert graph_mod.why_repair_was_skipped(run), \
            f"no reason given for {run.domain} holding {run.container.held}"


def test_a_repair_that_will_run_has_no_reason_to_skip(tmp_path):
    run = _run(tmp_path, results=[_Result("spf_single", "fail")])

    assert graph_mod.why_repair_was_skipped(run) == ""


# ---- what the model is told --------------------------------------------------


def test_the_task_names_only_the_failures(tmp_path):
    run = _run(tmp_path, results=[_Result("dkim_present", "fail", "no DKIM"),
                                  _Result("mx_present", "pass", "fine")])

    task = graph_mod.task_for(run)

    assert "no DKIM" in task
    assert "fine" not in task, "a passing check was presented as a problem"
    assert "acme.example" in task


def test_the_task_says_so_when_nothing_failed(tmp_path):
    run = _run(tmp_path, results=[_Result("mx_present", "pass")])

    assert "nothing is failing" in graph_mod.task_for(run)


# ---- the shape of the graph --------------------------------------------------


class _Model:
    """Enough of a Strands model for `Agent(...)` to build.

    `object()` is not enough any more: the constructor reads `model.stateful`.
    Worth a named class rather than a lambda, because a bare object failing
    here reads as a graph bug rather than as a test double being too thin.
    """

    stateful = False

    def get_config(self):
        return {}


def test_the_graph_has_three_nodes_and_two_edges(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mod, "build_model",
                        lambda *a, **k: (_Model(), "fake"))
    run = _run(tmp_path, results=[_Result("dkim_present", "fail")])

    graph, gate = graph_mod.build(run)

    assert set(graph.nodes) == {"triage", "repair", "recheck"}
    assert len(graph.edges) == 2
    assert gate.run is run


def test_every_node_is_built_with_printing_turned_off():
    """Strands' default callback handler prints tokens to stdout, and on a
    stdio MCP server stdout is the JSON-RPC channel. One stray line and the
    coding agent drops the server mid-run."""
    import inspect

    source = inspect.getsource(graph_mod.build)

    assert source.count("callback_handler=None") == 3, \
        "every agent in the graph must be built with callback_handler=None"


@pytest.mark.parametrize("module", ["graph", "repair", "gate", "watch"])
def test_no_new_agent_module_prints_to_stdout(module):
    """The existing test inspects only `launch.explain`, so it would pass
    happily while four new modules streamed tokens into the protocol."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(f"munim.agent.{module}"))
    offenders = [line.strip() for line in source.splitlines()
                 if line.strip().startswith("print(")]

    assert offenders == [], f"{module} writes to stdout: {offenders}"
