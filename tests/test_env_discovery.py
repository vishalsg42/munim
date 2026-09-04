"""Where an installed package looks for its configuration.

The loader walked up from `__file__`, which is the right instinct for the MCP
server (spawned as a subprocess, it inherits no shell and its cwd is whatever
the coding agent chose) and the wrong result once the package is installed.
From site-packages it walks the venv, then wherever the venv lives, then home.

Two consequences, both verified against a real PyPI install:

  - a .env in the directory the operator ran from is never seen, which is
    exactly what the README told them to create
  - a venv nested inside an unrelated project would pick up that project's
    .env, so Munim could load somebody else's secrets

So the search order is explicit now, and `doctor` says which file it used,
because "it works in one directory and not another" is the failure this
otherwise produces.
"""

import os
from pathlib import Path

import pytest

from munim.env import CONFIG_HOME, load, sources


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in ("MUNIM_ENV", "A_TEST_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_a_dotenv_in_the_working_directory_is_found(tmp_path, monkeypatch):
    """The regression. The README says to put one here."""
    (tmp_path / ".env").write_text("A_TEST_KEY=from-the-cwd\n")
    monkeypatch.chdir(tmp_path)

    used = load()

    assert used == tmp_path / ".env"
    assert os.environ["A_TEST_KEY"] == "from-the-cwd"


def test_the_home_config_is_found_when_the_cwd_has_none(tmp_path, monkeypatch):
    """The answer for an installed package: ~/.munim/.env sits beside the
    registry, the run logs and the reports, which is where everything else
    Munim keeps already lives."""
    home = tmp_path / "home"
    (home / ".munim").mkdir(parents=True)
    (home / ".munim" / ".env").write_text("A_TEST_KEY=from-home\n")
    monkeypatch.setattr("munim.env.CONFIG_HOME", home / ".munim" / ".env")
    monkeypatch.chdir(tmp_path)

    used = load()

    assert used == home / ".munim" / ".env"
    assert os.environ["A_TEST_KEY"] == "from-home"


def test_the_working_directory_wins_over_home(tmp_path, monkeypatch):
    """Being in a project means meaning it."""
    home = tmp_path / "home"
    (home / ".munim").mkdir(parents=True)
    (home / ".munim" / ".env").write_text("A_TEST_KEY=from-home\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("A_TEST_KEY=from-the-cwd\n")
    monkeypatch.setattr("munim.env.CONFIG_HOME", home / ".munim" / ".env")
    monkeypatch.chdir(work)

    assert load() == work / ".env"
    assert os.environ["A_TEST_KEY"] == "from-the-cwd"


def test_a_real_environment_variable_is_never_overwritten(tmp_path, monkeypatch):
    """A value already exported is a deliberate act. CI sets these."""
    (tmp_path / ".env").write_text("A_TEST_KEY=from-the-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("A_TEST_KEY", "from-the-shell")

    load()

    assert os.environ["A_TEST_KEY"] == "from-the-shell"


def test_munim_env_points_at_a_file_directly(tmp_path, monkeypatch):
    """For anyone whose layout matches none of the above."""
    chosen = tmp_path / "somewhere" / "custom.env"
    chosen.parent.mkdir()
    chosen.write_text("A_TEST_KEY=from-munim-env\n")
    monkeypatch.setenv("MUNIM_ENV", str(chosen))
    monkeypatch.chdir(tmp_path)

    assert load() == chosen
    assert os.environ["A_TEST_KEY"] == "from-munim-env"


def test_sources_says_where_it_looks_and_what_exists(tmp_path, monkeypatch):
    """doctor needs to name the file it read. "It works in one directory and
    not another" is the whole failure mode here."""
    (tmp_path / ".env").write_text("A_TEST_KEY=x\n")
    monkeypatch.chdir(tmp_path)

    found = sources()

    assert any(path == tmp_path / ".env" and exists for path, exists in found)
    assert all(isinstance(exists, bool) for _, exists in found)


def test_nothing_anywhere_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.env.CONFIG_HOME", tmp_path / "nope" / ".env")
    monkeypatch.chdir(tmp_path)

    assert load() is None


def test_munim_env_is_exclusive(tmp_path, monkeypatch):
    """Naming a file that is not there reads nothing, rather than quietly
    falling through to whatever .env happens to be up the tree. A typo would
    otherwise load a different file and say nothing."""
    (tmp_path / ".env").write_text("A_TEST_KEY=from-the-cwd\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MUNIM_ENV", str(tmp_path / "not-here.env"))

    assert load() is None
    assert "A_TEST_KEY" not in os.environ
