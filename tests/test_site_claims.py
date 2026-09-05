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


def test_the_policy_discloses_the_mcp_transport():
    """The thing this page never said, and the one a reader most needs.

    Munim is an MCP server. The coding agent calls its tools and puts the
    results in its own model's context, so every tool result reaches that
    agent's model provider, on every run, whatever Munim's own settings say.
    The page listed the providers and Munim's own model host and then said
    "Nowhere else", which was not true of the transport it runs on.
    """
    policy = (SITE / "privacy.html").read_text()
    assert "MCP server" in policy
    assert "coding agent" in policy


def test_the_policy_says_munims_own_reasoning_is_off_by_default():
    """Opt-in is the claim that makes the disclosure above bearable, so it has
    to be on the page rather than only in the README."""
    policy = (SITE / "privacy.html").read_text()
    assert "off by default" in policy
    assert "munim config ai on" in policy


def test_the_documents_only_name_model_hosts_that_can_be_built():
    """Rule-shaped, and covering the README as well as the policy.

    The policy offered "OpenAI or a local model through Ollama", and a previous
    version of this file asserted the Ollama sentence was present, so the test
    was pinning the overclaim in place. build_model wires three hosts. Scoped to
    one file this fixes one of the two documents that got it wrong.
    """
    from munim import settings

    known = {h.capitalize() for h in settings.ORDER} | {"Gemini", "Bedrock", "Anthropic"}
    never = {"Ollama", "OpenAI", "Mistral", "LiteLLM", "Llama"}

    for name in ("privacy.html",):
        text = (SITE / name).read_text()
        offenders = sorted(w for w in never if w in text)
        assert not offenders, \
            f"{name} offers model hosts Munim cannot build: {offenders}"

    readme = (SITE.parent / "README.md").read_text()
    offenders = sorted(w for w in never if w in readme)
    assert not offenders, f"README offers model hosts Munim cannot build: {offenders}"
    assert "Any Strands-supported host works" not in readme, \
        "Strands supports more hosts than Munim wires, so this overclaims"


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
    named = set(re.findall(r"munim (disconnect|connect|clients|doctor|config)", policy))
    # `sys.executable -m munim.cli`, not the bare name. Shelling out to
    # `munim` runs whatever is on PATH, which is the globally installed build,
    # so this test could pass while the branch under test had renamed or
    # removed the command the policy names. It was checking someone else's code.
    help_text = subprocess.run([sys.executable, "-m", "munim.cli", "--help"],
                               capture_output=True, text=True).stdout
    for command in named:
        assert command in help_text, f"policy names `munim {command}`, which does not exist"


def test_every_page_links_the_other_two():
    """Google wants the privacy policy reachable from the homepage."""
    pages = {p.name for p in SITE.glob("*.html")}
    assert pages == {"index.html", "privacy.html", "terms.html"}
    index = (SITE / "index.html").read_text()
    assert "privacy.html" in index and "terms.html" in index
