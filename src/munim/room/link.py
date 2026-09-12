"""Where the control room is, and whether anybody is there.

The room is a separate process on purpose: it outlives the MCP server, which
the coding agent kills on every reconnect. So it is often not running, and a
tool that hands back `http://127.0.0.1:8977` regardless is telling you to open
a link that will not load. Do that twice and nobody trusts the link that does
work.

The reports URL has the same problem and the same cause. The report file is
written to disk either way, so `report_file` is always true and always useful.
"""

import os
import socket

HOST = "127.0.0.1"


def port() -> int:
    """The same default and the same override the room itself reads."""
    try:
        return int(os.environ.get("MUNIM_ROOM_PORT", "8977"))
    except ValueError:
        return 8977


def base() -> str:
    return f"http://{HOST}:{port()}"


def is_up(timeout: float = 0.2) -> bool:
    """Is something listening?

    A connect, not a request. This runs inside a tool call that a person is
    waiting on, so the budget is a fifth of a second against a loopback port
    that either answers immediately or is not there at all.

    It cannot tell the room from anything else that took the port. Neither can
    the person clicking the link, and the room refuses to start on a taken port
    anyway.
    """
    try:
        with socket.create_connection((HOST, port()), timeout=timeout):
            return True
    except OSError:
        return False


def links(run_id: str, *, up: bool | None = None) -> dict[str, str]:
    """`watch` and `report` for a tool result, or nothing at all.

    Absent rather than empty: a key whose value is a URL that does not load is
    worse than no key, because a caller checks for the key.
    """
    if up is None:
        up = is_up()
    if not up:
        return {}
    return {"watch": base(), "report": f"{base()}/reports/{run_id}"}
