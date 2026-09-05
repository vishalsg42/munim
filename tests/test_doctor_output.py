"""`munim doctor` reports what is wrong with this installation, and nothing else.

It used to print thirteen lines on a healthy machine: every provider's login
route, every client, the keychain backend, the control room. All true, none of
it a problem, each with a fix beside it, closing on "1 thing(s) need fixing
before this works" when the thing worked fine. Somebody reading that cannot tell
which line is the one that matters, which is the same as printing nothing.

`audit_all_clients` has been documented from the start as silent when everything
passes and a list when it does not. This is that rule, applied to the command
people run first.
"""

import pytest

from munim import doctor
from munim.registry import ClientRecord, Registry


@pytest.fixture
def healthy(monkeypatch):
    """Every check passing, so the only question is what gets printed."""
    monkeypatch.setattr(doctor, "load_env", lambda: None)
    monkeypatch.setattr(doctor, "_config", lambda: doctor.Finding(doctor.OK, "Config", "fine"))
    monkeypatch.setattr(doctor, "_settings_file", lambda: doctor.Finding(doctor.OK, "Settings", "fine"))
    monkeypatch.setattr(doctor, "_agents", lambda: [doctor.Finding(doctor.OK, "Agents", "off")])
    monkeypatch.setattr(doctor, "_mcp_registered", lambda: doctor.Finding(doctor.OK, "Coding agent", "connected"))
    monkeypatch.setattr(doctor, "_one_interpreter", lambda: [])
    monkeypatch.setattr(doctor, "_room", lambda: doctor.Finding(doctor.OK, "Control room", "ready"))
    monkeypatch.setattr(doctor, "_keychain", lambda: doctor.Finding(doctor.OK, "Keychain", "macOS"))
    monkeypatch.setattr(doctor, "_oauth_apps", lambda: [
        doctor.Finding(doctor.OK, "Login: cloudflare", "ready")])
    monkeypatch.setattr(doctor, "_clients", lambda r: [
        doctor.Finding(doctor.OK, "Clients", "2 registered")])


def _run(tmp_path, **kw):
    return doctor.run(Registry(tmp_path / "r.json"), **kw)


def test_a_healthy_install_says_so_and_stops(healthy, tmp_path, capsys):
    assert _run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "No problems found" in out
    assert out.count("\n") <= 5, f"a healthy machine should be quiet:\n{out}"


def test_a_healthy_install_does_not_list_what_is_connected(healthy, tmp_path, capsys):
    """Inventory is not health. `munim clients` answers it, and putting it here
    is what buried the one line that mattered."""
    _run(tmp_path)
    out = capsys.readouterr().out
    assert "Login: cloudflare" not in out
    assert "Clients" not in out


def test_verbose_brings_the_inventory_back(healthy, tmp_path, capsys):
    """The other direction. Asserting only that it is hidden would pass if the
    inventory had been deleted rather than moved."""
    assert _run(tmp_path, verbose=True) == 0
    out = capsys.readouterr().out
    assert "Login: cloudflare" in out
    assert "Clients" in out


def test_the_header_says_what_this_install_is(healthy, tmp_path, capsys):
    """The first line of `claude doctor` answers "what am I running". This one
    should too, because it is the question somebody has when they type it."""
    _run(tmp_path)
    first = capsys.readouterr().out.splitlines()[0]
    assert "munim" in first
    assert "python" in first
    assert "agents" in first


def test_a_problem_is_shown_with_its_fix(healthy, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "_mcp_registered", lambda: doctor.Finding(
        doctor.BAD, "Coding agent", "not registered", fix="claude mcp add munim"))

    assert _run(tmp_path) == 1
    out = capsys.readouterr().out
    assert "not registered" in out
    assert "claude mcp add munim" in out
    assert "1 problem to fix" in out


def test_it_counts_in_words_people_write(healthy, tmp_path, monkeypatch, capsys):
    """`1 thing(s) need fixing` was the same half-done job this project already
    corrected once in the launch report."""
    monkeypatch.setattr(doctor, "_room", lambda: doctor.Finding(
        doctor.BAD, "Control room", "missing", fix="reinstall"))
    monkeypatch.setattr(doctor, "_keychain", lambda: doctor.Finding(
        doctor.BAD, "Keychain", "none", fix="install one"))

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "2 problems to fix" in out
    assert "(s)" not in out


def test_a_warning_does_not_claim_the_tool_is_broken(healthy, tmp_path, monkeypatch, capsys):
    """It used to say "before this works" for anything at all, including a
    warning, on an installation that worked."""
    monkeypatch.setattr(doctor, "_agents", lambda: [doctor.Finding(
        doctor.WARN, "Agents", "a key is set but agents are off", fix="munim config ai on")])

    assert _run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Working." in out
    assert "before this works" not in out


def test_the_gmail_advice_is_doable_from_an_installed_package():
    """It led with `uv run python scripts/setup_google_oauth.py`, which exists
    only in a source checkout: pyproject ships `src/munim` and nothing else. The
    instruction was undoable by exactly the person reading it."""
    gmail = [f for f in doctor._oauth_apps() if "gmail" in f.what]
    if not gmail:
        pytest.skip("gmail is configured here, so there is no advice to check")
    assert not gmail[0].fix.startswith("uv run"), \
        "the first thing offered must work without a source checkout"
    assert "console.cloud.google.com" in gmail[0].fix


# ---- speed ---------------------------------------------------------------

def test_the_coding_agent_listing_is_fetched_once(monkeypatch):
    """It was fetched twice, by two checks that each shelled out separately.
    `claude mcp list` takes about fifteen seconds to start, so the whole command
    took thirty-three seconds to run one subprocess twice, while every other
    check in the report totals thirty milliseconds."""
    calls = []

    class Result:
        stdout = "munim: /x/munim-mcp  - ✔ Connected\n"

    monkeypatch.setattr(doctor, "_LISTING", None)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(doctor.subprocess, "run",
                        lambda *a, **k: calls.append(a) or Result())

    doctor._mcp_registered()
    doctor._mcp_command()
    doctor._mcp_registered()

    assert len(calls) == 1, f"ran `claude mcp list` {len(calls)} times"


def test_the_report_says_how_long_it_took(healthy, tmp_path, capsys):
    """Sixteen seconds of silence looks hung rather than busy, and naming the
    slow check stops somebody optimising the wrong thing, which is how it came
    to run twice."""
    _run(tmp_path)
    out = capsys.readouterr().out
    assert "s)" in out.splitlines()[-1], out.splitlines()[-1]


def test_no_progress_line_when_the_output_is_piped(healthy, tmp_path, monkeypatch, capsys):
    """A line redrawn with a carriage return is noise in a pipe or a log, where
    the return is not honoured and the half-erased text survives."""
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")
    _run(tmp_path)
    captured = capsys.readouterr()
    assert "asking your coding agent" not in captured.err
    assert "asking your coding agent" not in captured.out


def test_the_registration_fix_makes_munim_available_everywhere(monkeypatch):
    """Registering per project means the next directory reports munim missing,
    which is exactly what somebody hits the first time they use it outside the
    repo they installed it from."""
    monkeypatch.setattr(doctor, "_LISTING", ["no munim here\n"])
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")

    finding = doctor._mcp_registered()
    assert finding.status == doctor.BAD
    assert "--scope user" in finding.fix
