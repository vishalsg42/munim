"""The one thing the control room can do, and the ways it must refuse.

D18 said the room "has exactly one interactive element in the whole
application, the confirmation button, and it appears only when the agent has
stopped and needs a person". The button was written and rendered and wired to
nothing, which is the second capability in this repository shipping "present
and inert" against the rule in ARCHITECTURE.md. This is it reaching something.

The tests worth reading are the refusals. A POST that writes an approval for
somebody else's DNS is not a feature you get to be relaxed about, and binding
to loopback answers a narrower question than it appears to.
"""

import json

import pytest
from starlette.testclient import TestClient

from munim import approval
from munim.room.server import build_app


@pytest.fixture
def room(tmp_path):
    app = build_app(runs_dir=tmp_path / "runs", reports_dir=tmp_path / "reports")
    return TestClient(app)


def _post(client, body, **headers):
    return client.post("/api/decisions/run-1/plan-1", json=body,
                       headers={"sec-fetch-site": "same-origin", **headers})


def test_a_click_records_an_answer(room):
    reply = _post(room, {"decision": "approve"})

    assert reply.status_code == 200
    assert reply.json()["approved"] is True
    made = approval.read("run-1", "plan-1")
    assert made is not None and made.approved is True and made.by == "room"


def test_not_now_records_a_refusal(room):
    reply = _post(room, {"decision": "reject"})

    assert reply.status_code == 200
    assert reply.json()["approved"] is False
    assert approval.read("run-1", "plan-1").approved is False


def test_a_second_click_does_not_change_the_answer(room):
    _post(room, {"decision": "reject"})

    again = _post(room, {"decision": "approve"})

    assert again.json()["approved"] is False, \
        "double-clicking turned a refusal into an approval"


def test_a_word_that_is_not_a_decision_is_refused(room):
    for body in ({"decision": "maybe"}, {"decision": True}, {}, {"approved": 1}):
        reply = _post(room, body)
        assert reply.status_code == 400, f"{body} was accepted"
    assert approval.read("run-1", "plan-1") is None


def test_a_body_that_is_not_json_is_refused(room):
    reply = room.post("/api/decisions/run-1/plan-1", content="approve",
                      headers={"sec-fetch-site": "same-origin",
                               "content-type": "text/plain"})

    assert reply.status_code == 400
    assert approval.read("run-1", "plan-1") is None


# ---- the refusals that are actually about security ----------------------


def test_another_page_cannot_approve_somebody_elses_dns(room):
    """Loopback stops another machine, not another tab.

    Any site the operator's browser visits while the room is open can POST to
    127.0.0.1. Without this check, reading the wrong blog post while an agent
    waits for approval is enough to change a client's live DNS.
    """
    reply = room.post("/api/decisions/run-1/plan-1", json={"decision": "approve"},
                      headers={"sec-fetch-site": "cross-site",
                               "origin": "https://evil.test"})

    assert reply.status_code == 403
    assert approval.read("run-1", "plan-1") is None


def test_a_request_claiming_no_origin_at_all_is_refused(room):
    """A form post from another origin arrives with `Sec-Fetch-Site:
    cross-site`; an old client may send neither header. Refuse rather than
    assume, because the room's own page always sends one."""
    reply = room.post("/api/decisions/run-1/plan-1", json={"decision": "approve"})

    assert reply.status_code == 403
    assert approval.read("run-1", "plan-1") is None


def test_an_origin_header_from_elsewhere_is_refused(room):
    reply = room.post("/api/decisions/run-1/plan-1", json={"decision": "approve"},
                      headers={"origin": "https://evil.test"})

    assert reply.status_code == 403


# ---- routing, which is where this would silently not exist --------------


def test_the_decision_route_is_not_swallowed_by_the_page_handler(room):
    """`Route("/{path:path}", index)` catches everything that reaches it, so a
    route appended after it never runs. Registering this one late would answer
    a POST with the HTML page and a 200, which reads as success."""
    reply = _post(room, {"decision": "approve"})

    assert reply.headers["content-type"].startswith("application/json")
    assert reply.json()["by"] == "room"


def test_the_room_still_binds_loopback_only():
    """The origin check above is the second lock. This is the first, and it is
    one line in `main()` that a future 'let me demo from my phone' would
    quietly change."""
    import inspect

    from munim.room import server

    source = inspect.getsource(server.main)
    assert '"127.0.0.1"' in source or "'127.0.0.1'" in source, \
        "the room must bind loopback only"
    assert "0.0.0.0" not in source


def test_reading_a_run_still_works(room, tmp_path):
    """The room is still a window. Adding one button must not have changed
    what it was already for."""
    reply = room.get("/api/runs")

    assert reply.status_code == 200
    assert "runs" in json.loads(reply.text)


# ---- which runs have a report -------------------------------------------
#
# The reports were written to disk and served at /reports/<id> from the first
# week, and no page ever linked to one, because nothing told the page which
# existed. Offering a link that 404s is worse than offering none, so the list
# comes back with the runs.

def test_the_run_list_names_the_runs_that_have_a_report(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run-1.jsonl").write_text("")
    (runs / "run-2.jsonl").write_text("")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "run-2.html").write_text("<p>hello</p>")

    body = TestClient(build_app(runs_dir=runs, reports_dir=reports)).get("/api/runs").json()

    assert body["runs"] == ["run-1", "run-2"]
    assert body["reports"] == ["run-2"]


def test_no_reports_directory_is_an_empty_list_not_a_crash(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run-1.jsonl").write_text("")

    body = TestClient(
        build_app(runs_dir=runs, reports_dir=tmp_path / "nothing-here")
    ).get("/api/runs").json()

    assert body["reports"] == []
