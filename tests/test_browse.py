"""The navigable view, driven through the menu's keys seam.

The property this file guards hardest is that nothing changed for anything
without a terminal. `munim clients | jq`, CI, Windows and every existing test
take the flat path, and a navigable view that quietly started emitting escape
codes into a pipe would be worse than not having one.
"""

from types import SimpleNamespace

import pytest

from munim import browse, cli, health, pick
from munim.registry import ClientRecord, Registry


def status(client, provider, state=health.LIVE, tools=3, detail=""):
    return health.Status(client, provider, state, detail, tools)


@pytest.fixture
def estate(tmp_path, monkeypatch):
    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Balaji Roofings", domain="balaji.test"))
    reg.add(ClientRecord(name="Ivy & Fern"))
    monkeypatch.setattr(cli, "_registry", lambda: reg)
    return reg


def probed(monkeypatch, *statuses):
    monkeypatch.setattr(health, "check_all", lambda *a, **k: list(statuses))


# ---- the client screen ------------------------------------------------


def test_providers_are_grouped_under_their_client(estate, monkeypatch):
    probed(monkeypatch,
           status("Balaji Roofings", "cloudflare"),
           status("Balaji Roofings", "vercel"),
           status("Ivy & Fern", "cloudflare"))

    rows = browse._clients_screen(estate, health.check_all(estate))
    heads = [r.text for r in rows if isinstance(r, pick.Head)]

    assert any("Balaji Roofings" in h for h in heads)
    assert any("Ivy & Fern" in h for h in heads)
    assert any("balaji.test" in h for h in heads), "the domain belongs on the group"


def test_a_client_with_nothing_connected_still_appears(estate, monkeypatch):
    """Otherwise the one client who most needs an instruction is invisible."""
    probed(monkeypatch, status("Balaji Roofings", "cloudflare"))

    rows = browse._clients_screen(estate, health.check_all(estate))
    labels = [r.label for r in rows if isinstance(r, pick.Item)]

    assert "nothing connected" in labels


def test_an_expired_session_is_marked_differently_from_a_live_one(
        estate, monkeypatch):
    probed(monkeypatch,
           status("Balaji Roofings", "cloudflare", health.EXPIRED,
                  detail="the session expired"),
           status("Ivy & Fern", "cloudflare", health.LIVE))

    rows = browse._clients_screen(estate, health.check_all(estate))
    marks = " ".join(r.mark for r in rows if isinstance(r, pick.Item))

    assert "needs authentication" in marks
    assert "connected" in marks


def test_an_unreachable_provider_is_not_called_expired(estate, monkeypatch):
    """Reconnecting does not fix a network that is down."""
    probed(monkeypatch,
           status("Balaji Roofings", "cloudflare", health.UNREACHABLE,
                  detail="no answer in 8s"))

    rows = browse._clients_screen(estate, health.check_all(estate))
    marks = " ".join(r.mark for r in rows if isinstance(r, pick.Item))

    assert "could not be reached" in marks
    assert "needs authentication" not in marks


# ---- the tool detail, which is the whole point ------------------------


LONG = ("Execute JavaScript code against the Cloudflare API. First use the "
        "'search' tool to find the right endpoints, then write code using "
        "the cloudflare.request() function. This sentence exists to push the "
        "description well past the seventy characters the old listing cut at.")


def test_the_description_is_printed_whole(capsys):
    """The bug this screen exists for: the listing cut `execute` at 70
    characters, and the part it cut is the part telling you what to pass."""
    record = ClientRecord(name="Acme")
    browse.tool_detail(record, "cloudflare", {
        "tool": "execute", "does": LONG, "read_only": None, "arguments": {}})

    err = capsys.readouterr().err
    assert LONG.split(". ")[-1][:40] in err.replace("\n  ", " "), \
        "the tail of the description was lost"
    assert len(err) > 300


def test_blank_lines_in_a_description_survive(capsys):
    """These are interface listings, not prose. The shape carries meaning."""
    record = ClientRecord(name="Acme")
    browse.tool_detail(record, "cloudflare", {
        "tool": "execute", "does": "one\n\ntwo", "read_only": None,
        "arguments": {}})

    assert "  one\n\n  two" in capsys.readouterr().err


def test_flat_arguments_render_as_a_table():
    lines = browse._arguments({
        "type": "object",
        "properties": {"code": {"type": "string", "description": "The JS"},
                       "dry": {"type": "boolean"}},
        "required": ["code"]})
    text = "\n".join(lines)

    assert "code" in text and "string" in text and "required" in text
    assert "dry" in text and "optional" in text
    assert "The JS" in text


def test_a_nested_schema_is_not_flattened_into_one_row():
    """Vercel's tools take nested objects. A table would render the whole
    thing as `options object required` and hide everything that matters,
    which is the truncation bug one level down."""
    lines = browse._arguments({
        "type": "object",
        "properties": {"project": {"type": "object",
                                   "properties": {"name": {"type": "string"}}}},
        "required": ["project"]})
    text = "\n".join(lines)

    assert "name" in text, "the nested property vanished"
    assert "\"properties\"" in text, "expected the schema itself, pretty-printed"


def test_a_tool_with_no_arguments_says_so():
    assert browse._arguments({"type": "object"}) == ["  none"]
    assert browse._arguments(None) == ["  none"]


def test_the_access_label_is_three_valued(capsys):
    record = ClientRecord(name="Acme")
    for annotated, expected in ((True, "read-only"), (False, "writes")):
        browse.tool_detail(record, "cloudflare", {
            "tool": "t", "does": "", "read_only": annotated, "arguments": {}})
        assert expected in capsys.readouterr().err

    browse.tool_detail(record, "cloudflare", {
        "tool": "t", "does": "", "read_only": None, "arguments": {}})
    err = capsys.readouterr().err
    assert "Access:" not in err, \
        "an unannotated tool must not be labelled; the provider said nothing"


def test_the_detail_names_the_command_that_runs_it(capsys):
    browse.tool_detail(ClientRecord(name="Balaji Roofings"), "cloudflare",
                       {"tool": "execute", "does": "", "read_only": None,
                        "arguments": {}})

    assert 'munim call "Balaji Roofings" cloudflare execute' in \
        capsys.readouterr().err


# ---- navigation -------------------------------------------------------


def test_escape_at_the_top_leaves_with_success(estate, monkeypatch, capsys):
    probed(monkeypatch, status("Balaji Roofings", "cloudflare"))
    assert browse.walk(estate, keys=[pick.ESC]) == 0


def test_control_c_at_the_top_exits_cancelled(estate, monkeypatch, capsys):
    probed(monkeypatch, status("Balaji Roofings", "cloudflare"))
    assert browse.walk(estate, keys=[pick.CTRL_C]) == cli.CANCELLED


def test_no_clients_says_how_to_add_one(tmp_path, capsys):
    empty = Registry(tmp_path / "r.json")
    assert browse.walk(empty) == 0
    assert "munim clients add" in capsys.readouterr().err


def test_a_dead_session_explains_rather_than_listing_tools(
        estate, monkeypatch, capsys):
    """Opening a session to list tools would need a login nobody asked for.

    The message is *returned* rather than printed. Printed, the very next
    redraw covered it, so choosing "View tools" on a dead session looked like
    the menu had done nothing at all.
    """
    dead = status("Balaji Roofings", "cloudflare", health.EXPIRED, tools=0,
                  detail="the session expired")

    said = browse._tools_walk(ClientRecord(name="Balaji Roofings"), dead)

    assert isinstance(said, str)
    assert "the session expired" in said
    assert "munim connect" in said
    assert capsys.readouterr().err == "", \
        "nothing may be printed outside the frame that owns the screen"


def test_the_reason_is_shown_inside_the_next_frame(estate, monkeypatch, capsys):
    """Choosing an action must leave visible evidence it did something."""
    dead = status("Balaji Roofings", "cloudflare", health.EXPIRED, tools=0,
                  detail="the session expired")
    record = ClientRecord(name="Balaji Roofings")

    # "View tools", then Esc out of the provider screen.
    browse._provider_walk(record, dead, keys=[pick.ENTER, pick.ESC])

    err = capsys.readouterr().err
    assert "Cannot list tools" in err
    assert "munim connect" in err


def test_the_action_menu_prints_commands_rather_than_running_them(
        estate, monkeypatch, capsys):
    """A browser login or a deletion behind one keypress is a consequential
    action hidden in a menu."""
    live = status("Balaji Roofings", "cloudflare")
    record = ClientRecord(name="Balaji Roofings")

    # Down to "Disconnect", Enter, then Esc out.
    browse._provider_walk(record, live,
                          keys=[pick.DOWN, pick.DOWN, pick.ENTER, pick.ESC])

    err = capsys.readouterr().err
    assert 'Run: munim disconnect "Balaji Roofings" cloudflare' in err


# ---- nothing changed for anything without a terminal ------------------


def test_the_flat_listing_is_untouched_when_not_a_terminal(
        estate, monkeypatch, capsys):
    """`munim clients | cat` must be byte-identical to what it always was."""
    monkeypatch.setattr(pick, "interactive", lambda: False)
    monkeypatch.setattr("munim.container.vault",
                        type("R", (), {"get_password": lambda *a: None,
                                       "set_password": lambda *a: None,
                                       "delete_password": lambda *a: None})())

    assert cli.main(["clients"]) == 0
    out = capsys.readouterr()

    assert "Balaji Roofings" in out.err or "Balaji Roofings" in out.out
    assert "\x1b[" not in out.err + out.out, "escape codes reached a pipe"
    assert "Checking sessions" not in out.err, "a pipe must not pay for a probe"


def test_json_never_reaches_the_navigable_path(estate, monkeypatch, capsys):
    import json

    monkeypatch.setattr(pick, "interactive", lambda: True)
    called = []
    monkeypatch.setattr(health, "check_all", lambda *a, **k: called.append(1) or [])

    assert cli.main(["clients", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)
    assert called == [], "--json opened network sessions"


# ---- a dead session is no longer a dead end ---------------------------


def test_a_remembered_list_is_shown_when_the_session_is_dead(
        estate, monkeypatch, capsys):
    """Both providers refuse `initialize` without a token, so the list cannot
    be fetched again once the credential dies. It was known once."""
    from munim import toolcache

    record = ClientRecord(name="Balaji Roofings")
    toolcache.remember(record.id, "cloudflare",
                       [{"tool": "execute", "does": "Run JS",
                         "read_only": None, "arguments": {}}])
    dead = status("Balaji Roofings", "cloudflare", health.EXPIRED, tools=0,
                  detail="the session expired")

    browse._tools_walk(record, dead, keys=[pick.ESC])

    err = capsys.readouterr().err
    assert "execute" in err, "the remembered tool was not shown"
    assert "Remembered from" in err, "a cached list must say that it is cached"
    assert "still needs a live session" in err, \
        "browsing from memory must not imply you can call from memory"


def test_nothing_remembered_still_explains_rather_than_showing_nothing(
        estate, monkeypatch):
    dead = status("Balaji Roofings", "cloudflare", health.EXPIRED, tools=0,
                  detail="the session expired")

    said = browse._tools_walk(ClientRecord(name="Nobody Here"), dead)

    assert isinstance(said, str) and "Cannot list tools" in said


def test_a_live_listing_carries_no_stale_banner(estate, monkeypatch, capsys):
    """The banner is deliberately loud, so it must never appear when the list
    was read a moment ago."""
    import asyncio

    live = status("Balaji Roofings", "cloudflare", health.LIVE)
    monkeypatch.setattr(
        "munim.remote.passthrough.tools_for",
        lambda *a, **k: asyncio.sleep(0, result=[
            {"tool": "execute", "does": "", "read_only": None, "arguments": {}}]))

    browse._tools_walk(ClientRecord(name="Balaji Roofings"), live,
                       keys=[pick.ESC])

    err = capsys.readouterr().err
    assert "execute" in err
    assert "Remembered from" not in err
