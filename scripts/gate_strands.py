"""Day-one gate: does a Strands agent reach a model and use a tool?

Tries Bedrock first, then falls back to a direct provider. The fallback exists
because Bedrock access is blocked account-wide for some entrants, and Devpost
confirmed on 2026-08-25 that a submission "stays eligible if you build it with
Strands Agents and a different model host". See docs/DECISIONS.md D16.
"""

import os
import sys

from mcpc.env import load as load_env
from strands import Agent, tool

load_env()


@tool
def add_two_numbers(a: int, b: int) -> int:
    """Add two numbers together and return the sum."""
    return a + b


# Probed against account an AISPL account on 2026-09-03:
#   anthropic.claude-sonnet-5 / opus-5 -> AccessDeniedException, "not available
#     for this account". An account-tier gate; the use case form does not lift it.
#   anthropic.claude-sonnet-4-5-... (bare) -> needs an inference profile.
#   us.anthropic.claude-sonnet-4-5-... -> gated only by the Anthropic use case form.
# So the US cross-region inference profile for Sonnet 4.5 is the target.
BEDROCK_MODEL = os.environ.get(
    "MCPC_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)


def try_bedrock():
    from strands.models.bedrock import BedrockModel

    region = os.environ.get("AWS_REGION", "us-east-1")
    return BedrockModel(model_id=BEDROCK_MODEL, region_name=region), (
        f"Bedrock {BEDROCK_MODEL} ({region})"
    )


def try_gemini():
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        raise RuntimeError("GEMINI_API_KEY not set")
    from strands.models.gemini import GeminiModel

    model_id = os.environ.get("MCPC_GEMINI_MODEL", "gemini-2.5-flash")
    # google-genai reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment,
    # so the key is never passed through argv or written to disk.
    return GeminiModel(model_id=model_id), f"Gemini {model_id}"


def try_anthropic():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    from strands.models.anthropic import AnthropicModel

    return AnthropicModel(model_id="claude-sonnet-5"), "Anthropic API"


def main() -> int:
    failures = []
    for build in (try_bedrock, try_gemini, try_anthropic):
        try:
            model, label = build()
        except Exception as exc:
            failures.append(f"{build.__name__}: {exc}")
            continue
        try:
            agent = Agent(model=model, tools=[add_two_numbers])
            text = str(agent("What is 17 plus 25? Use the tool."))
            if "42" not in text:
                failures.append(f"{label}: tool ran but 42 not in response: {text!r}")
                continue
            print(f"GATE PASSED via {label}")
            return 0
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")

    print("GATE FAILED. Every model host was tried:")
    for f in failures:
        print(f"  - {f}")
    print("\nIf Bedrock reports 'Operation not allowed', that is the known")
    print("account-wide block. Set ANTHROPIC_API_KEY and re-run; the submission")
    print("stays eligible on a different model host.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
