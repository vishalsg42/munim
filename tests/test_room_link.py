"""A link into the control room, only when the control room is there.

`fix` handed back `watch: http://127.0.0.1:8977` on every call, and `check` and
`audit_all_clients` handed back a `report` URL the same way. The room is a
separate process that the coding agent does not start, so most of the time
those links went nowhere. A link that fails teaches people not to click the one
that works, which costs more than the missing link ever saved.

The report file is written either way and `report_file` says where, so nothing
is lost when the URLs are absent.
"""

import socket

from munim.room import link


def test_no_links_when_nothing_is_listening():
    assert link.links("run-1", up=False) == {}


def test_both_links_when_the_room_is_up():
    made = link.links("run-1", up=True)

    assert made["watch"] == link.base()
    assert made["report"].endswith("/reports/run-1")


def test_is_up_says_no_for_a_port_nobody_holds(monkeypatch):
    # Bind and release, so the port is real, routable and certainly empty.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    monkeypatch.setenv("MUNIM_ROOM_PORT", str(free))

    assert link.is_up(timeout=0.2) is False
    assert link.links("run-1") == {}


def test_is_up_says_yes_for_a_port_something_holds(monkeypatch):
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        # Room for more than one, because nothing accepts them: a backlog of
        # one makes the second probe in this test hang until it times out.
        held.listen(8)
        monkeypatch.setenv("MUNIM_ROOM_PORT", str(held.getsockname()[1]))

        assert link.is_up(timeout=0.5) is True
        assert link.links("run-1")["watch"] == link.base()


def test_the_port_follows_the_room_rather_than_a_second_default(monkeypatch):
    # munim-room reads MUNIM_ROOM_PORT. A link that ignored it would point at
    # 8977 while the room served 9100, which is worse than no link at all.
    monkeypatch.setenv("MUNIM_ROOM_PORT", "9100")
    assert link.base() == "http://127.0.0.1:9100"


def test_a_broken_port_setting_does_not_take_a_tool_call_down(monkeypatch):
    monkeypatch.setenv("MUNIM_ROOM_PORT", "not-a-number")
    assert link.port() == 8977
