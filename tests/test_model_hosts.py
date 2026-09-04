"""A host Munim offers has to be a host Munim can build.

Found by probing rather than by reading: `pyproject.toml` pinned bare
`strands-agents`, and Strands ships Gemini and Anthropic as extras. So
`strands.models.gemini` existed on disk with no `google` package underneath,
`build_model` raised ModuleNotFoundError for two of the three documented hosts,
and `doctor` reported them as fine because it only checked whether a key was set.
"""

import importlib.util
import pathlib

import pytest

from munim import settings
from munim.agent import model as model_module

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "munim"


def _importable(host: str) -> bool:
    try:
        return importlib.util.find_spec(settings.HOSTS[host].needs) is not None
    except (ImportError, ValueError):
        return False


def test_only_one_module_constructs_a_model():
    """Rule-shaped rather than a list of the three call sites there are today.

    The switch is enforced inside build_model, so a fourth constructor landing
    anywhere else would be a hole in it. Written this way because a test that
    named the current callers would keep passing while a new one appeared.
    """
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.relative_to(SRC).as_posix() == "agent/model.py":
            continue
        text = path.read_text()
        if "strands.models" in text:
            offenders.append(path.relative_to(SRC).as_posix())
    assert offenders == [], \
        f"these import a model backend outside agent/model.py: {offenders}"


@pytest.mark.parametrize("host", settings.ORDER)
def test_no_host_leaks_a_module_not_found(host, monkeypatch):
    """The regression test. Every host either builds or explains itself.

    A ModuleNotFoundError escaping build_model is the specific failure this
    guards: it bypassed the "no model host available" message the function is
    written to produce, so the operator got a stack trace naming a package they
    had never heard of instead of a sentence naming the fix.
    """
    if _importable(host):
        pytest.skip(f"{host} is installed here, so there is no missing extra "
                    f"to report")

    monkeypatch.setenv("MUNIM_AI", "1")
    monkeypatch.setenv("MUNIM_AI_HOST", host)
    # Claim it is installed when it is not, which is exactly the state that
    # produced the crash: doctor believed a key was enough.
    monkeypatch.setattr(settings, "installed", lambda name: True)
    monkeypatch.setattr(settings, "resolve_key",
                        lambda name, backend=None: ("x", "environment"))

    with pytest.raises(model_module.NoModelHost) as raised:
        model_module.build_model()
    said = str(raised.value)
    assert "ModuleNotFound" not in said
    extra = settings.HOSTS[host].extra
    if extra:
        assert f"munim[{extra}]" in said, said


@pytest.mark.parametrize("host", settings.ORDER)
def test_every_host_declares_how_to_install_it(host):
    """A host with no extra has to be one that ships with strands-agents,
    or the message telling somebody to install it would name nothing."""
    spec = settings.HOSTS[host]
    if not spec.extra:
        assert _importable(host), \
            f"{host} declares no extra, so it must ship with strands-agents"


def test_the_declared_extras_exist_in_pyproject():
    """The install command the error message prints has to be real."""
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    declared = set(data["project"].get("optional-dependencies", {}))
    needed = {s.extra for s in settings.HOSTS.values() if s.extra}
    assert needed <= declared, \
        f"build_model tells people to install extras that do not exist: " \
        f"{sorted(needed - declared)}"


def test_auto_does_not_pick_a_host_it_cannot_build(monkeypatch):
    """`auto` returned Bedrock before it looked at anything else, and
    constructing a model does not authenticate, so an unusable Bedrock beat a
    working Gemini and only failed at the first call."""
    monkeypatch.setattr(settings, "installed", lambda name: name == "gemini")
    monkeypatch.setattr(settings, "resolve_key",
                        lambda name, backend=None: ("x", "environment"))
    assert settings.ai().chosen() == "gemini"


def test_auto_reports_nothing_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(settings, "installed", lambda name: False)
    assert settings.ai().chosen() == ""
