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

def host_of(text):
    """The host of the first URL in a message, or None.

    Parsed and compared exactly, which is the remediation
    `py/incomplete-url-substring-sanitization` asks for and what the assertion
    meant anyway: `"example.com" in message` is also satisfied by
    `evil-example.com.attacker.test`.
    """
    import re
    from urllib.parse import urlparse

    found = re.search(r"https?://[^\s,)'\"]+", text)
    return urlparse(found.group(0)).hostname if found else None



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
    assert host_of(gmail[0].fix) == "console.cloud.google.com"


# ---- speed ---------------------------------------------------------------
# The listing cache this section used to test is gone with the subprocess it
# cached. tests/test_coding_agents.py asserts nothing shells out at all.

def test_the_report_says_how_long_it_took(healthy, tmp_path, capsys):
    """Sixteen seconds of silence looks hung rather than busy, and naming the
    slow check stops somebody optimising the wrong thing, which is how it came
    to run twice."""
    _run(tmp_path)
    out = capsys.readouterr().out
    assert "s)" in out.splitlines()[-1], out.splitlines()[-1]


def test_the_summary_counts_what_it_printed(healthy, tmp_path, monkeypatch, capsys):
    """`--verbose` showed two `!` lines and closed with "No problems found",
    because the count ran over the health checks and the inventory was displayed
    without being counted. A summary describing a different set of findings than
    the one on screen is worse than no summary."""
    monkeypatch.setattr(doctor, "_oauth_apps", lambda: [
        doctor.Finding(doctor.WARN, "Login: gmail", "needs an application", fix="...")])
    monkeypatch.setattr(doctor, "_clients", lambda r: [
        doctor.Finding(doctor.WARN, "Clients", "none registered yet", fix="...")])

    _run(tmp_path, verbose=True)
    out = capsys.readouterr().out
    assert out.count("\n! ") == 2, out
    assert "No problems found" not in out
    assert "2 things worth a look" in out


def test_the_default_report_does_not_count_what_it_did_not_look_at(healthy, tmp_path, monkeypatch, capsys):
    """Without --verbose the inventory is never evaluated, so a clean bill of
    health is about health and says where the rest is."""
    monkeypatch.setattr(doctor, "_oauth_apps", lambda: [
        doctor.Finding(doctor.WARN, "Login: gmail", "needs an application", fix="...")])

    _run(tmp_path)
    out = capsys.readouterr().out
    assert "No problems found" in out
    assert "--verbose" in out
    assert "Login: gmail" not in out
