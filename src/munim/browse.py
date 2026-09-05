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
                        RED, menu, paint)

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


def _provider_screen(record, status) -> None:
    """The header block above the action menu. Printed, not selectable."""
    glyph, colour = GLYPH[status.state]
    print(f"\n{paint(status.provider, BOLD)} · {record.name}\n", file=sys.stderr)
    rows = [("Status", paint(f"{glyph} {status.state}", colour)),
            ("Client", record.name),
            ("Domain", record.domain or "not set")]
    if status.live and status.tools:
        rows.append(("Tools", f"{status.tools} tools"))
    if status.detail and not status.live:
        rows.append(("Why", status.detail))
    if status.fix:
        rows.append(("Fix", status.fix))
    for label, value in rows:
        print(f"  {label + ':':10}{value}", file=sys.stderr)
    print(file=sys.stderr)


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


def tool_detail(record, provider: str, tool: dict) -> None:
    """One tool, whole. The screen the truncated listing could never be."""
    title = tool.get("title") or tool["tool"]
    print(f"\n{paint(title, BOLD)}\n{provider} · {record.name}\n",
          file=sys.stderr)
    print(f"  {'Tool:':10}{tool['tool']}", file=sys.stderr)
    access = {True: "read-only", False: "writes", None: ""}[tool["read_only"]]
    if access:
        print(f"  {'Access:':10}{access}", file=sys.stderr)

    if tool["does"]:
        print(file=sys.stderr)
        for block in tool["does"].splitlines():
            # Wrapped, never cut. Blank lines and indentation are load-bearing
            # in these descriptions: they are interface listings, not prose.
            if not block.strip():
                print(file=sys.stderr)      # no indent, so no trailing spaces
                continue
            for line in textwrap.wrap(block, WRAP):
                print(f"  {line}", file=sys.stderr)

    print("\n  Arguments:", file=sys.stderr)
    for line in _arguments(tool.get("arguments")):
        print(f"  {line}", file=sys.stderr)

    print(f"\n  munim call \"{record.name}\" {provider} {tool['tool']} "
          f"--args '{{...}}'\n", file=sys.stderr)


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
    while True:
        _provider_screen(record, status)
        actions = [Item("View tools", value="tools"),
                   Item("Reconnect", hint=f'munim connect "{record.name}" '
                                          f'{status.provider}', value="connect"),
                   Item("Disconnect", value="disconnect"),
                   Item("Set domain", value="domain")]
        chosen = menu(f"{status.provider} · {record.name}", actions, keys=keys)
        if chosen is None:
            return None
        if chosen is BACK:
            return 0

        if chosen == "tools":
            if _tools_walk(record, status, keys=keys) is None:
                return None
        else:
            # The commands exist and are the documented way in. Running a
            # browser login or a deletion from inside a menu would hide a
            # consequential action behind a keypress.
            said = {"connect": f'munim connect "{record.name}" {status.provider}',
                    "disconnect": f'munim disconnect "{record.name}" '
                                  f'{status.provider}',
                    "domain": f'munim clients domain "{record.name}" <site>'}
            print(f"\n  Run: {said[chosen]}\n", file=sys.stderr)


def _tools_walk(record, status, *, keys=None):
    import asyncio

    keys = iter(keys) if keys is not None else None

    from munim.remote.passthrough import tools_for
    from munim.remote.session import NeedsLogin, NoRemoteServer

    if not status.live:
        print(f"\n  {status.detail}."
              + (f"\n  Run: {status.fix}\n" if status.fix else "\n"),
              file=sys.stderr)
        return 0

    try:
        tools = asyncio.run(tools_for(record.id, status.provider))
    except (NeedsLogin, NoRemoteServer) as why:
        print(f"\n  {why}\n", file=sys.stderr)
        return 0

    while True:
        rows = [Item(t["tool"],
                     hint={True: "read-only", False: "writes", None: ""}[
                         t["read_only"]],
                     value=t)
                for t in tools]
        chosen = menu(f"Tools for {status.provider}", rows,
                      subtitle=f"{len(tools)} tools · {record.name}", keys=keys)
        if chosen is None:
            return None
        if chosen is BACK:
            return 0

        tool_detail(record, status.provider, chosen)
        # The detail has to stay on screen. Returning straight to the list
        # would redraw over it, which is the alternate-screen problem in
        # miniature: printing something and immediately covering it is the
        # same as not printing it.
        if menu("", [Item("Back to tools", value="back")], keys=keys) is None:
            return None
