"""The navigable menu: headers, paging, colour, and Esc meaning "up one level".

`choose` answers one question and returns. This answers "where do you want to
go", which needs a different shape. The property worth guarding hardest is that
adding it changed nothing for the callers that only ever asked one flat
question, so the last two tests here are the ones that matter most.

Driven through `menu`'s `keys` seam, for the reason `pick.py` already gives for
`ask` on `choose`: a raw-mode loop that can only be exercised by hand is one
nobody will change with confidence.
"""

import io

from munim import pick
from munim.pick import BACK, Blank, Head, Item


def rows():
    return [
        Head("Balaji Roofings"),
        Item("cloudflare", value="b/cf", mark="needs authentication"),
        Item("vercel", value="b/vc", mark="needs authentication"),
        Blank(),
        Head("Ivy & Fern"),
        Item("cloudflare", hint="3 tools", value="i/cf", mark="connected"),
    ]


def many(count):
    return [Item(f"row{i}", value=i) for i in range(count)]


def short_terminal(monkeypatch, lines=14):
    monkeypatch.setattr(pick.shutil, "get_terminal_size",
                        lambda: type("S", (), {"lines": lines, "columns": 80})())


# ---- selection and navigation -----------------------------------------


def test_enter_returns_the_value_under_the_cursor(capsys):
    assert pick.menu("Clients", rows(), keys=[pick.ENTER]) == "b/cf"


def test_the_cursor_never_lands_on_a_header_or_a_blank(capsys):
    """Down twice from the first item reaches the last item, stepping over the
    blank and the header sitting between them."""
    got = pick.menu("Clients", rows(), keys=[pick.DOWN, pick.DOWN, pick.ENTER])
    assert got == "i/cf"


def test_moving_up_from_the_top_wraps_past_the_headers(capsys):
    got = pick.menu("Clients", rows(), keys=[pick.UP, pick.ENTER])
    assert got == "i/cf", "wrapping landed on a header or a blank"


def test_a_number_selects_directly(capsys):
    assert pick.menu("Clients", rows(), keys=["3", pick.ENTER]) == "i/cf"


def test_a_number_past_the_end_is_ignored(capsys):
    """Three selectable rows, so 7 is a mistype rather than a choice."""
    assert pick.menu("Clients", rows(), keys=["7", pick.ENTER]) == "b/cf"


# ---- Esc is not Ctrl-C ------------------------------------------------


def test_escape_goes_back_and_control_c_quits(capsys):
    """`choose` returns None for both, so a nested view could never tell them
    apart. That is the whole reason BACK exists."""
    assert pick.menu("Clients", rows(), keys=[pick.ESC]) is BACK
    assert pick.menu("Clients", rows(), keys=[pick.CTRL_C]) is None
    assert BACK is not None


def test_the_footer_says_which_one_escape_does(capsys):
    pick.menu("Clients", rows(), keys=[pick.ESC], can_go_back=True)
    assert "Esc back" in capsys.readouterr().err

    pick.menu("Clients", rows(), keys=[pick.ESC], can_go_back=False)
    assert "Esc quit" in capsys.readouterr().err


def test_a_menu_with_nothing_to_pick_backs_out_rather_than_hanging():
    assert pick.menu("Clients", [Head("Empty")], keys=[pick.ENTER]) is BACK


def test_running_out_of_keys_backs_out_rather_than_blocking():
    """A test that forgot to press Enter should fail, not hang the suite."""
    assert pick.menu("Clients", rows(), keys=[]) is BACK


# ---- the footer describes what the keys actually do -------------------


def test_numbers_are_offered_only_when_they_can_reach_every_row(capsys):
    """Offering "7" on a list of forty is a promise the keyboard cannot keep."""
    pick.menu("Short", many(9), keys=[pick.ESC])
    assert "1-9" in capsys.readouterr().err

    pick.menu("Long", many(10), keys=[pick.ESC])
    err = capsys.readouterr().err
    assert "1-9" not in err
    assert "↑/↓ navigate" in err


def test_a_number_does_nothing_on_a_list_too_long_to_number(capsys):
    """The footer stops offering digits, so the loop must stop honouring them."""
    got = pick.menu("Long", many(10), keys=["2", pick.ENTER])
    assert got == 0, "a digit selected a row on an unnumbered list"


# ---- paging -----------------------------------------------------------


def test_a_long_list_pages_and_says_how_much_is_hidden(monkeypatch, capsys):
    short_terminal(monkeypatch)
    pick.menu("Long", many(40), keys=[pick.ESC])

    err = capsys.readouterr().err
    assert "more below" in err
    assert "row39" not in err, "the whole list was drawn despite a short terminal"


def test_the_viewport_follows_the_cursor_down(monkeypatch, capsys):
    short_terminal(monkeypatch)
    pick.menu("Long", many(40), keys=[*([pick.DOWN] * 25), pick.ESC])

    err = capsys.readouterr().err
    assert "row25" in err, "the cursor moved out of the drawn window"
    assert "more above" in err


def test_the_redraw_stays_the_same_height_every_frame(monkeypatch, capsys):
    """The redraw moves the cursor up by exactly the number of lines it drew
    last time. A frame of a different height corrupts everything above it."""
    short_terminal(monkeypatch)
    pick.menu("Long", many(40), keys=[*([pick.DOWN] * 20), pick.ESC])

    err = capsys.readouterr().err
    heights = {int(chunk.split("A")[0]) for chunk in err.split("\x1b[")
               if chunk[:1].isdigit() and "A" in chunk[:4]}
    assert len(heights) == 1, f"frames had differing heights: {heights}"


# ---- colour -----------------------------------------------------------


def test_no_colour_when_stderr_is_not_a_terminal(monkeypatch):
    """Escape codes in something being parsed is what makes people stop
    trusting a tool's output."""
    monkeypatch.setattr(pick.sys, "stderr", io.StringIO())
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert pick.coloured() is False
    assert pick.paint("hello", pick.GREEN) == "hello"


def test_no_colour_env_is_honoured(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self): return True

    monkeypatch.setattr(pick.sys, "stderr", Tty())
    monkeypatch.setenv("NO_COLOR", "1")
    assert pick.coloured() is False

    monkeypatch.delenv("NO_COLOR")
    assert pick.coloured() is True
    assert pick.paint("hello", pick.GREEN).startswith(pick.GREEN)


# ---- nothing above this changed ---------------------------------------


def test_choose_still_returns_none_for_both_escape_and_control_c(monkeypatch):
    """`menu` grew a back sentinel. `choose` must not have: every existing
    caller treats None as "backed out" and would now get an object instead."""
    import termios as real

    class Fake:
        TCSADRAIN = real.TCSADRAIN
        def tcgetattr(self, *a): return None
        def tcsetattr(self, *a): pass

    class Stdin:
        # pytest replaces stdin with a pseudofile that has no fileno(), and
        # `_live` needs one to put the terminal into raw mode.
        def fileno(self): return 0

    monkeypatch.setattr(pick, "interactive", lambda: True)
    monkeypatch.setattr(pick, "termios", Fake())
    monkeypatch.setattr(pick, "tty",
                        type("T", (), {"setraw": staticmethod(lambda *a: None)})())
    monkeypatch.setattr(pick.sys, "stdin", Stdin())

    for key in (pick.ESC, pick.CTRL_C):
        monkeypatch.setattr(pick, "_read_key", lambda k=key: k)
        assert pick.choose("Pick", [("a", ""), ("b", "")]) is None


def test_the_numbered_fallback_is_untouched(capsys):
    """Pipes, CI and Windows take this path, and its output is what scripts
    and every existing test read."""
    assert pick.choose("Pick one", [("alpha", ""), ("beta", "")],
                       ask=lambda: "2") == 1

    err = capsys.readouterr().err
    assert "  1  alpha" in err
    assert "\x1b[" not in err, "the numbered path must never emit escape codes"


# ---- a bare Esc must not wait for an arrow that is not coming ---------


def keypress(monkeypatch, chunks, pending=True):
    """Feed _read_key raw bytes, the way the file descriptor does."""
    queue = list(chunks)
    monkeypatch.setattr(pick.sys, "stdin",
                        type("S", (), {"fileno": staticmethod(lambda: 0)})())
    monkeypatch.setattr(pick.os, "read", lambda fd, n: queue.pop(0))
    monkeypatch.setattr(pick.select, "select",
                        lambda *a, **k: (([0], [], []) if pending
                                         else ([], [], [])))
    return queue


def test_a_bare_escape_does_not_block_waiting_for_an_arrow_tail(monkeypatch):
    """Esc is both a key and the first byte of every arrow.

    Reading two more bytes unconditionally blocked until the operator pressed
    something else: nothing happened, then two keys later something did, which
    is indistinguishable from a frozen picker.
    """
    left = keypress(monkeypatch, [b"\x1b", b"[B"], pending=False)

    assert pick._read_key() == pick.ESC
    assert left == [b"[B"], "it read past the Esc when nothing was waiting"


def test_an_arrow_is_still_read_whole(monkeypatch):
    """All three bytes arrive in one write, so the wait never costs anything."""
    keypress(monkeypatch, [b"\x1b", b"[A"], pending=True)
    assert pick._read_key() == pick.UP


def test_keys_are_read_from_the_descriptor_not_through_sys_stdin(monkeypatch):
    """The bug that made Down go back a screen.

    Python's text layer reads ahead, so an arrow's trailing "[B" landed in
    *its* buffer while select asked the kernel, saw nothing waiting, and
    concluded the Esc stood alone. Reading the descriptor directly is the fix,
    so a stdin whose .read would answer must never be consulted.
    """
    class Trap:
        def fileno(self): return 0
        def read(self, n):
            raise AssertionError("_read_key went through the buffered layer")

    monkeypatch.setattr(pick.sys, "stdin", Trap())
    monkeypatch.setattr(pick.os, "read", lambda fd, n: b"q")
    assert pick._read_key() == "q"


def test_a_multibyte_character_is_read_whole(monkeypatch):
    """A typed client name need not be ASCII, and half a character is not a key."""
    keypress(monkeypatch, ["é".encode()[:1], "é".encode()[1:]])
    assert pick._read_key() == "é"


def test_a_closed_terminal_reads_as_a_cancel(monkeypatch):
    """Otherwise the loop spins on an endless stream of empty reads."""
    keypress(monkeypatch, [b""])
    assert pick._read_key() == pick.CTRL_C


def test_owning_the_screen_homes_instead_of_counting_lines_back(monkeypatch,
                                                                capsys):
    """Counting lines back only works while nothing else writes between
    frames. Four stacked screens is what happens when it does not."""
    monkeypatch.setattr(pick, "_owns_screen", True)
    try:
        pick.menu("Title", many(3), keys=[pick.ESC])
    finally:
        monkeypatch.setattr(pick, "_owns_screen", False)

    err = capsys.readouterr().err
    assert "\x1b[H" in err, "the frame did not home the cursor"
    assert "\x1b[J" in err, "nothing erased a taller previous frame"


def test_full_screen_is_skipped_when_there_is_no_terminal(capsys):
    """Entering the alternate buffer in a pipe would put escape codes into
    whatever is reading, and never leaving it would strand a real terminal."""
    with pick.full_screen():
        pass
    assert capsys.readouterr().err == ""
