"""Nothing under tests/ may write to the real home directory.

`check` writes an HTML report, and its default destination is
`~/.munim/reports`. Every test that exercised the tool left four files there;
the directory had reached 85 before anyone looked. Passing `reports_dir` fixes
the tests that remember to. This fixture covers the ones that do not.
"""

import pytest

import munim.report


@pytest.fixture(autouse=True)
def _never_write_to_the_real_home(tmp_path, monkeypatch):
    monkeypatch.setattr(munim.report, "REPORTS_DIR", tmp_path / "reports")


@pytest.fixture(autouse=True)
def _agents_are_off_and_no_host_is_real(tmp_path, monkeypatch):
    """No test may reach a model host, and none may read the operator's config.

    This replaces a fixture that monkeypatched `munim.agent.launch.build_model`
    to raise. That covered one of three call sites: `across` and `within` were
    unprotected, and every `check` test was forced down the `except Exception`
    branch, so no test could ever observe the path a real install takes.

    Two layers now. Settings point at tmp_path with every model variable
    cleared, so agents are off by default exactly as a fresh install is, which
    is the state worth exercising. And `_construct` refuses, so a test that
    turns agents on still cannot talk to Bedrock: those tests inject a fake
    model through `build_model` instead.

    Clearing the environment matters as much as the file. A developer with a
    Gemini key exported would otherwise have their machine decide what the
    suite asserts, which is the bug already found once for `.env`.
    """
    import munim.agent.model

    monkeypatch.setenv("MUNIM_SETTINGS", str(tmp_path / "settings.json"))
    for name in ("MUNIM_AI", "MUNIM_AI_HOST", "MUNIM_PREFER",
                 "MUNIM_BEDROCK_MODEL", "MUNIM_GEMINI_MODEL",
                 "MUNIM_ANTHROPIC_MODEL", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "ANTHROPIC_API_KEY", "AWS_PROFILE", "AWS_ACCESS_KEY_ID",
                 "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    import importlib.util

    from munim import settings

    real = munim.agent.model._construct

    def really_importable(host: str) -> bool:
        # Asked of the filesystem, not of settings.installed, which a test is
        # allowed to monkeypatch. A test that fakes "this host is installed"
        # must not thereby unlock a real network client.
        spec = settings.HOSTS.get(host)
        try:
            return bool(spec) and importlib.util.find_spec(spec.needs) is not None
        except (ImportError, ValueError):
            return False

    def guarded(host, key):
        # Only hosts that could actually build a client are refused. One whose
        # backend is absent cannot reach anything, and letting the real code run
        # for it is what lets a test assert that a missing extra comes back as
        # NoModelHost rather than as ModuleNotFoundError.
        if really_importable(host):
            raise AssertionError(
                f"a test tried to build a real {host} model. Inject a fake "
                f"through build_model instead.")
        return real(host, key)

    monkeypatch.setattr(munim.agent.model, "_construct", guarded)


@pytest.fixture(autouse=True)
def _never_read_the_real_dotenv(tmp_path, monkeypatch):
    """No test may read the operator's own .env.

    `load()` walks up from the working directory, and pytest runs in the repo
    root, so anything calling it picked up the real file. Four tests asserting
    "gmail is not configured" started failing the moment a command began
    loading the env, because the developer running them had configured gmail.

    Worse than flaky: a test could have passed on a machine that happened to
    have a key set, and the suite would have been reporting that machine's
    configuration rather than the code's behaviour.

    MUNIM_ENV is the first thing `candidates()` consults, so pointing it at a
    file that does not exist stops the walk before it starts.

    Blocking the load is not enough on its own. `load_dotenv` puts values into
    os.environ, and they stay there for the rest of the pytest process, so one
    test that loads the real file configures every test after it. The variables
    are cleared as well.
    """
    import os

    monkeypatch.setenv("MUNIM_ENV", str(tmp_path / "no-such.env"))
    for name in list(os.environ):
        if name.endswith(("_OAUTH_CLIENT_ID", "_OAUTH_CLIENT_SECRET")):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_test_may_touch_the_real_keychain(monkeypatch):
    """`munim.container.keyring` was the one door left open.

    `munim.remote.storage.keyring` gets swapped by the tests that care, and that
    covered sessions. Nothing swapped the module the API-key backend uses, so
    any test reaching `disconnect(everything=True)` ran `_sweep_orphans`, which
    dumps the operator's real login keychain, treats every real client id as an
    orphan because the registry under test is a temporary one, and deletes
    through the unpatched backend.

    It destroyed nothing only because no `munim:<provider>` API-key items happen
    to exist on the machine this was found on. One `munim connect "<client>"
    <provider> --token` and the suite would have started eating live
    credentials.

    Same shape as `_never_write_to_the_real_home` above, and for the same
    reason: the test suite must not be able to reach anything the operator
    would miss.
    """
    import munim.container

    class Nowhere:
        def __init__(self): self.store = {}
        def get_password(self, service, account):
            return self.store.get((service, account))
        def set_password(self, service, account, secret):
            self.store[(service, account)] = secret
        def delete_password(self, service, account):
            self.store.pop((service, account), None)

    monkeypatch.setattr(munim.container, "keyring", Nowhere())
