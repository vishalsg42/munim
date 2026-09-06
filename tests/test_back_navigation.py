"""Esc goes up a level wherever one question is really a step of several.

`choose` returned None for both Esc and Ctrl-C, so a chained flow could not
tell "wrong provider, let me pick again" from "abandon the command", and always
did the second. `menu` fixed this for the navigable view weeks of commits ago;
this is the same rule everywhere else a list appears.

The rule: a question with something above it returns BACK on Esc and says
"Esc back" in its footer. A question standing on its own keeps returning None
and says "Esc cancel", because there is nowhere to go.
"""

import pytest

from munim import pick
from munim.pick import BACK


def rows(count):
    return [(f"row{i}", "") for i in range(count)]


def driven(monkeypatch, *presses):
    """Drive the one-question picker without a terminal."""
    import termios as real

    queue = list(presses)

    class Fake:
        TCSADRAIN = real.TCSADRAIN
        TCSANOW = real.TCSANOW
        def tcgetattr(self, *a): return None
        def tcsetattr(self, *a): pass

    monkeypatch.setattr(pick, "interactive", lambda: True)
    monkeypatch.setattr(pick, "termios", Fake())
    monkeypatch.setattr(pick, "tty",
                        type("T", (), {"setraw": staticmethod(lambda *a, **k: None)})())
    monkeypatch.setattr(pick.sys, "stdin",
                        type("S", (), {"fileno": staticmethod(lambda: 0)})())
    monkeypatch.setattr(pick, "_read_key", lambda: queue.pop(0))
    monkeypatch.setattr(pick, "_read_within", lambda s: queue.pop(0) if queue else None)


# ---- the picker itself ------------------------------------------------


def test_escape_returns_back_when_there_is_a_level_above(monkeypatch):
    driven(monkeypatch, pick.ESC)
    assert pick.choose("Pick", rows(3), can_go_back=True) is BACK


def test_escape_still_cancels_when_there_is_not(monkeypatch):
    """Every existing caller reads None as backed out, and a question with
    nothing above it must keep meaning that."""
    driven(monkeypatch, pick.ESC)
    assert pick.choose("Pick", rows(3)) is None


def test_control_c_always_quits_outright(monkeypatch):
    """From any depth. Esc is up one level; Ctrl-C is out."""
    driven(monkeypatch, pick.CTRL_C)
    assert pick.choose("Pick", rows(3), can_go_back=True) is None


def test_the_footer_says_which_one_escape_does(monkeypatch, capsys):
    monkeypatch.setattr(pick, "_owns_screen", True)
    try:
        pick._render(rows(3), 0, "", "", 0, "Pick", "", "back")
        assert "Esc back" in capsys.readouterr().err
        pick._render(rows(3), 0, "", "", 0, "Pick", "", "cancel")
        assert "Esc cancel" in capsys.readouterr().err
    finally:
        monkeypatch.setattr(pick, "_owns_screen", False)


# ---- the helpers the CLI chains are built from ------------------------


def test_choose_one_passes_back_through(monkeypatch):
    from munim.cli import choose_one

    driven(monkeypatch, pick.ESC)
    assert choose_one("Pick", ["a", "b"], can_go_back=True) is BACK


def test_pick_client_passes_back_through(monkeypatch, tmp_path):
    from munim.cli import _pick_client
    from munim.registry import ClientRecord, Registry

    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme"))
    driven(monkeypatch, pick.ESC)

    assert _pick_client(reg, "Which?", can_go_back=True) is BACK


def test_ask_which_client_passes_back_through(monkeypatch, tmp_path):
    from munim.cli import ask_which_client
    from munim.registry import ClientRecord, Registry

    reg = Registry(tmp_path / "r.json")
    reg.add(ClientRecord(name="Acme"))
    driven(monkeypatch, pick.ESC)

    assert ask_which_client(reg, can_go_back=True) is BACK


def test_back_is_not_none_and_not_an_index(monkeypatch):
    """A caller that forgets to check it must fail loudly, not treat it as
    row zero or as a cancel."""
    assert BACK is not None
    assert not isinstance(BACK, int)
