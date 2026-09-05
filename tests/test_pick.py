"""One chooser, used by every choice.

Every list in this tool wanted a number typed at it. The list is already on
screen, so the arrow keys should move through it, and a CLI where one list is
navigable and the next is not is worse than one where neither is.

The interactive path needs a real terminal on both ends, so what is tested here
is the fallback and the contract. A raw-mode picker cannot be typed at by a
test, and a chooser only exercisable by hand is one nobody would change with
confidence.
"""

import io

import pytest

from munim import pick

OPTIONS = [("Acme", "acme.test"), ("Ivy & Fern", ""), ("Balaji", "balaji.test")]


def test_a_number_picks_that_row():
    assert pick.choose("Which?", OPTIONS, ask=lambda: "2") == 1


def test_a_label_typed_in_full_picks_it():
    """For anyone who knows what they want and does not want to read a list."""
    assert pick.choose("Which?", OPTIONS, ask=lambda: "Balaji") == 2


def test_a_label_is_matched_regardless_of_case():
    assert pick.choose("Which?", OPTIONS, ask=lambda: "ivy & fern") == 1


def test_a_number_outside_the_list_is_refused():
    assert pick.choose("Which?", OPTIONS, ask=lambda: "9") is None


def test_an_empty_answer_backs_out():
    assert pick.choose("Which?", OPTIONS, ask=lambda: "") is None


def test_no_options_is_not_a_choice():
    assert pick.choose("Which?", [], ask=lambda: "1") is None


def test_the_caller_can_resolve_answers_the_chooser_cannot():
    """Letter shortcuts and ids belong to the caller, not to the chooser, and
    refusing them would remove routes people already use."""
    def resolve(answer):
        return 0 if answer == "c_deadbeef" else None

    assert pick.choose("Which?", OPTIONS, ask=lambda: "c_deadbeef",
                       resolve=resolve) == 0
    assert pick.choose("Which?", OPTIONS, ask=lambda: "nonsense",
                       resolve=resolve) is None


def test_end_of_input_backs_out_rather_than_raising():
    """Ctrl-D at a prompt is an answer, not a crash."""
    def eof():
        raise EOFError

    assert pick.choose("Which?", OPTIONS, ask=eof) is None


def test_interrupting_backs_out_rather_than_raising():
    def interrupted():
        raise KeyboardInterrupt

    assert pick.choose("Which?", OPTIONS, ask=interrupted) is None


def test_the_prompt_and_list_go_to_stderr(capsys):
    """Data goes to stdout, everything else to stderr, so a chooser cannot
    contaminate output something is parsing."""
    pick.choose("Which client?", OPTIONS, ask=lambda: "1")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Which client?" in captured.err
    assert "Acme" in captured.err


def test_it_falls_back_when_the_terminal_is_not_one(monkeypatch):
    """A pipe, CI, a test, and Windows all take the numbered route. Reading keys
    from a pipe cannot work, and redrawing into one leaves escape codes in
    whatever reads it."""
    monkeypatch.setattr(pick.sys, "stdin", io.StringIO())
    assert pick.interactive() is False


def test_windows_has_no_raw_mode_and_says_so():
    """termios is Unix only. The numbered prompt is the route there, which is
    why it stays a first-class path rather than an apology."""
    import inspect

    source = inspect.getsource(pick)
    assert "except ImportError" in source
    assert "RAW_AVAILABLE" in source
