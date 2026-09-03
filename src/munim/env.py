"""Load configuration from .env.

The MCP server runs as a subprocess spawned by the coding agent, so it does not
inherit the operator's shell environment. Reading .env from the project root is
what makes a key set once work in both places.

Never logs a value.
"""

from pathlib import Path

from dotenv import load_dotenv


def load(start: Path | None = None) -> Path | None:
    """Load the nearest .env walking up from `start`. Returns the file used."""
    here = (start or Path(__file__)).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return candidate
    return None
