"""Choosing from a list, the way people expect a CLI to let them.

Every choice in this tool was a number typed at a prompt. That works and it is
not what anyone reaches for: the list is already on screen, so the arrow keys
should move through it.

One component, used by every choice, because a CLI where one list is navigable
and the next wants a typed number is worse than one where neither is.

Degrades rather than breaks. Raw mode needs a terminal on both ends and `termios`,
which is Unix only, so a pipe, a test, CI, and Windows all get the numbered
prompt this replaces. The numbered path stays a first-class route rather than an
apology: typing 2 is faster than pressing down twice, and both work in the
interactive picker too.

Writes to stderr throughout, like every other prompt here, so a chooser cannot
contaminate output something is parsing.
"""

import os
import select
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass

try:
    import termios
    import tty
    RAW_AVAILABLE = True
except ImportError:                     # Windows, and anywhere without termios
    RAW_AVAILABLE = False

UP, DOWN = "\x1b[A", "\x1b[B"
BACKSPACE = ("\x7f", "\x08")
ENTER, RETURN = "\r", "\n"
CTRL_C, ESC = "\x03", "\x1b"

# How long the rest of an escape sequence has to arrive. An arrow key sends
# all three bytes at once, so this only ever waits when the key really was
# a bare Esc.
ESCAPE_TAIL = 0.05


def interactive() -> bool:
    """Whether a live picker is possible. Both ends must be a terminal: reading
    keys from a pipe cannot work, and redrawing into one leaves escape codes in
    whatever reads it."""
    return (RAW_AVAILABLE and sys.stdin.isatty() and sys.stderr.isatty())


def _render(options: list[tuple[str, str]], cursor: int, typed: str,
            new_row: str, drawn: int) -> int:
    """Draw the list. The last row is a text field when there is one.

    Returns how many lines were used, so the next draw can move back over
    exactly those and redraw in place.
    """
    if drawn:
        sys.stderr.write(f"\x1b[{drawn}A")

    rows = [*options] + ([(new_row, "")] if new_row else [])
    for index, (label, hint) in enumerate(rows):
        here = index == cursor
        mark = "❯" if here else " "
        editing = new_row and index == len(rows) - 1

        if editing:
            # The row is the field. An operator looking at the list can see
            # where a name goes, which typing at a bare prompt never showed
            # them.
            caret = "▏" if here else ""
            body = f"{label}: {typed}{caret}" if here else label
        else:
            body = label + (f"   {hint}" if hint else "")

        sys.stderr.write(f"\x1b[2K {mark} {index + 1}  {body}\n")
    sys.stderr.flush()
    return len(rows)


def _read_key() -> str:
    """One keypress, including the three bytes an arrow key arrives as.

    Read straight from the file descriptor, never through `sys.stdin`. Python's
    text layer reads ahead, so an arrow's trailing "[B" ended up in *its*
    buffer while `select` asked the kernel, saw nothing waiting, and concluded
    the Esc was on its own. Pressing Down went back a screen.

    Esc is both a key and the first byte of every arrow, so telling them apart
    means waiting to see whether more follows. An arrow sends all three bytes
    in a single write and they are already here; a finger is slower than any
    terminal. Reading two bytes unconditionally instead made a bare Esc block
    on bytes that were never coming, which looked like the picker had frozen.

    A UTF-8 lead byte says how many continuation bytes to expect, because a
    typed name may not be ASCII and half a character is not a keypress.
    """
    fd = sys.stdin.fileno()
    data = os.read(fd, 1)
    if not data:
        return CTRL_C                   # the terminal went away

    if data == ESC.encode():
        if select.select([fd], [], [], ESCAPE_TAIL)[0]:
            data += os.read(fd, 2)      # arrows are ESC [ A/B
        return data.decode("utf-8", "replace")

    lead = data[0]
    need = (4 if lead >= 0xF0 else 3 if lead >= 0xE0 else
            2 if lead >= 0xC0 else 1)
    while len(data) < need:
        more = os.read(fd, need - len(data))
        if not more:
            break
        data += more
    return data.decode("utf-8", "replace")


def _live(prompt: str, options: list[tuple[str, str]], allow_new: bool,
          new_hint: str):
    print(prompt, file=sys.stderr)

    new_row = new_hint or "a new one, type the name" if allow_new else ""
    count = len(options) + (1 if new_row else 0)
    typed, cursor, drawn = "", 0, 0

    saved = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
            drawn = _render(options, cursor, typed, new_row, drawn)
            tty.setraw(sys.stdin.fileno())

            key = _read_key()
            on_new = bool(new_row) and cursor == count - 1

            if key in (CTRL_C, ESC):
                return None
            if key in (ENTER, RETURN):
                if on_new:
                    if typed.strip():
                        return typed.strip()
                    continue            # an empty name is not a client
                return cursor
            if key == UP:
                cursor = (cursor - 1) % count
                continue
            if key == DOWN:
                cursor = (cursor + 1) % count
                continue
            if on_new:
                # Typing belongs to the field once you are standing in it.
                if key in BACKSPACE:
                    typed = typed[:-1]
                elif key.isprintable():
                    typed += key
                continue
            if key.isdigit() and key != "0":
                wanted = int(key) - 1
                if wanted < len(options):
                    return wanted
                if new_row and wanted == count - 1:
                    cursor = wanted     # move into the field rather than pick it
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
        sys.stderr.write("\n")
        sys.stderr.flush()


def _numbered(prompt: str, options: list[tuple[str, str]], ask,
              resolve=None, allow_new: bool = False, new_hint: str = ""):
    print(prompt, file=sys.stderr)
    for index, (label, hint) in enumerate(options, 1):
        print(f"  {index}  {label}" + (f"   {hint}" if hint else ""),
              file=sys.stderr)
    if allow_new:
        print(f"  or type {new_hint or 'a new name'}", file=sys.stderr)
    print("> ", end="", file=sys.stderr, flush=True)
    try:
        answer = (ask or input)().strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return None
    if answer.isdigit():
        # A bare number is a row, or it is a mistake. Treating an out of range
        # one as the name of a new thing would turn a mistyped selection into a
        # client called "9", which nobody meant and nothing would catch.
        picked = int(answer) - 1
        return picked if 0 <= picked < len(options) else None
    # A label typed straight in, for anyone who knows what they want.
    for index, (label, _) in enumerate(options):
        if answer and answer.lower() == label.lower():
            return index
    # Anything else the caller understands: a letter shortcut, an id, a name
    # this list shows under a different label. The chooser cannot know those,
    # and refusing them would remove routes people already use.
    found = resolve(answer) if resolve and answer else None
    if found is not None:
        return found
    # Anything else typed is a new thing, which is what removes the need for a
    # "not listed" row: the operator is already typing the name.
    return answer if allow_new and answer else None


def choose(prompt: str, options: list[tuple[str, str]], ask=None,
           resolve=None, allow_new: bool = False, new_hint: str = ""):
    """Pick one. Returns its index, a typed string when it names something new,
    or None if the operator backed out.

    `ask` forces the numbered path and is how the tests drive this: a raw-mode
    picker cannot be typed at by a test, and a chooser that could only be
    exercised by hand is one nobody would change with confidence.
    """
    if not options and not allow_new:
        return None
    if ask is None and interactive():
        return _live(prompt, options, allow_new, new_hint)
    return _numbered(prompt, options, ask, resolve, allow_new, new_hint)


# ---------------------------------------------------------------------------
# The navigable menu.
#
# `choose` above answers one question and returns. This answers "where do you
# want to go", which is a different shape: rows are grouped under headers, a
# long list has to page rather than scroll off, Esc means "up one level" rather
# than "give up", and the footer has to say so because none of that is
# guessable.
#
# Kept beside `choose` rather than folded into it. Every existing caller asks
# one flat question, and giving them headers, paging and a back sentinel they
# never use would put the risk of this change into paths that did not need it.
# ---------------------------------------------------------------------------

# Backing out one level. Distinct from None on purpose: `choose` returns None
# for both Esc and Ctrl-C, so a caller could never tell "go up" from "quit",
# and a nested view needs to.
BACK = object()

# Rows the cursor cannot land on, and the lines around the list, all cost
# vertical space that the viewport has to leave room for.
CHROME = 6


@dataclass(frozen=True)
class Head:
    """A group label. Not selectable."""
    text: str


@dataclass(frozen=True)
class Item:
    label: str
    hint: str = ""
    value: object = None
    mark: str = ""          # a status glyph, already coloured


@dataclass(frozen=True)
class Blank:
    """Vertical space between groups."""


# The alternate screen buffer. Entering it means a walk can clear and redraw
# without destroying what was in the terminal before, and leaving it puts the
# scrollback back exactly as it was. The first version of this drew each screen
# below the last, so navigating four levels left four stacked screens on top of
# each other and the one you were looking at was the one furthest down.
ALT_ON, ALT_OFF = "\x1b[?1049h", "\x1b[?1049l"

# The cursor is hidden for the length of a walk. It has nowhere useful to sit
# in a menu, and leaving it visible makes it skid down the frame on every
# redraw. Claude Code hides it for the same reason.
CURSOR_OFF, CURSOR_ON = "\x1b[?25l", "\x1b[?25h"

# Whether a walk currently owns the whole screen. When it does, each frame
# homes the cursor and erases below rather than counting lines back, which is
# both simpler and immune to a frame whose height changed.
_owns_screen = False


@contextmanager
def full_screen():
    """Own the terminal for the duration of a walk, and hand it back after."""
    global _owns_screen
    if not interactive():
        yield
        return
    sys.stderr.write(ALT_ON + CURSOR_OFF)
    sys.stderr.flush()
    _owns_screen = True
    try:
        yield
    finally:
        _owns_screen = False
        sys.stderr.write(CURSOR_ON + ALT_OFF)
        sys.stderr.flush()


@contextmanager
def suspended():
    """Step out of the full screen, run something, and come back.

    An action that opens a browser, prompts, or prints progress cannot happen
    inside a frame that redraws over it. The first version of this menu dodged
    the problem by refusing to act at all and printing the command for the
    operator to run themselves, which meant every item on it did nothing.
    """
    global _owns_screen
    if not _owns_screen:
        yield
        return
    _owns_screen = False
    sys.stderr.write(CURSOR_ON + ALT_OFF)
    sys.stderr.flush()
    try:
        yield
    finally:
        sys.stderr.write(ALT_ON + CURSOR_OFF)
        sys.stderr.flush()
        _owns_screen = True


GREEN, RED, AMBER = "\x1b[32m", "\x1b[31m", "\x1b[33m"
DIM, BOLD, CYAN, RESET = "\x1b[2m", "\x1b[1m", "\x1b[36m", "\x1b[0m"


def coloured() -> bool:
    """Whether to emit colour at all.

    NO_COLOR is honoured because it is the convention, and stderr being a pipe
    matters more: this whole module writes there, and escape codes in something
    being parsed is the bug that makes people distrust a tool's output.
    """
    return not os.environ.get("NO_COLOR") and sys.stderr.isatty()


def paint(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if coloured() else text


def _selectable(rows) -> list[int]:
    return [i for i, row in enumerate(rows) if isinstance(row, Item)]


def _viewport(rows, cursor: int, height: int) -> tuple[int, int]:
    """Which slice of rows to draw, keeping the cursor inside it."""
    if len(rows) <= height:
        return 0, len(rows)
    half = height // 2
    start = max(0, min(cursor - half, len(rows) - height))
    return start, start + height


def _draw(title, subtitle, rows, cursor, footer, numbered, drawn, height,
          header=()):
    if _owns_screen:
        sys.stderr.write("\x1b[H")     # home; erase below happens after
    elif drawn:
        sys.stderr.write(f"\x1b[{drawn}A")

    lines = [paint(title, BOLD)] if title else []
    if subtitle:
        lines.append(paint(subtitle, DIM))
    lines.extend(header)
    lines.append("")

    start, end = _viewport(rows, cursor, height)
    lines.append(paint(f"  ↑ {start} more above", DIM) if start else "")

    order = _selectable(rows)
    for index in range(start, end):
        row = rows[index]
        if isinstance(row, Blank):
            lines.append("")
            continue
        if isinstance(row, Head):
            lines.append("  " + paint(row.text, BOLD))
            continue

        here = index == cursor
        pointer = paint("❯", CYAN) if here else " "
        # Numbered only when every row is reachable by one keypress. Offering
        # "7" on a list of forty is a promise the keyboard cannot keep.
        number = f"{order.index(index) + 1}. " if numbered else ""
        label = paint(row.label, CYAN) if here else row.label
        body = label + (f" · {row.mark}" if row.mark else "")
        if row.hint:
            body += "   " + paint(row.hint, DIM)
        lines.append(f" {pointer} {number}{body}")

    below = len(rows) - end
    lines.append(paint(f"  ↓ {below} more below", DIM) if below else "")
    lines.append("")
    lines.append(paint(footer, DIM))

    for line in lines:
        sys.stderr.write(f"\x1b[2K{line}\n")
    if _owns_screen:
        sys.stderr.write("\x1b[J")     # nothing from a taller previous screen
    sys.stderr.flush()
    return len(lines)


def menu(title: str, rows: list, *, subtitle: str = "", header=(),
         can_go_back: bool = True, keys=None, refresh=None, tick=0.15):
    """Navigate a grouped list. Returns the chosen Item's value, BACK, or None.

    None is Ctrl-C, which quits from any depth. BACK is Esc, which the caller
    turns into "up one level", or into a quit at the top.

    `keys` is the seam, and it is here for the reason `ask` is on `choose`: a
    raw-mode loop that can only be driven by hand is one nobody will change
    with confidence. Pass an iterable of keypresses and raw mode is skipped
    entirely, so the drawing and the navigation stay testable without a
    terminal.

    Pass an *iterator* when several menus make up one walk. iter() on a list
    restarts it, so handing the same list to each screen replays the same
    keypresses forever; iter() on an iterator returns the same object, which
    is what lets position carry across screens.

    `refresh` makes the menu able to change without a keypress. It is called
    from the idle path every `tick` seconds and returns `(rows, subtitle)` when
    something moved, or None when nothing did. Returning None costs one
    redraw's worth of nothing. Once it stops being called the menu blocks
    again, so an idle screen is free.
    """
    order = _selectable(rows)
    if not order:
        return BACK if can_go_back else None
    if keys is None and not interactive():
        return BACK

    at, drawn = 0, 0
    scripted = iter(keys) if keys is not None else None
    streaming = refresh is not None

    def shape():
        """Recomputed per frame, because rows can change while streaming."""
        order = _selectable(rows)
        numbered = len(order) <= 9
        move = "↑/↓ or 1-9" if numbered else "↑/↓ navigate"
        footer = (f"{move} · Enter select · "
                  f"Esc {'back' if can_go_back else 'quit'}")
        height = max(3, shutil.get_terminal_size().lines - CHROME
                     - (2 if subtitle else 1) - len(header))
        return order, numbered, footer, height

    order, numbered, footer, height = shape()

    saved = termios.tcgetattr(sys.stdin) if scripted is None else None
    try:
        if scripted is None:
            tty.setraw(sys.stdin.fileno(), termios.TCSANOW)
        while True:
            if scripted is None:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
            # Clamped rather than trusted. The row set is meant to be stable
            # while streaming, and a cursor that outruns it would raise under
            # the operator's hands rather than merely look wrong.
            at = min(at, len(order) - 1)
            drawn = _draw(title, subtitle, rows, order[at], footer,
                          numbered, drawn, height, header)
            if scripted is None:
                # TCSANOW, not the TCSAFLUSH tty.setraw defaults to. FLUSH
                # discards input received but not yet read, and this runs once
                # per frame. Blocking on a keypress that window is invisible;
                # with a refresh tick it opens several times a second and eats
                # keys the operator has already pressed.
                tty.setraw(sys.stdin.fileno(), termios.TCSANOW)

            if scripted is None:
                if streaming and not select.select([sys.stdin], [], [], tick)[0]:
                    # Nothing typed. Let the caller move things along, redraw
                    # if it did, and go round again.
                    moved = refresh()
                    if moved is None:
                        streaming = False       # settled: block from here on
                        continue
                    rows, subtitle = moved
                    order, numbered, footer, height = shape()
                    continue
                key = _read_key()
            else:
                # Running out of scripted keys means the caller expected the
                # menu to have returned by now. Backing out beats blocking.
                key = next(scripted, ESC)
            if key == CTRL_C:
                return None
            if key == ESC:
                return BACK
            if key in (ENTER, RETURN):
                return rows[order[at]].value
            if key == UP:
                at = (at - 1) % len(order)
            elif key == DOWN:
                at = (at + 1) % len(order)
            elif numbered and key.isdigit() and key != "0":
                wanted = int(key) - 1
                if wanted < len(order):
                    return rows[order[wanted]].value
    finally:
        if scripted is None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
        if not _owns_screen:
            sys.stderr.write("\n")
        sys.stderr.flush()
