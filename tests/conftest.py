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
