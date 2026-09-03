"""Which model host to use.

Strands is the requirement; the host is a config line (D16, D17). Bedrock first,
then Gemini, then Anthropic - so restoring Bedrock later is an env change and
not a code change.
"""

import os

from munim.env import load as load_env

BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def build_model():
    """Return (model, label). Raises only if no host is reachable at all."""
    load_env()
    tried = []

    if os.environ.get("MUNIM_PREFER") != "gemini":
        try:
            from strands.models.bedrock import BedrockModel

            model_id = os.environ.get("MUNIM_BEDROCK_MODEL", BEDROCK_MODEL)
            region = os.environ.get("AWS_REGION", "us-east-1")
            return BedrockModel(model_id=model_id, region_name=region), f"Bedrock {model_id}"
        except Exception as exc:  # pragma: no cover - depends on account state
            tried.append(f"bedrock: {exc}")

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        from strands.models.gemini import GeminiModel

        model_id = os.environ.get("MUNIM_GEMINI_MODEL", "gemini-2.5-flash")
        return GeminiModel(model_id=model_id), f"Gemini {model_id}"
    tried.append("gemini: GEMINI_API_KEY not set")

    if os.environ.get("ANTHROPIC_API_KEY"):
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(model_id="claude-sonnet-5"), "Anthropic API"
    tried.append("anthropic: ANTHROPIC_API_KEY not set")

    raise RuntimeError("no model host available: " + "; ".join(tried))
