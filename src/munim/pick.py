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
ENTER, RETURN = "\r", "\n"
CTRL_C, ESC = "\x03", "\x1b"


def interactive() -> bool:
    """Whether a live picker is possible. Both ends must be a terminal: reading
    keys from a pipe cannot work, and redrawing into one leaves escape codes in
    whatever reads it."""
    return (RAW_AVAILABLE and sys.stdin.isatty() and sys.stderr.isatty())


def _render(prompt: str, options: list[tuple[str, str]], cursor: int,
            first: bool) -> None:
    if not first:
        # Back over the options to redraw in place. The prompt stays put.
        sys.stderr.write(f"\x1b[{len(options)}A")
    for index, (label, hint) in enumerate(options):
        mark = "❯" if index == cursor else " "
        number = f"{index + 1}" if index < 9 else " "
        line = f" {mark} {number}  {label}"
        if hint:
            line += f"   {hint}"
        # Clear to end of line: a shorter row must not leave the tail of a
        # longer one behind it.
        sys.stderr.write(f"\x1b[2K{line}\n")
    sys.stderr.flush()


def _read_key() -> str:
    """One keypress, including the three bytes an arrow key arrives as."""
    first = sys.stdin.read(1)
    if first != ESC:
        return first
    rest = sys.stdin.read(2)            # arrows are ESC [ A/B
    return first + rest if rest else ESC


def _live(prompt: str, options: list[tuple[str, str]]) -> int | None:
    print(prompt, file=sys.stderr)
    cursor = 0
    _render(prompt, options, cursor, first=True)

    saved = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            key = _read_key()
            if key in (ENTER, RETURN):
                return cursor
            if key in (CTRL_C, ESC, "q"):
                return None
            if key == UP or key == "k":
                cursor = (cursor - 1) % len(options)
            elif key == DOWN or key == "j":
                cursor = (cursor + 1) % len(options)
            elif key.isdigit() and key != "0":
                # Typing the number is still the fastest way when you can see
                # the one you want, so it selects rather than merely moving.
                wanted = int(key) - 1
                if wanted < len(options):
                    return wanted
                continue
            else:
                continue
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
            _render(prompt, options, cursor, first=False)
            tty.setraw(sys.stdin.fileno())
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
        sys.stderr.write("\n")
        sys.stderr.flush()


def _numbered(prompt: str, options: list[tuple[str, str]], ask,
              resolve=None) -> int | None:
    print(prompt, file=sys.stderr)
    for index, (label, hint) in enumerate(options, 1):
        print(f"  {index}  {label}" + (f"   {hint}" if hint else ""),
              file=sys.stderr)
    print("> ", end="", file=sys.stderr, flush=True)
    try:
        answer = (ask or input)().strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return int(answer) - 1
    # A label typed straight in, for anyone who knows what they want.
    for index, (label, _) in enumerate(options):
        if answer and answer.lower() == label.lower():
            return index
    # Anything else the caller understands: a letter shortcut, an id, a name
    # this list shows under a different label. The chooser cannot know those,
    # and refusing them would remove routes people already use.
    return resolve(answer) if resolve and answer else None


def choose(prompt: str, options: list[tuple[str, str]], ask=None,
           resolve=None) -> int | None:
    """Pick one. Returns its index, or None if the operator backed out.

    `ask` forces the numbered path and is how the tests drive this: a raw-mode
    picker cannot be typed at by a test, and a chooser that could only be
    exercised by hand is one nobody would change with confidence.
    """
    if not options:
        return None
    if ask is None and interactive():
        return _live(prompt, options)
    return _numbered(prompt, options, ask, resolve)
