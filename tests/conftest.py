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
def _no_live_model_calls(monkeypatch):
    """No test may call a model host over the network.

    `check` runs the agent now, so without this the suite reaches for Bedrock
    on every check test: slow, flaky, and dependent on whoever runs it having
    credentials. Clearing the keys drives `explain` down its documented
    degradation path instead, which is the behaviour a fresh clone gets and is
    therefore worth exercising by default.
    """
    # Clearing the environment is not enough: build_model calls load_env(),
    # which reads .env back in and hands the tests a live key. The suite went
    # from 3s to 41s that way, talking to Gemini on every check test.
    import munim.agent.launch

    def refuse():
        raise RuntimeError("no model host available: disabled for tests")

    monkeypatch.setattr(munim.agent.launch, "build_model", refuse)


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
