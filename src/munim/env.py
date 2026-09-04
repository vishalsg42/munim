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

from dotenv import load_dotenv

# Beside registry.json, runs/ and reports/. One place for everything Munim keeps.
CONFIG_HOME = Path.home() / ".munim" / ".env"


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
    """Load the first configuration file that exists. Returns the file used."""
    for candidate in candidates(start):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return candidate
    return None
