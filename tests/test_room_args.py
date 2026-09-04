"""The room's flags. Missing them cost a real debugging detour: `--port 8986`
was silently dropped, the room bound 8977 anyway and died on EADDRINUSE."""

from pathlib import Path

from munim.room.server import parse_args
from munim.runlog import RUNS_DIR


def test_port_defaults_to_8977():
    assert parse_args([]).port == 8977


def test_port_can_be_moved(monkeypatch):
    assert parse_args(["--port", "8986"]).port == 8986


def test_the_environment_still_works(monkeypatch):
    monkeypatch.setenv("MUNIM_ROOM_PORT", "9001")
    assert parse_args([]).port == 9001


def test_the_flag_beats_the_environment(monkeypatch):
    monkeypatch.setenv("MUNIM_ROOM_PORT", "9001")
    assert parse_args(["--port", "8986"]).port == 8986


def test_the_runs_directory_can_be_pointed_elsewhere():
    """Filming a recorded run means serving a different directory than the one
    live runs are written to."""
    assert parse_args([]).runs is None       # build_app falls back to RUNS_DIR
    assert parse_args(["--runs", "/tmp/demo"]).runs == Path("/tmp/demo")


def test_an_unknown_flag_is_an_error_not_a_shrug():
    """The whole point: argparse must reject what it does not understand."""
    import pytest
    with pytest.raises(SystemExit):
        parse_args(["--prot", "8986"])


def test_the_reports_directory_can_be_pointed_elsewhere():
    """A room pointed at one set of runs must not serve another set's reports."""
    assert parse_args([]).reports is None
    assert parse_args(["--reports", "/tmp/demo-reports"]).reports == Path("/tmp/demo-reports")


def test_build_app_keeps_runs_and_reports_together(tmp_path):
    from munim.room.server import build_app
    app = build_app(tmp_path / "runs", tmp_path / "reports")
    assert app.state.runs_dir == tmp_path / "runs"
    assert app.state.reports_dir == tmp_path / "reports"


def test_the_report_route_reads_the_configured_directory(tmp_path):
    """It imported REPORTS_DIR directly, so --runs moved the runs and left the
    reports behind."""
    import inspect

    from munim.room import server
    body = inspect.getsource(server.report)
    assert "app.state.reports_dir" in body
    assert "REPORTS_DIR" not in body
