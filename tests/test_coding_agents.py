"""munim is an MCP server, and MCP is not one vendor's protocol.

`docs/ARCHITECTURE.md` has always drawn the client as "Claude Code, Codex,
Cursor". `doctor` nonetheless shelled out to `claude` alone and reported
`1 problem to fix` when munim was not registered there. For an operator driving
munim from Codex that verdict is meaningless, and it cost eighteen of the
command's eighteen and a half seconds to be wrong.

Reading each client's own config is both correct and instant.
"""

import json

import pytest

from munim import doctor


@pytest.fixture
def clients(tmp_path, monkeypatch):
    """A machine with whichever clients a test decides to write."""
    def install(name, filename, contents):
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        return (name, str(path))

    def use(*entries):
        monkeypatch.setattr(doctor, "MCP_CLIENTS", tuple(entries))
    return install, use


def test_a_json_client_is_read(clients):
    install, use = clients
    use(install("Cursor", "mcp.json",
                json.dumps({"mcpServers": {"munim": {"command": "/x/munim-mcp"}}})))

    assert doctor._mcp_registered().status == doctor.OK
    assert "Cursor" in doctor._mcp_registered().detail


def test_a_toml_client_is_read(clients):
    """Codex keeps a table per server rather than an object."""
    install, use = clients
    use(install("Codex", "config.toml",
                '[mcp_servers.munim]\ncommand = "/x/munim-mcp"\n'
                '[mcp_servers.other]\ncommand = "/y/other"\n'))

    assert doctor._mcp_registered().status == doctor.OK
    assert doctor._mcp_command() == "/x/munim-mcp"


def test_a_server_registered_per_project_is_found(clients):
    """Claude Code nests a server map under each project, which is how munim
    can be registered in one directory and missing in the next."""
    install, use = clients
    use(install("Claude Code", "claude.json", json.dumps({
        "projects": {"/some/repo": {"mcpServers": {"munim": {"command": "/x/munim-mcp"}}}}})))

    assert doctor._mcp_registered().status == doctor.OK
    assert doctor._mcp_command() == "/x/munim-mcp"


def test_not_being_registered_is_a_note_rather_than_a_verdict(clients):
    """munim cannot see every MCP client that exists, so "not in the ones I know
    about" is not the same as broken. It used to report BAD."""
    install, use = clients
    use(install("Codex", "config.toml", '[mcp_servers.other]\ncommand = "/y"\n'),
        install("Cursor", "mcp.json", json.dumps({"mcpServers": {}})))

    finding = doctor._mcp_registered()
    assert finding.status == doctor.WARN, "an unregistered server is not a fault"
    assert "Codex" in finding.detail and "Cursor" in finding.detail
    assert "munim-mcp" in finding.fix


def test_every_client_is_searched_not_just_the_first(clients):
    """The bug this replaces: one client checked, the rest ignored."""
    install, use = clients
    use(install("Claude Code", "claude.json", json.dumps({"mcpServers": {}})),
        install("Antigravity", "ag.json",
                json.dumps({"mcpServers": {"munim": {"command": "/x/munim-mcp"}}})))

    assert doctor._mcp_registered().status == doctor.OK
    assert "Antigravity" in doctor._mcp_registered().detail


def test_no_client_at_all_is_not_a_problem(clients, tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "MCP_CLIENTS",
                        (("Cursor", str(tmp_path / "absent.json")),))
    assert doctor._mcp_registered().status == doctor.OK


def test_an_unreadable_config_is_skipped_rather_than_fatal(clients):
    """One agent's broken config must not take the whole report down."""
    install, use = clients
    use(install("Cursor", "mcp.json", "{not json,"),
        install("Codex", "config.toml",
                '[mcp_servers.munim]\ncommand = "/x/munim-mcp"\n'))

    assert doctor._mcp_registered().status == doctor.OK


def test_it_does_not_shell_out(clients, monkeypatch):
    """Eighteen of the command's eighteen and a half seconds were one
    subprocess. Nothing here may start a process."""
    install, use = clients
    use(install("Cursor", "mcp.json",
                json.dumps({"mcpServers": {"munim": {"command": "/x"}}})))

    import subprocess

    def refuse(*a, **k):
        raise AssertionError("doctor started a subprocess")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    doctor._mcp_registered()
    doctor._mcp_command()
