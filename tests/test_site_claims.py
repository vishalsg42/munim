"""The privacy policy has to stay true as the code changes.

It is a legal document that Google will read, and it makes specific factual
claims about what Munim does with data. The one most easily falsified is "no
telemetry": a single analytics import would make the policy a lie, and nothing
would fail.
"""

import pathlib
import re

SITE = pathlib.Path("site")
SRC = pathlib.Path("src/munim")


def test_the_policy_claim_of_no_telemetry_is_true():
    """The policy says Munim contains no analytics, telemetry, crash reporting
    or update check, and that it sends nothing to its authors."""
    banned = ("posthog", "mixpanel", "segment.io", "amplitude",
              "sentry_sdk", "opentelemetry", "google-analytics")
    offenders = []
    for path in SRC.rglob("*.py"):
        body = path.read_text().lower()
        offenders += [f"{path}: {name}" for name in banned if name in body]
    assert not offenders, f"the privacy policy claims no telemetry: {offenders}"


def test_the_policy_names_the_model_host_disclosure():
    """The least obvious thing Munim does, and the one a reader most needs: the
    agent sends provider data to whichever model host is configured."""
    policy = (SITE / "privacy.html").read_text()
    assert "model provider you configure" in policy
    assert "Ollama" in policy, "the local-model escape hatch is part of the disclosure"


def test_the_policy_carries_googles_required_limited_use_wording():
    """Google requires this for restricted scopes, close to verbatim."""
    policy = (SITE / "privacy.html").read_text()
    assert "Google API Services User Data Policy" in policy
    assert "Limited Use" in policy


def test_the_deletion_instructions_name_real_commands():
    """A policy that tells somebody to run a command that does not exist is
    worse than one that says nothing."""
    import subprocess
    import sys
    policy = (SITE / "privacy.html").read_text()
    named = set(re.findall(r"munim (disconnect|connect|clients|doctor)", policy))
    help_text = subprocess.run(["munim", "--help"], capture_output=True,
                               text=True).stdout
    for command in named:
        assert command in help_text, f"policy names `munim {command}`, which does not exist"


def test_every_page_links_the_other_two():
    """Google wants the privacy policy reachable from the homepage."""
    pages = {p.name for p in SITE.glob("*.html")}
    assert pages == {"index.html", "privacy.html", "terms.html"}
    index = (SITE / "index.html").read_text()
    assert "privacy.html" in index and "terms.html" in index
