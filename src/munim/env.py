"""Where Munim looks for its configuration.

The MCP server runs as a subprocess spawned by the coding agent, so it does not
inherit the operator's shell environment. Something has to read a file.

This used to walk up from `__file__`, which is the right instinct for that
subprocess and the wrong result once the package is installed: from
site-packages it walks the venv, then wherever the venv happens to live, then
home. Two things followed, both confirmed against a real PyPI install:

  - a `.env` in the directory the operator ran from was never found, which is
    exactly what the README told them to create, and
  - a venv nested inside an unrelated project would have picked up that
    project's `.env`, so Munim could load somebody else's secrets.

So the order is written down rather than emergent:

  1. `$MUNIM_ENV`, for a layout none of the rest fits
  2. the working directory and its parents, so being in a project means meaning it
  3. `~/.munim/.env`, which is the answer for an installed package and sits
     beside the registry, the run logs and the reports

A real environment variable always wins: `override=False` throughout, because a
value already exported is a deliberate act and CI sets these.

Never logs a value.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

# Beside registry.json, runs/ and reports/. One place for everything Munim keeps.
CONFIG_HOME = Path.home() / ".munim" / ".env"

# Read from the real environment only, never from a file. python-dotenv writes
# into os.environ permanently, and the MCP server loads once at startup, so a
# MUNIM_AI sitting in a .env would go sticky for the life of that process and
# silently beat every later `munim config ai on`. The command would report
# success while the running server stayed off, which is the two-commands-
# disagree failure this project has hit before. `doctor` reports a file that
# carries one, because somebody will try it.
NOT_FROM_A_FILE = ("MUNIM_AI",)


def candidates(start: Path | None = None) -> list[Path]:
    """Every file that would be consulted, in order, whether or not it exists."""
    # Exclusive, not merely first. Naming a file and then silently reading a
    # different one because the named one was missing is a surprise, and a
    # typo would be invisible. It also makes the setting usable as a way to
    # say "read nothing", which the test suite relies on so that a developer's
    # own configuration cannot decide what the tests assert.
    named = os.environ.get("MUNIM_ENV")
    if named:
        return [Path(named).expanduser()]

    found: list[Path] = []
    here = (start or Path.cwd()).resolve()
    found += [directory / ".env" for directory in [here, *here.parents]]
    found.append(CONFIG_HOME)
    return found


def sources(start: Path | None = None) -> list[tuple[Path, bool]]:
    """The candidates, each with whether it is there.

    `doctor` prints this. "It works in one directory and not another" is the
    failure this whole module exists to prevent, and naming the file that was
    read is what turns it from a mystery into a sentence.
    """
    return [(path, path.is_file()) for path in candidates(start)]


def load(start: Path | None = None) -> Path | None:
    """Load the first configuration file that exists. Returns the file used.

    Sets rather than overrides: a value already exported is a deliberate act and
    CI sets these. Everything in NOT_FROM_A_FILE is skipped, which is why this
    parses the file itself instead of calling load_dotenv.
    """
    for candidate in candidates(start):
        if candidate.is_file():
            for name, value in dotenv_values(candidate).items():
                if value is None or name in NOT_FROM_A_FILE:
                    continue
                os.environ.setdefault(name, value)
            return candidate
    return None


def ignored_in(start: Path | None = None) -> list[tuple[Path, str]]:
    """Settings found in a config file that a config file cannot carry.

    `doctor` prints these. Putting MUNIM_AI in .env and watching nothing happen
    is exactly the kind of silence this project keeps deciding is worse than a
    sentence.
    """
    found = []
    for candidate in candidates(start):
        if not candidate.is_file():
            continue
        try:
            values = dotenv_values(candidate)
        except OSError:
            continue
        for name in NOT_FROM_A_FILE:
            if name in values:
                found.append((candidate, name))
        break
    return found
