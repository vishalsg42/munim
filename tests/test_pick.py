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


# ---- typing something new, instead of a "not listed" row ------------------

def test_an_unmatched_answer_becomes_a_new_name():
    """This is what removed the "a client not listed" row. Choosing that row
    only ever led to a second prompt asking for the name, so the operator had
    to announce they were about to type a name before typing it."""
    assert pick.choose("Which?", OPTIONS, ask=lambda: "Thornbury Ltd",
                       allow_new=True) == "Thornbury Ltd"


def test_an_unmatched_answer_is_refused_when_new_things_are_not_allowed():
    """The other direction: `allow_new` has to mean something."""
    assert pick.choose("Which?", OPTIONS, ask=lambda: "Thornbury Ltd") is None


def test_an_existing_label_still_selects_rather_than_creating_a_twin():
    assert pick.choose("Which?", OPTIONS, ask=lambda: "Acme",
                       allow_new=True) == 0


def test_a_number_out_of_range_is_a_mistake_not_a_name():
    """A mistyped selection must not become something called "9"."""
    assert pick.choose("Which?", OPTIONS, ask=lambda: "9", allow_new=True) is None


def test_blank_input_backs_out_even_when_new_things_are_allowed():
    assert pick.choose("Which?", OPTIONS, ask=lambda: "   ", allow_new=True) is None


def test_a_list_with_nothing_in_it_can_still_take_a_new_name():
    """A first connection on a fresh install has no rows and still needs to be
    able to name the client."""
    assert pick.choose("Which?", [], ask=lambda: "Ivy & Fern",
                       allow_new=True) == "Ivy & Fern"


def test_the_new_row_is_where_typing_goes():
    """Typing used to filter the list from a bare `>` prompt, which nobody
    could guess was possible. The last row is a text field now: you can see
    where a name goes before you type it."""
    import inspect

    source = inspect.getsource(pick._live)
    assert "on_new" in source
    assert "typed += key" in source, "the row has to accept characters"


def test_an_empty_name_does_not_create_a_client():
    """Enter on an empty field is a slip, not a client called nothing."""
    import inspect

    source = inspect.getsource(pick._live)
    assert "typed.strip()" in source


# ---- one picker, every command ------------------------------------------

def test_a_fixed_set_can_be_picked_by_number():
    """`choose_one` is what `config ai host`, `config ai key` and `connect` use
    when they were given no argument. One thing to learn rather than one per
    command."""
    from munim import cli

    assert cli.choose_one("Which?", ["auto", "bedrock", "gemini"],
                          ask=lambda: "2") == "bedrock"


def test_a_fixed_set_can_be_picked_by_name():
    from munim import cli

    assert cli.choose_one("Which?", ["auto", "bedrock"],
                          ask=lambda: "bedrock") == "bedrock"


def test_backing_out_of_a_fixed_set_chooses_nothing():
    from munim import cli

    assert cli.choose_one("Which?", ["auto", "bedrock"], ask=lambda: "") is None


def test_a_client_can_be_picked_for_a_command_that_was_given_none(tmp_path):
    """`clients forget` and `clients domain` used to demand a name you had to
    already know, while the list sat one command away."""
    from munim import cli
    from munim.registry import ClientRecord, Registry

    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme", domain="acme.test"))
    reg.add(ClientRecord(name="Balaji Roofings"))

    assert cli._pick_client(reg, ask=lambda: "1") == "Acme"
    assert cli._pick_client(reg, ask=lambda: "2") == "Balaji Roofings"


def test_picking_a_client_when_there_are_none_says_so(tmp_path, capsys):
    from munim import cli
    from munim.registry import Registry

    assert cli._pick_client(Registry(tmp_path / "r.json")) is None
    assert "No clients registered" in capsys.readouterr().err
