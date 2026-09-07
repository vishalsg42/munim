"""Answering from a terminal, which is what keeps D18's test true.

D18's test is "if the room were removed, nothing about how the product is used
would change". A repair that could only be approved in a browser would break
that, and would also strand every run nobody happened to be watching, which is
most of them.

So the decision has two writers and they agree. The room's button is the one on
camera; this is the one that works at 2am over ssh.
"""

import sys

import pytest

from munim import approval
from munim.cli import approve


def _asked(run="r1", plan="p1", client="Acme Ltd"):
    approval.ask(run, plan, client=client, domain="acme.example", changes=[
        {"purpose": "SPF", "type": "TXT", "name": "acme.example",
         "action": "merge", "current": ["v=spf1 include:a ~all"],
         "content": "v=spf1 include:a include:b ~all",
         "note": "combines 2 policies, keeping 4 senders"}])


@pytest.fixture
def not_a_terminal(monkeypatch):
    """Non-interactive by default, so a test cannot block on input()."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)


def test_nothing_waiting_says_so_and_is_not_an_error(capsys, not_a_terminal):
    """Exit 0. Running this when nothing is pending is a reasonable thing for
    a person to do and should not look like a fault."""
    assert approve("r1") == 0
    assert "Nothing is waiting for you" in capsys.readouterr().err


def test_approving_records_it(not_a_terminal):
    _asked()

    assert approve("r1", assume_yes=True) == 0

    made = approval.read("r1", "p1")
    assert made is not None and made.approved is True and made.by == "cli"


def test_refusing_records_it(not_a_terminal):
    _asked()

    approve("r1", refuse=True)

    assert approval.read("r1", "p1").approved is False


def test_the_diff_is_printed_before_anything_is_recorded(capsys, not_a_terminal):
    """The one that matters. An approval given without seeing what it replaces
    is a signature on a blank page, and this is somebody else's live DNS."""
    _asked()

    approve("r1", assume_yes=True)

    said = capsys.readouterr().err
    assert "v=spf1 include:a ~all" in said, "the current value was not shown"
    assert "include:b" in said, "the proposed value was not shown"
    assert "combines 2 policies" in said


def test_it_says_whose_account_this_is(capsys, not_a_terminal):
    """Verbatim from the control room's card. It is the best sentence in the
    codebase and the person approving over ssh deserves it too."""
    _asked()

    approve("r1", assume_yes=True)

    assert "It is their account, not yours." in capsys.readouterr().err


def test_a_non_interactive_shell_without_yes_records_nothing(capsys,
                                                             not_a_terminal):
    """Silence is not consent, and it is not refusal either.

    The first version of this approved, which is how a script piping into this
    would have changed a client's DNS by not answering. A refusal would also be
    wrong: that is a decision, and nobody is here to make one. So nothing is
    recorded, the run times out on its own, and that is recoverable.
    """
    _asked()

    approve("r1")

    assert approval.read("r1", "p1") is None
    said = capsys.readouterr().err
    assert "nobody at this terminal" in said
    assert "--yes" in said and "--no" in said


def test_saying_no_at_the_prompt_refuses(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    _asked()

    approve("r1")

    assert approval.read("r1", "p1").approved is False


def test_saying_yes_at_the_prompt_approves(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    _asked()

    approve("r1")

    assert approval.read("r1", "p1").approved is True


def test_an_answer_already_given_is_not_overwritten(not_a_terminal):
    _asked()
    approval.record("r1", "p1", approved=False, by="room")

    approve("r1", assume_yes=True)

    assert approval.read("r1", "p1").approved is False, \
        "the cli overrode an answer the room had already given"


def test_a_run_with_no_pending_question_is_not_offered(capsys, not_a_terminal):
    _asked()
    approval.record("r1", "p1", approved=True, by="room")

    assert approve("r1") == 0
    assert "Nothing is waiting" in capsys.readouterr().err


def test_more_than_one_pending_change_is_answered(not_a_terminal):
    _asked(plan="p1")
    _asked(plan="p2")

    approve("r1", assume_yes=True)

    assert approval.read("r1", "p1").approved is True
    assert approval.read("r1", "p2").approved is True


def test_the_newest_waiting_run_is_found_without_naming_one(monkeypatch,
                                                            not_a_terminal):
    """An operator who has just watched a run stop does not want to go and find
    its id first. That is the kind of step that makes a person open the
    dashboard instead."""
    monkeypatch.setattr("munim.runlog.all_runs", lambda *a, **k: ["old", "new"])
    _asked(run="new", plan="p9")

    approve("", assume_yes=True)

    made = approval.read("new", "p9")
    assert made is not None and made.approved is True


def test_an_older_run_that_was_already_answered_is_skipped(monkeypatch,
                                                           not_a_terminal):
    """Newest *waiting*, not merely newest. A run that has been answered is
    not the one the operator means."""
    monkeypatch.setattr("munim.runlog.all_runs", lambda *a, **k: ["old", "new"])
    _asked(run="old", plan="p1")
    _asked(run="new", plan="p9")
    approval.record("new", "p9", approved=True, by="room")

    approve("", assume_yes=True)

    assert approval.read("old", "p1") is not None, \
        "it stopped at the newest run instead of the newest waiting one"
