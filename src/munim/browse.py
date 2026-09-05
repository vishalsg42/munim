"""The navigable view: clients, their providers, those providers' tools.

Four screens, and a stack. Esc pops one level, Ctrl-C leaves from any depth,
and Esc at the top leaves too, because there is nowhere further up.

Why this exists rather than more flags: munim's surface is three levels deep
already. `munim tools "Balaji Roofings" cloudflare execute` is the same
information, and it requires knowing all three names before you can see any of
them. The list is the thing that tells you what the names are.

Live status is fetched once on entry and cached for the walk. It is the only
network call in here, `check_all` runs the probes concurrently, and re-running
it per screen would make moving around cost a round trip.
"""

import sys
import textwrap

from munim import health
from munim.pick import (AMBER, BACK, BOLD, Blank, DIM, GREEN, Head, Item,
                        RED, full_screen, menu, paint, suspended)

# What a tool's description is wrapped to. Cloudflare's `execute` carries about
# 1200 characters of TypeScript interfaces, and they are the only thing telling
# you what to put in `--args`, so the detail screen prints them whole.
WRAP = 74

GLYPH = {health.LIVE: ("✓", GREEN),
         health.EXPIRED: ("⚠", AMBER),
         health.UNREACHABLE: ("✗", RED)}


def _mark(status: health.Status) -> str:
    glyph, colour = GLYPH[status.state]
    tail = f" · {status.tools} tools" if status.live and status.tools else ""
    return paint(f"{glyph} {status.state}", colour) + paint(tail, DIM)


def _clients_screen(registry, statuses) -> list:
    """Every client, with each provider under them.

    Grouped rather than flat because the client is the thing munim is about:
    the same provider appears under several of them, and a flat list of
    `cloudflare` repeated is unreadable.
    """
    by_client = {}
    for status in statuses:
        by_client.setdefault(status.client, []).append(status)

    rows = []
    for record in sorted(registry.clients(), key=lambda r: r.name.lower()):
        held = by_client.get(record.name, [])
        rows.append(Head(record.name + (f"  {record.domain}" if record.domain else "")))
        if not held:
            rows.append(Item("nothing connected", value=("connect", record.name)))
        for status in sorted(held, key=lambda s: s.provider):
            rows.append(Item(status.provider, mark=_mark(status),
                             value=("provider", record, status)))
        rows.append(Blank())
    return rows[:-1] if rows else rows


def _provider_header(record, status) -> list[str]:
    """The status block above the action menu.

    Returned rather than printed. Printing it put it *above* the menu's own
    frame, so redrawing the menu left the block stranded and the next screen
    stacked underneath instead of replacing it.
    """
    glyph, colour = GLYPH[status.state]
    rows = [("Status", paint(f"{glyph} {status.state}", colour)),
            ("Client", record.name),
            ("Domain", record.domain or "not set")]
    if status.live and status.tools:
        rows.append(("Tools", f"{status.tools} tools"))
    if status.detail and not status.live:
        rows.append(("Why", status.detail))
    if status.fix:
        rows.append(("Fix", status.fix))
    return [""] + [f"  {label + ':':10}{value}" for label, value in rows]


def _arguments(schema: dict) -> list[str]:
    """The argument block for a tool detail screen.

    Flat scalar properties render as a table. Anything nested falls back to
    indented JSON, because these schemas come from zod and flattening a nested
    object into one `object` row reproduces the truncation this screen exists
    to fix.
    """
    import json

    properties = (schema or {}).get("properties") or {}
    if not properties:
        return ["  none"]

    required = set((schema or {}).get("required") or [])
    nested = any(
        p.get("type") in ("object", "array") or
        any(k in p for k in ("$ref", "anyOf", "allOf", "oneOf", "items",
                             "properties"))
        for p in properties.values() if isinstance(p, dict))
    if nested:
        return ["  " + line
                for line in json.dumps(schema, indent=2).splitlines()]

    width = max(len(name) for name in properties)
    out = []
    for name, spec in properties.items():
        kind = (spec or {}).get("type", "any")
        need = "required" if name in required else "optional"
        says = ((spec or {}).get("description") or "").strip().splitlines()
        out.append(f"  {name.ljust(width)}  {kind:8} {need:8} "
                   f"{says[0] if says else ''}".rstrip())
    return out


def _detail_lines(record, provider: str, tool: dict) -> list[str]:
    """One tool, whole, as lines. The screen the truncated listing could not be.

    Lines rather than prints, so the same content serves `munim tools A B C`
    and the navigable frame without one of them being a copy that drifts.
    """
    out = [f"  {'Tool:':10}{tool['tool']}"]
    access = {True: "read-only", False: "writes", None: ""}[tool["read_only"]]
    if access:
        out.append(f"  {'Access:':10}{access}")

    if tool["does"]:
        out.append("")
        for block in tool["does"].splitlines():
            # Wrapped, never cut. Blank lines and indentation are load-bearing
            # in these descriptions: they are interface listings, not prose.
            if not block.strip():
                out.append("")
                continue
            out += [f"  {line}" for line in textwrap.wrap(block, WRAP)]

    out += ["", "  Arguments:"]
    out += [f"  {line}" for line in _arguments(tool.get("arguments"))]
    out += ["", f"  munim call \"{record.name}\" {provider} {tool['tool']} "
                f"--args '{{...}}'"]
    return out


def tool_detail(record, provider: str, tool: dict) -> None:
    """The same thing printed, for `munim tools <client> <provider> <tool>`."""
    title = tool.get("title") or tool["tool"]
    print(f"\n{paint(title, BOLD)}\n{provider} · {record.name}", file=sys.stderr)
    for line in _detail_lines(record, provider, tool):
        print(line, file=sys.stderr)
    print(file=sys.stderr)


def walk(registry, *, keys=None) -> int:
    """The loop. Returns an exit status."""
    from munim.cli import CANCELLED

    records = registry.clients()
    if not records:
        print("No clients yet. Add one: munim clients add \"<name>\"",
              file=sys.stderr)
        return 0

    print("Checking sessions...", file=sys.stderr)
    statuses = health.check_all(registry)

    with full_screen():
        return _walk(registry, records, statuses, keys)


def _walk(registry, records, statuses, keys) -> int:
    from munim.cli import CANCELLED

    # One iterator for the whole walk. `menu` calls iter() on what it is
    # given, and iter() on a list restarts it, so passing the list down would
    # replay the same keypresses on every screen and never terminate. iter()
    # on an iterator returns the same object, so this shares position.
    keys = iter(keys) if keys is not None else None

    while True:
        rows = _clients_screen(registry, statuses)
        chosen = menu("Clients",
                      rows,
                      subtitle=f"{len(records)} clients · "
                               f"{sum(1 for s in statuses if s.live)} live",
                      can_go_back=False, keys=keys)
        if chosen is None or chosen is BACK:
            return CANCELLED if chosen is None else 0

        kind = chosen[0]
        if kind == "connect":
            print(f'\nNothing connected yet. Run: munim connect "{chosen[1]}" '
                  f'<provider>\n', file=sys.stderr)
            continue

        _, record, status = chosen
        if _provider_walk(record, status, keys=keys) is None:
            return CANCELLED


def _provider_walk(record, status, *, keys=None):
    """One provider: the header, an action menu, and the tools beneath it."""
    keys = iter(keys) if keys is not None else None
    note = ""
    while True:
        actions = [Item("View tools", value="tools"),
                   Item("Reconnect", hint=f'munim connect "{record.name}" '
                                          f'{status.provider}', value="connect"),
                   Item("Disconnect", value="disconnect"),
                   Item("Set domain", value="domain")]
        header = _provider_header(record, status)
        if note:
            # Shown inside the frame rather than printed underneath it, so it
            # survives the redraw. Printed, it scrolled away and choosing an
            # action looked like it had done nothing at all.
            header += ["", f"  {note}"]
        chosen = menu(f"{status.provider} · {record.name}", actions,
                      header=header, keys=keys)
        note = ""
        if chosen is None:
            return None
        if chosen is BACK:
            return 0

        if chosen == "tools":
            outcome = _tools_walk(record, status, keys=keys)
            if outcome is None:
                return None
            if isinstance(outcome, str):
                note = outcome
        elif chosen == "connect":
            status, note = _reconnect(record, status, keys=keys)
        elif chosen == "disconnect":
            done, note = _disconnect(record, status, keys=keys)
            if done:
                return 0        # there is no provider left to stand on
        elif chosen == "domain":
            record, note = _set_domain(record, keys=keys)


# ---- the actions, which used to only print the command ----------------
#
# The first version printed `munim connect ...` and returned, on the grounds
# that a browser login or a deletion behind one keypress hides a consequential
# action. The gate is worth keeping; refusing to act at all was not. So the
# destructive one asks first, in its own frame, and every one of them steps out
# of the full screen to run, because a browser prompt or a progress line cannot
# happen inside something that redraws over it.


def _confirm(question: str, yes: str, *, keys=None) -> bool:
    """A frame whose only job is to make somebody say yes on purpose."""
    picked = menu(question,
                  [Item("Cancel", value=False), Item(yes, value=True)],
                  keys=keys)
    return picked is True


def _reconnect(record, status, *, keys=None):
    from munim.cli import connect

    with suspended():
        print(file=sys.stderr)
        code = connect(record.name, status.provider)
    if code != 0:
        return status, f"{status.provider} was not reconnected."

    fresh = health.check_all_for(record, status.provider)
    return fresh, ("Reconnected." if fresh.live
                   else f"Reconnected, but the session still will not open: "
                        f"{fresh.detail}")


def _disconnect(record, status, *, keys=None):
    """True when the credential is gone, so the caller leaves this screen."""
    from munim.cli import disconnect

    if not _confirm(
            f"Remove {record.name}'s {status.provider} credential?",
            f"Yes, disconnect {status.provider}", keys=keys):
        return False, ""

    with suspended():
        print(file=sys.stderr)
        code = disconnect(record.name, status.provider, False,
                          assume_yes=True, dry_run=False)
    if code != 0:
        return False, f"Nothing was removed from {status.provider}."
    from munim import toolcache
    toolcache.forget(record.id, status.provider)
    return True, ""


def _set_domain(record, *, keys=None):
    from munim.cli import set_domain
    from munim.registry import Registry

    with suspended():
        print(f"\nSite for {record.name} (blank to keep "
              f"{record.domain or 'none'}): ", end="", file=sys.stderr,
              flush=True)
        try:
            typed = input().strip()
        except (EOFError, KeyboardInterrupt):
            typed = ""
        code = set_domain(record.name, typed) if typed else 1
    if not typed:
        return record, "Domain unchanged."
    if code != 0:
        return record, "The domain was not changed."

    from pathlib import Path
    fresh = Registry(Path.home() / ".munim" / "registry.json").get(record.id)
    return fresh, f"Domain set to {fresh.domain}."


def _tools_walk(record, status, *, keys=None):
    import asyncio

    keys = iter(keys) if keys is not None else None

    from munim.remote.passthrough import tools_for
    from munim.remote.session import NeedsLogin, NoRemoteServer

    if not status.live:
        # A dead session cannot be asked, but it was asked once. Showing what
        # it said then beats a dead end, as long as the screen says plainly
        # that this is a memory and how old it is.
        from munim import toolcache

        held = toolcache.recall(record.id, status.provider)
        if held is None:
            return (f"Cannot list tools: {status.detail}."
                    + (f"  Run: {status.fix}" if status.fix else ""))
        tools, age = held
        return _tools_menu(record, status, tools, stale=age, keys=keys)

    try:
        tools = asyncio.run(tools_for(record.id, status.provider))
    except (NeedsLogin, NoRemoteServer) as why:
        return f"Cannot list tools: {why}"

    return _tools_menu(record, status, tools, stale=None, keys=keys)


def _tools_menu(record, status, tools, *, stale, keys):
    """The tools screen, live or remembered.

    One function for both, so a remembered list cannot quietly drift into
    looking different from a live one. The only difference is the banner, and
    it is deliberately loud: a cached list can be wrong, because a provider may
    ship a new tool or vary its tools per account.
    """
    from munim import toolcache

    while True:
        rows = [Item(t["tool"],
                     hint={True: "read-only", False: "writes", None: ""}[
                         t["read_only"]],
                     value=t)
                for t in tools]
        header = []
        if stale is not None:
            header = ["",
                      f"  ⚠ Remembered from a session {toolcache.age_in_words(stale)}. "
                      f"Not read live.",
                      f"    {status.detail}."
                      + (f"  Run: {status.fix}" if status.fix else ""),
                      "    Calling one still needs a live session."]
        chosen = menu(f"Tools for {status.provider}", rows, header=header,
                      subtitle=f"{len(tools)} tools · {record.name}", keys=keys)
        if chosen is None:
            return None
        if chosen is BACK:
            return 0

        # The detail is the frame, not something printed above one. Rendered
        # as a header it survives the redraw instead of being covered by it.
        if menu(chosen.get("title") or chosen["tool"],
                [Item("Back to tools", value="back")],
                subtitle=f"{status.provider} · {record.name}",
                header=_detail_lines(record, status.provider, chosen),
                keys=keys) is None:
            return None
