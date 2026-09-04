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


def test_a_provider_that_registers_on_demand_is_never_told_to_register_an_app():
    """Nobody registers an application for a provider that issues a client on
    demand. Telling them to is worse than saying nothing.

    The condition is `ready`, not "is in the table". Gmail and Stitch are in the
    table and cannot register on demand: accounts.google.com publishes no
    registration endpoint, so an application by hand is the only way in and
    doctor has to say so. This asserted "in SERVERS" and so demanded silence
    about the two providers that most need a word.
    """
    from munim.remote.servers import SERVERS

    for finding in doctor._oauth_apps():
        provider = finding.what.split(":", 1)[1].strip()
        server = SERVERS.get(provider)
        if server is not None and server.ready:
            assert finding.status == doctor.OK, provider
            assert not finding.fix, f"{provider} is told to register an app"


def test_an_unconnected_client_is_a_warning_with_the_command(tmp_path):
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="Ivy & Fern"))
    findings = doctor._clients(registry)
    unconnected = [f for f in findings if "Ivy & Fern" in f.what][0]
    assert unconnected.status == doctor.WARN
    assert "munim connect" in unconnected.fix


def test_the_keychain_is_reported_when_there_is_none(monkeypatch):
    """A machine with no keychain backend, which is most Linux servers and
    every CI runner, used to take doctor down with a stack trace.

    Reads degrade to "nothing connected", which is right for a library and
    wrong for a diagnosis: a client that is connected and reads as disconnected
    is the most confusing state this tool can be in."""
    import keyring
    import keyring.errors

    def boom(*a, **k):
        raise keyring.errors.NoKeyringError("No recommended backend was available")

    monkeypatch.setattr(keyring, "get_password", boom)
    finding = doctor._keychain()
    assert finding.status == doctor.BAD
    assert "no backend" in finding.detail
    assert finding.fix, "a diagnosis with no next step is a complaint"


def test_a_missing_keychain_does_not_take_the_client_list_down(monkeypatch, tmp_path):
    import keyring
    import keyring.errors

    def boom(*a, **k):
        raise keyring.errors.NoKeyringError("nope")

    monkeypatch.setattr(keyring, "get_password", boom)
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="acme"))
    findings = doctor._clients(registry)          # must not raise
    assert any("acme" in f.what for f in findings)


def test_the_coding_agent_check_resolves_the_executable(monkeypatch):
    """On Windows it is claude.cmd, which a bare name in a subprocess list does
    not find."""
    import inspect

    source = inspect.getsource(doctor._mcp_registered)
    assert 'shutil.which("claude")' in source
    assert '["claude", "mcp", "list"]' not in source, \
        "passing the bare name will not resolve claude.cmd on Windows"
