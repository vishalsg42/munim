"""Day-one gate: does a Strands agent reach a model and use a tool?

Tries Bedrock first, then falls back to a direct provider. The fallback exists
because Bedrock access is blocked account-wide for some entrants, and Devpost
confirmed on 2026-08-25 that a submission "stays eligible if you build it with
Strands Agents and a different model host". See docs/DECISIONS.md D16.
"""

import os
import sys

from strands import Agent, tool


@tool
def add_two_numbers(a: int, b: int) -> int:
    """Add two numbers together and return the sum."""
    return a + b


def try_bedrock():
    from strands.models.bedrock import BedrockModel

    region = os.environ.get("AWS_REGION", "us-west-2")
    return BedrockModel(region_name=region), f"Bedrock ({region})"


def try_anthropic():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    from strands.models.anthropic import AnthropicModel

    return AnthropicModel(model_id="claude-sonnet-5"), "Anthropic API"


def main() -> int:
    failures = []
    for build in (try_bedrock, try_anthropic):
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
