"""`munim doctor` tells someone what is missing and the one step that fixes it.

For a tool strangers install, "it does not work" is the failure that loses them,
so every finding carries a fix and the exit code distinguishes broken from
merely improvable.
"""

from munim import doctor
from munim.registry import ClientRecord, Registry


def test_a_missing_model_host_is_broken_not_merely_improvable(monkeypatch):
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY",
                "AWS_PROFILE", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(doctor, "load_env", lambda: None)
    finding = doctor._model()
    assert finding.status == doctor.BAD
    assert "GEMINI_API_KEY" in finding.fix


def test_a_configured_model_host_passes(monkeypatch):
    monkeypatch.setattr(doctor, "load_env", lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert doctor._model().status == doctor.OK


def test_every_finding_that_is_not_ok_carries_a_fix(monkeypatch, tmp_path):
    """A report that says something is wrong without saying what to do is the
    thing this command exists to replace."""
    monkeypatch.setattr(doctor, "load_env", lambda: None)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY",
                "AWS_PROFILE", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(key, raising=False)
    registry = Registry(tmp_path / "r.json")
    findings = [doctor._model(), doctor._room(), *doctor._oauth_apps(),
                *doctor._clients(registry)]
    for finding in findings:
        if finding.status != doctor.OK:
            assert finding.fix, f"{finding.what} reports a problem with no fix"


def test_resend_is_reported_as_reachable_now_that_it_runs_an_mcp_server():
    """This used to assert "not applicable", and that was right while Resend
    published no OAuth endpoint of its own. It runs an MCP server, which does,
    so the honest report is that it is ready rather than exempt."""
    resend = [f for f in doctor._oauth_apps() if "resend" in f.what][0]
    assert resend.status == doctor.OK
    assert "MCP server" in resend.detail


def test_a_provider_with_an_mcp_server_is_never_told_to_register_an_app():
    """Nobody registers an application for a provider that registers a client
    on demand. Telling them to is worse than saying nothing."""
    from munim.remote.servers import SERVERS

    for finding in doctor._oauth_apps():
        provider = finding.what.split(":", 1)[1].strip()
        if provider in SERVERS:
            assert finding.status == doctor.OK, provider
            assert not finding.fix, f"{provider} is told to register an app"


def test_an_unconnected_client_is_a_warning_with_the_command(tmp_path):
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="Ivy & Fern"))
    findings = doctor._clients(registry)
    unconnected = [f for f in findings if "Ivy & Fern" in f.what][0]
    assert unconnected.status == doctor.WARN
    assert "munim connect" in unconnected.fix
