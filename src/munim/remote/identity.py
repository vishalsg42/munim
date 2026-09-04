"""Who a session actually belongs to, asked of the provider.

The operator types a client name; the provider knows which account was
authorised. Until now nothing joined the two, so a typo at the prompt or the
wrong account at the consent screen stored a token under a name that had
nothing to do with it, and nothing noticed. "Only a person can catch that" was
true only because nobody asked.

Each provider is asked in its own words because there is no common tool for it.
A provider not listed here returns None rather than a guess: an identity that
might be wrong is worse than none, since the whole point is to be checkable.
"""

import json
import re

# Read-only, and the smallest read that names the account.
_WHO: dict[str, tuple[str, str]] = {
    "cloudflare": ("execute", """async () => {
  const r = await cloudflare.request({ method: 'GET', path: '/accounts' });
  return (r.result || []).map(a => ({ id: a.id, name: a.name }));
}"""),
}


def _first_named(text: str) -> str | None:
    """Pull a name out of whatever the provider answered with."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        # Some servers wrap the payload in prose. Take the first JSON object.
        match = re.search(r"[\[{].*[\]}]", text or "", re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None

    if isinstance(data, dict):
        data = data.get("result", data)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        return None

    first = data[0]
    if not isinstance(first, dict):
        return None
    return first.get("name") or first.get("email") or first.get("id")


async def identity_of(session, provider: str) -> str | None:
    """The account this session is authenticated as, or None if unknowable."""
    plan = _WHO.get(provider)
    if plan is None:
        return None
    tool, code = plan
    try:
        answer = await session.call_tool(tool, {"code": code})
    except Exception:
        # Never fail a connection over a label. The session is good either way.
        return None
    for chunk in getattr(answer, "content", []) or []:
        name = _first_named(getattr(chunk, "text", "") or "")
        if name:
            return name
    return None
