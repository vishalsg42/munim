"""Whether Munim may think is a decision, not a side effect of having a key.

Every switch test asserts both directions. This project has shipped a test that
inspected a field before the flow discarded it, asserted the opposite of the
truth, and passed; a one-directional assertion here would pass just as well if
the setting were ignored entirely.
"""

import json

import pytest

from munim import settings


def test_a_fresh_install_has_agents_off():
    """The whole point. A key alone must not amount to consent."""
    assert settings.ai().enabled is False


def test_turning_them_on_sticks():
    settings.set_enabled(True)
    assert settings.ai().enabled is True
    settings.set_enabled(False)
    assert settings.ai().enabled is False


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("off", False), ("", False),
])
def test_the_switch_reads_the_words_people_actually_type(value, expected, monkeypatch):
    monkeypatch.setenv("MUNIM_AI", value)
    assert settings.ai().enabled is expected


def test_an_unrecognised_switch_value_is_off_and_says_so(monkeypatch):
    """Neither silently on because the string is non-empty, nor silently off."""
    monkeypatch.setenv("MUNIM_AI", "maybe")
    state = settings.ai()
    assert state.enabled is False
    assert any("maybe" in p for p in state.problems), state.problems


def test_the_environment_beats_the_file_in_both_directions(monkeypatch):
    settings.set_enabled(False)
    monkeypatch.setenv("MUNIM_AI", "1")
    assert settings.ai().enabled is True

    settings.set_enabled(True)
    monkeypatch.setenv("MUNIM_AI", "0")
    assert settings.ai().enabled is False


def test_the_switch_is_ignored_in_a_dotenv_file(tmp_path, monkeypatch):
    """python-dotenv writes into os.environ permanently, and the MCP server
    loads once at startup. A MUNIM_AI in a file would go sticky for the life of
    that process and silently beat every later `munim config ai on`, so the
    command would report success while the running server stayed off."""
    from munim import env

    dotenv = tmp_path / ".env"
    dotenv.write_text("MUNIM_AI=1\nGEMINI_API_KEY=from-the-file\n")
    monkeypatch.setenv("MUNIM_ENV", str(dotenv))

    env.load()
    import os
    assert os.environ.get("MUNIM_AI") is None
    assert os.environ.get("GEMINI_API_KEY") == "from-the-file", \
        "only the switch is excluded; ordinary settings still load"
    assert settings.ai().enabled is False


def test_a_switch_in_a_file_is_reported_rather_than_silently_dropped(tmp_path, monkeypatch):
    from munim import env

    dotenv = tmp_path / ".env"
    dotenv.write_text("MUNIM_AI=1\n")
    monkeypatch.setenv("MUNIM_ENV", str(dotenv))
    assert [name for _, name in env.ignored_in()] == ["MUNIM_AI"]


def test_a_corrupt_settings_file_fails_closed(tmp_path, monkeypatch):
    """Agents off, with a reason, rather than an exception on every command
    including the one you would run to fix it."""
    broken = tmp_path / "settings.json"
    broken.write_text("{not json,}")
    monkeypatch.setenv("MUNIM_SETTINGS", str(broken))

    state = settings.ai()
    assert state.enabled is False
    assert state.problems


def test_an_unknown_host_fails_closed(monkeypatch):
    monkeypatch.setenv("MUNIM_AI", "1")
    monkeypatch.setenv("MUNIM_AI_HOST", "gpt9")
    state = settings.ai()
    assert state.enabled is False, "an unreadable host must not leave agents on"
    assert any("gpt9" in p for p in state.problems)


def test_model_ids_are_kept_per_host():
    """One shared id is a bug rather than a simplification: set a Gemini id,
    switch to Bedrock, and it would be handed to BedrockModel(model_id=...).
    The environment variables this replaced were already separate."""
    settings.set_model("gemini", "gemini-2.5-pro")
    assert settings.model_for("gemini") == "gemini-2.5-pro"
    assert settings.model_for("bedrock") == settings.HOSTS["bedrock"].default_model


def test_a_model_id_resolves_environment_then_file_then_default(monkeypatch):
    assert settings.model_for("gemini") == settings.HOSTS["gemini"].default_model
    settings.set_model("gemini", "from-the-file")
    assert settings.model_for("gemini") == "from-the-file"
    monkeypatch.setenv("MUNIM_GEMINI_MODEL", "from-the-environment")
    assert settings.model_for("gemini") == "from-the-environment"


def test_a_key_resolves_environment_before_keychain(monkeypatch):
    class Backend:
        def get(self, account, name): return "from-the-keychain"
        def set(self, account, name, secret): pass
        def forget(self, account, name): return True

    assert settings.resolve_key("gemini", Backend()) == ("from-the-keychain", "keychain")
    monkeypatch.setenv("GEMINI_API_KEY", "from-the-environment")
    assert settings.resolve_key("gemini", Backend()) == ("from-the-environment", "environment")


def test_google_api_key_is_still_accepted(monkeypatch):
    """Both build_model and doctor took it before this change. Dropping it would
    quietly disconnect installs that work today."""
    class Backend:
        def get(self, account, name): return None

    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert settings.resolve_key("gemini", Backend())[0] == "x"


def test_settings_are_written_as_readable_json(tmp_path, monkeypatch):
    """It sits beside registry.json and servers.json and is meant to be opened."""
    monkeypatch.setenv("MUNIM_SETTINGS", str(tmp_path / "settings.json"))
    settings.set_enabled(True)
    settings.set_host("gemini")
    written = json.loads((tmp_path / "settings.json").read_text())
    assert written["ai"]["enabled"] is True
    assert written["ai"]["host"] == "gemini"
