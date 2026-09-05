"""`munim doctor` tells someone what is missing and the one step that fixes it.

For a tool strangers install, "it does not work" is the failure that loses them,
so every finding carries a fix and the exit code distinguishes broken from
merely improvable.
"""

from munim import doctor
from munim.registry import ClientRecord, Registry


def test_no_model_host_is_not_broken_when_agents_are_off(monkeypatch):
    """This used to assert BAD, under the name
    `test_a_missing_model_host_is_broken_not_merely_improvable`, and that was
    right while having a key was how you consented to using one.

    Agents are opt-in now, so no model host is the default and intended state.
    A fresh install reporting itself broken for behaving exactly as designed is
    how people learn to ignore the report.
    """
    monkeypatch.setattr(doctor, "load_env", lambda: None)
    findings = doctor._agents()
    assert all(f.status != doctor.BAD for f in findings), \
        [f.detail for f in findings]
    assert any("off" in f.detail for f in findings)
    assert any("munim config ai on" in f.fix for f in findings)


def test_agents_on_with_no_usable_host_is_broken(monkeypatch):
    """The other direction, which is what makes the test above mean something.

    Asserting only that nothing is BAD would pass just as well if `_agents`
    never reported anything at all.
    """
    from munim import settings

    monkeypatch.setattr(doctor, "load_env", lambda: None)
    monkeypatch.setenv("MUNIM_AI", "1")
    monkeypatch.setattr(settings, "installed", lambda host: False)
    findings = doctor._agents()
    assert any(f.status == doctor.BAD for f in findings), \
        [f.detail for f in findings]


def test_a_usable_host_passes(monkeypatch):
    from munim import settings

    monkeypatch.setattr(doctor, "load_env", lambda: None)
    monkeypatch.setenv("MUNIM_AI", "1")
    monkeypatch.setenv("MUNIM_AI_HOST", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(settings, "installed", lambda host: True)
    findings = doctor._agents()
    assert any(f.status == doctor.OK and "gemini" in f.detail for f in findings), \
        [f.detail for f in findings]


def test_a_key_with_agents_off_is_pointed_out(monkeypatch):
    """The upgrade case. Somebody on 0.2.1 had a key and got explanations; after
    this they do not, and the prose would otherwise just quietly stop."""
    monkeypatch.setattr(doctor, "load_env", lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    findings = doctor._agents()
    assert any(f.status == doctor.WARN and "unused" in f.detail
               for f in findings), [f.detail for f in findings]


def test_every_finding_that_is_not_ok_carries_a_fix(monkeypatch, tmp_path):
    """A report that says something is wrong without saying what to do is the
    thing this command exists to replace."""
    monkeypatch.setattr(doctor, "load_env", lambda: None)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY",
                "AWS_PROFILE", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(key, raising=False)
    registry = Registry(tmp_path / "r.json")
    findings = [*doctor._agents(), doctor._room(), doctor._settings_file(),
                *doctor._oauth_apps(), *doctor._clients(registry)]
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


def test_an_unusable_credential_store_is_reported(monkeypatch, tmp_path):
    """This used to simulate a machine with no keychain backend, which was most
    Linux servers and every CI runner, and which took doctor down with a stack
    trace before it degraded to "nothing connected".

    A file has a state the keychain did not: it exists and cannot be read. That
    must not read as "nothing connected", because a client that is connected and
    reports as disconnected is the most confusing state this tool can be in.
    """
    broken = tmp_path / "credentials.json"
    broken.write_text("{not json")
    monkeypatch.setenv("MUNIM_CREDENTIALS", str(broken))

    finding = doctor._keychain()
    assert finding.status == doctor.BAD
    assert finding.fix, "a problem with no next step is a complaint"
    assert "will not overwrite" in finding.fix, \
        "it must say it is refusing rather than silently starting fresh"


def test_a_store_that_has_nothing_yet_is_fine(monkeypatch, tmp_path):
    """The other direction. A fresh install has no file and that is normal."""
    monkeypatch.setenv("MUNIM_CREDENTIALS", str(tmp_path / "none.json"))
    assert doctor._keychain().status == doctor.OK


def test_a_world_readable_store_is_flagged(monkeypatch, tmp_path):
    """0600 is the whole of the protection."""
    import json
    import os

    loose = tmp_path / "credentials.json"
    loose.write_text(json.dumps({"version": 1, "records": {}}))
    os.chmod(loose, 0o644)
    monkeypatch.setenv("MUNIM_CREDENTIALS", str(loose))

    finding = doctor._keychain()
    assert finding.status == doctor.WARN
    assert "chmod 600" in finding.fix



def test_an_unreadable_store_does_not_take_the_client_list_down(monkeypatch, tmp_path):
    """It used to be a missing keychain backend, which was every CI runner. The
    client list has to survive an unusable store: the names are in the registry
    and are worth showing even when the credentials cannot be read."""
    broken = tmp_path / "credentials.json"
    broken.write_text("{not json")
    monkeypatch.setenv("MUNIM_CREDENTIALS", str(broken))

    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="acme"))
    findings = doctor._clients(registry)          # must not raise
    assert any("acme" in f.what for f in findings)


def test_the_coding_agent_check_needs_no_executable():
    """This used to guard `shutil.which("claude")`, because on Windows the
    executable is claude.cmd and a bare name in a subprocess list does not find
    it. Reading each client's config solves that more thoroughly: there is no
    executable to resolve, on any platform, and no subprocess to start.

    It also stopped being one vendor's question. `docs/ARCHITECTURE.md` draws
    the client as "Claude Code, Codex, Cursor", and the check now reads all of
    them.
    """
    import inspect

    source = inspect.getsource(doctor._mcp_registered)
    assert "subprocess" not in source
    assert "shutil" not in source
    assert "MCP_CLIENTS" in inspect.getsource(doctor._registrations)
