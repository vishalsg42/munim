"""`settings.json` decides whether agents may reach a model host.

It was written with a fixed temporary name and `write_text`: no `mkstemp`, no
`fsync`, and a failed write left the temporary file behind. The docstring
claimed it was "written the way registry.py writes", and it was not.

Three consequences, all of which this file pins:

  - Two processes writing at once shared one temporary name, so the second
    clobbered the first's half-written file before renaming it into place.
  - Without `fsync` the rename can be durable while the bytes are not, so a
    crash leaves an intact file pointing at partial content.
  - Reading an unparseable file yields "nothing stored", and the setters then
    saved from an empty dict, silently discarding the host and model ids still
    in the file. A typo somebody could have fixed by hand became data they had
    to remember.
"""

import json

import pytest

from munim import settings


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MUNIM_SETTINGS", str(tmp_path / "settings.json"))
    return tmp_path / "settings.json"


# ---- durability ----------------------------------------------------------

def test_a_write_leaves_no_temporary_file(home):
    settings.set_enabled(True)
    strays = [p.name for p in home.parent.iterdir() if p.name != home.name]
    assert strays == [], f"left behind: {strays}"


def test_a_failed_write_leaves_no_temporary_file(home, monkeypatch):
    settings.set_enabled(True)
    before = home.read_text()

    def explode(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(settings.os, "replace", explode)
    with pytest.raises(OSError):
        settings.set_host("gemini")

    assert home.read_text() == before, "the previous settings did not survive"
    strays = [p.name for p in home.parent.iterdir() if p.name != home.name]
    assert strays == [], f"a failed write left: {strays}"


def test_the_bytes_are_flushed_before_the_rename(home, monkeypatch):
    """`os.replace` can be durable while what it points at is not, which leaves
    an intact rename onto partial content."""
    synced = []
    monkeypatch.setattr(settings.os, "fsync", lambda fd: synced.append(fd))
    settings.set_enabled(True)
    assert synced, "nothing was fsynced before the rename"


def test_each_writer_gets_its_own_temporary_name():
    """A fixed `.tmp` name means two processes writing at once use the same
    file, and the second clobbers the first before renaming it into place."""
    import ast
    import inspect

    # The body, not the docstring: the docstring explains the old bug by
    # quoting it, and a naive substring search finds its own explanation.
    tree = ast.parse(inspect.getsource(settings.write))
    body = ast.unparse(ast.get_docstring(tree.body[0], clean=False) and
                       ast.Module(body=tree.body[0].body[1:], type_ignores=[])
                       or tree.body[0])

    assert "mkstemp" in body
    assert "with_suffix" not in body, "a fixed temporary name is shared between writers"


# ---- an unreadable file --------------------------------------------------

def test_an_unreadable_file_reads_as_agents_off(home):
    """The safe direction, and now by design rather than by luck."""
    home.write_text('{"ai": {"enabled": true}')          # truncated
    state = settings.ai()
    assert state.enabled is False
    assert state.problems, "it failed closed without saying why"


def test_an_unreadable_file_is_not_overwritten(home):
    """Saving from an empty dict would discard the host and model ids still in
    the file, turning a fixable typo into lost data."""
    broken = '{"ai": {"host": "gemini", "models": {"gemini": "gemini-2.5-pro"}}'
    home.write_text(broken)

    for change in (lambda: settings.set_enabled(True),
                   lambda: settings.set_host("bedrock"),
                   lambda: settings.set_model("gemini", "other")):
        with pytest.raises(settings.Unreadable):
            change()

    assert home.read_text() == broken, "a setter destroyed the file it could not read"


def test_the_refusal_says_which_file_and_that_nothing_changed(home):
    home.write_text("{not json")
    with pytest.raises(settings.Unreadable) as raised:
        settings.set_enabled(True)
    said = str(raised.value)
    assert str(home) in said
    assert "nothing was changed" in said


def test_a_readable_file_still_writes(home):
    """The other direction. Refusing everything would pass the test above."""
    settings.set_host("gemini")
    settings.set_model("gemini", "gemini-2.5-pro")
    settings.set_enabled(True)

    stored = json.loads(home.read_text())
    assert stored["ai"] == {"enabled": True, "host": "gemini",
                            "models": {"gemini": "gemini-2.5-pro"}}


def test_a_setter_preserves_the_settings_it_did_not_touch(home):
    """The property the refusal exists to protect, on the happy path."""
    settings.set_host("gemini")
    settings.set_model("gemini", "gemini-2.5-pro")
    settings.set_enabled(True)

    stored = json.loads(home.read_text())["ai"]
    assert stored["host"] == "gemini" and stored["models"]["gemini"] == "gemini-2.5-pro"


def test_the_cli_reports_it_rather_than_raising(home, capsys):
    """A traceback for a file the operator can fix by hand is a bad answer."""
    from munim import cli

    home.write_text("{not json")
    assert cli.config_ai("on", []) == 2
    assert "nothing was changed" in capsys.readouterr().err
