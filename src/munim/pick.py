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

import sys

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
    """One keypress, including the three bytes an arrow key arrives as."""
    first = sys.stdin.read(1)
    if first != ESC:
        return first
    rest = sys.stdin.read(2)            # arrows are ESC [ A/B
    return first + rest if rest else ESC


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
