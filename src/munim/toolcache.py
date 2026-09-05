"""What a provider's tools were, last time anyone could ask.

Cloudflare and Vercel both return 401 on `initialize`, before `tools/list` is
even reachable, so there is no unauthenticated window to read a tool list
through. Confirmed by probing rather than assumed:

    cloudflare  HTTP 401  WWW-Authenticate: Bearer realm="OAuth", ...
    vercel      HTTP 401  {"error":"invalid_token", ...}

That made an expired session a dead end: `View tools` had nothing to show and
`munim tools` could only say reconnect. But the list was already known. Munim
fetches it on every successful connect and every listing, and then threw it
away.

So keep it. This is public metadata about what a provider offers, not anything
about the account: names, descriptions and argument schemas. No credential and
no result of any call goes in here, which is why it is a plain file next to the
registry rather than anything in the credential store.

The obvious cost, stated rather than buried: a cached list can be wrong. A
provider that ships a new tool, or that varies its tools per account, leaves
you reading yesterday's answer. So every caller is told the age and shows it,
and nothing is ever *called* from cache: `call_provider_tool` opens a real
session, which fails honestly if the credential is dead.
"""

import json
import os
import tempfile
import time
from pathlib import Path

HOME = Path.home() / ".munim"
VERSION = 1

# Beyond this a remembered list is too old to show. Not a correctness boundary,
# since a list can go stale in a minute; it is the point past which "this is
# what it was" stops being a useful thing to say.
STALE_AFTER = 30 * 24 * 3600


def path() -> Path:
    named = os.environ.get("MUNIM_TOOL_CACHE")
    return Path(named).expanduser() if named else HOME / "tools.json"


def _key(client: str, provider: str) -> str:
    return f"{client}/{provider}"


def _load() -> dict:
    target = path()
    if not target.exists():
        return {}
    try:
        held = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A cache that cannot be read is a cache miss. Unlike the credential
        # store, there is nothing here worth refusing to overwrite.
        return {}
    return held.get("entries", {}) if held.get("version") == VERSION else {}


def remember(client: str, provider: str, tools: list[dict]) -> None:
    """Record what this provider offered. Never raises: this is a convenience."""
    try:
        entries = _load()
        entries[_key(client, provider)] = {"at": time.time(), "tools": tools}
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": VERSION, "entries": entries}, handle)
        os.replace(tmp, target)
    except OSError:
        pass


def recall(client: str, provider: str) -> tuple[list[dict], float] | None:
    """(tools, age in seconds) from the last successful listing, or None."""
    entry = _load().get(_key(client, provider))
    if not entry:
        return None
    age = time.time() - float(entry.get("at", 0))
    if age > STALE_AFTER:
        return None
    return entry.get("tools", []), age


def forget(client: str, provider: str | None = None) -> None:
    """Drop what is remembered, so `munim disconnect` leaves nothing behind."""
    try:
        entries = _load()
        for key in [k for k in entries
                    if k == _key(client, provider) or
                    (provider is None and k.startswith(f"{client}/"))]:
            entries.pop(key)
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": VERSION, "entries": entries}, handle)
        os.replace(tmp, target)
    except OSError:
        pass


def age_in_words(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{round(seconds / 60)} minutes ago"
    if seconds < 36 * 3600:
        return f"{round(seconds / 3600)} hours ago"
    return f"{round(seconds / 86400)} days ago"
