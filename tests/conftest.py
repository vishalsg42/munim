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
