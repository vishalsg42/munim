"""One person's answer, and the four ways it could go wrong.

The agent stops before replacing a record somebody put there on purpose. What
comes back through this channel decides whether a client's live DNS changes, so
the interesting tests here are not "does it store a boolean". They are: can an
answer be reused where it was not given, can two clicks flip a no into a yes,
does running out of time read as consent, and does waiting for a person stop
the server answering anybody else.
"""

import asyncio
import json
import stat
import time

import pytest

from munim import approval


async def test_an_answer_comes_back():
    approval.record("r1", "p1", approved=True, by="room")

    made = approval.read("r1", "p1")

    assert made is not None
    assert made.approved is True
    assert made.by == "room"


async def test_nobody_has_answered_yet():
    assert approval.read("r1", "p1") is None


async def test_a_second_click_cannot_turn_a_refusal_into_an_approval():
    """The button is on a page a person can double-click, and the CLI can race
    it. Whichever answer lands first is the one that was given."""
    approval.record("r1", "p1", approved=False, by="room")

    again = approval.record("r1", "p1", approved=True, by="room")

    assert again.approved is False
    assert approval.read("r1", "p1").approved is False


async def test_an_answer_about_one_plan_does_not_cover_another():
    """The key is both ids. Plan id alone would let an answer given in one run
    be reused by a later run against the same plan file, which is the shape of
    the cross-account write D5 exists to stop."""
    approval.record("r1", "p1", approved=True, by="room")

    assert approval.read("r1", "p2") is None
    assert approval.read("r2", "p1") is None


async def test_an_old_answer_stops_counting(monkeypatch):
    """An approval is a statement about a moment: somebody looked at two
    records and said yes to those. Half an hour later the zone may not be what
    they looked at."""
    approval.record("r1", "p1", approved=True, by="room")
    monkeypatch.setattr(approval, "GOOD_FOR", -1.0)

    assert approval.read("r1", "p1") is None


async def test_waiting_returns_as_soon_as_somebody_answers():
    async def answer_shortly():
        await asyncio.sleep(0.05)
        approval.record("r1", "p1", approved=True, by="room")

    waiting = asyncio.create_task(approval.wait_for("r1", "p1", timeout=5))
    await answer_shortly()
    made = await waiting

    assert made is not None and made.approved is True


async def test_running_out_of_time_is_not_approval():
    """The one that would be a real incident. Nobody was watching the room, so
    nobody said yes, and the answer to that is None rather than True."""
    made = await approval.wait_for("r1", "p1", timeout=0.05)

    assert made is None


async def test_waiting_for_a_person_does_not_stall_the_event_loop():
    """The regression test for a class of bug, not an instance of one.

    This project has already shipped a synchronous `flock` that stalled the
    whole server for 8.07 seconds while another process held a file. A wait for
    a human is minutes rather than seconds, so the same mistake here would take
    the server down for the length of somebody's coffee. Assert the loop keeps
    turning rather than asserting the implementation.
    """
    ticks = 0

    async def keep_counting():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    counter = asyncio.create_task(keep_counting())
    await approval.wait_for("r1", "p1", timeout=0.5)
    counter.cancel()

    assert ticks >= 20, \
        f"the loop only turned {ticks} times while waiting, so it was blocked"


async def test_the_question_carries_what_would_change():
    """A person is deciding about a diff, not about a sentence. The current
    value has to travel with the proposed one or the decision is uninformed."""
    approval.ask("r1", "p1", client="Acme Ltd", domain="acme.example",
                 changes=[{"purpose": "SPF", "name": "acme.example",
                           "action": "merge",
                           "current": ["v=spf1 include:a ~all"],
                           "content": "v=spf1 include:a include:b ~all"}])

    asked = approval.question("r1", "p1")

    assert asked["client"] == "Acme Ltd"
    assert asked["changes"][0]["current"] == ["v=spf1 include:a ~all"]
    assert "include:b" in asked["changes"][0]["content"]


async def test_the_answer_is_not_readable_by_other_users():
    """It decides whether somebody else's DNS changes. `~/.munim/plans` is
    world-readable today because `mailplan._save` only ever calls mkdir and is
    safe purely because `~/.munim` happens to be 0700. Do not inherit that."""
    approval.record("r1", "p1", approved=True, by="room")

    folder = approval.directory()
    written = folder / f"{approval.key('r1', 'p1')}.json"

    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


async def test_a_half_written_answer_is_never_read(tmp_path, monkeypatch):
    """`record` renames a complete file into place rather than writing in
    place, so a reader sees either nothing or the whole thing. That is why
    there is no lock here, and the absence of the lock is the fix rather than
    an oversight."""
    seen = []
    real = approval._write

    def watch(path, payload):
        real(path, payload)
        seen.append(path.name)

    monkeypatch.setattr(approval, "_write", watch)
    approval.record("r1", "p1", approved=True, by="room")

    # Nothing partial is left behind, and what remains parses.
    leftovers = [p.name for p in approval.directory().glob("*.tmp")]
    assert leftovers == []
    written = approval.directory() / f"{approval.key('r1', 'p1')}.json"
    assert json.loads(written.read_text())["approved"] is True


async def test_a_decision_can_be_forgotten():
    approval.record("r1", "p1", approved=True, by="room")
    approval.forget("r1", "p1")

    assert approval.read("r1", "p1") is None


@pytest.mark.parametrize("run_id,plan_id", [
    ("../../etc", "p1"),
    ("r1", "../../../tmp/evil"),
    ("r/1", "p\\1"),
])
async def test_an_id_cannot_climb_out_of_the_directory(run_id, plan_id):
    """Ids reach this from a URL path. Neither is trusted."""
    approval.record(run_id, plan_id, approved=True, by="room")

    written = list(approval.directory().glob("*.json"))
    assert written, "nothing was written at all"
    for path in written:
        assert path.parent == approval.directory(), \
            f"a decision escaped the directory: {path}"


async def test_time_moves_forward_in_a_recorded_answer():
    before = time.time()
    made = approval.record("r1", "p1", approved=True, by="cli")

    assert made.at >= before
    assert made.stale is False
