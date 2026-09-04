"""Building the model host, once policy has said we may.

Split from settings.py on purpose. That module decides whether Munim is allowed
to think and on whose model; this one does the construction and nothing else.
Deciding should not require the ability to build, and the decision has to be
readable by `doctor` and the CLI, neither of which should have to import Strands.

This is the boundary where provider data would leave for a model host, so it is
where the switch is enforced. Every caller goes through here: across all of
src/, the only Strands model constructions are in this file, and all three
Agent(...) calls take what this returns. A gate here covers callers written
later, which a check in each tool would not.

Two things this file used to get wrong, both found by probing rather than by
reading:

  - Gemini and Anthropic are Strands *extras*. `strands.models.gemini` exists on
    a bare install and raises ModuleNotFoundError for `google` underneath, so a
    bare `from ... import GeminiModel` escaped build_model as ModuleNotFoundError
    rather than falling through to the next host. Every branch catches it now.
  - `auto` returned Bedrock before it looked at anything else, and constructing a
    model does not authenticate, so an unusable Bedrock beat a working Gemini
    and only failed at the first call. `settings.Ai.chosen` picks a host that is
    installed and holds a credential.
"""

from munim import settings
from munim.env import load as load_env

# Kept as a name because .env.example and the docs cite it.
BEDROCK_MODEL = settings.HOSTS["bedrock"].default_model


class AgentsDisabled(RuntimeError):
    """Agents are off, so nothing was built and nothing was sent.

    Distinct from "no host is reachable" because they are different situations
    with different fixes, and callers report them differently: one is a setting
    the operator chose, the other is something broken.
    """


class NoModelHost(RuntimeError):
    """Agents are on and no host can be built. Says which and why."""


def _construct(host: str, key: str):
    """Build one host's model, or raise NoModelHost naming the missing piece."""
    spec = settings.HOSTS[host]
    model_id = settings.model_for(host)

    try:
        if host == "bedrock":
            import os

            from strands.models.bedrock import BedrockModel
            region = os.environ.get("AWS_REGION", "us-east-1")
            return BedrockModel(model_id=model_id, region_name=region), \
                f"Bedrock {model_id}"

        if host == "gemini":
            from strands.models.gemini import GeminiModel
            # Passed rather than left to the environment, so a key held only in
            # the keychain works. Reading it back out of os.environ would have
            # meant the keychain route silently did nothing.
            args = {"api_key": key} if key else None
            return GeminiModel(client_args=args, model_id=model_id), \
                f"Gemini {model_id}"

        if host == "anthropic":
            from strands.models.anthropic import AnthropicModel
            args = {"api_key": key} if key else None
            return AnthropicModel(client_args=args, model_id=model_id), \
                f"Anthropic {model_id}"
    except ImportError as exc:
        raise NoModelHost(
            f"{host} needs a package this install does not have ({exc}). "
            f"Install it with: pip install 'munim[{spec.extra}]'"
            if spec.extra else
            f"{host} could not be imported: {exc}") from exc

    raise NoModelHost(f"{host!r} is not a model host Munim knows")


def build_model(backend=None):
    """Return (model, label).

    Raises AgentsDisabled when agents are off, before anything is constructed
    and before any credential is read. Raises NoModelHost when they are on and
    nothing can be built.
    """
    # Keys may live in ~/.munim/.env, which the MCP subprocess does not inherit.
    # The switch itself is not read from there: see settings.ai.
    load_env()

    policy = settings.ai(backend)
    if not policy.enabled:
        raise AgentsDisabled(
            "Agents are off, so nothing was sent to a model host. "
            "Turn them on with: munim config ai on")

    host = policy.chosen(backend)
    if not host:
        raise NoModelHost(_why_nothing_is_usable(policy, backend))

    key, _ = settings.resolve_key(host, backend)
    return _construct(host, key)


def _why_nothing_is_usable(policy, backend=None) -> str:
    """One sentence per host saying what it is missing, and the fix.

    "no model host available" told an operator nothing about which of three
    things to do next.
    """
    wanted = settings.ORDER if policy.host == settings.AUTO else (policy.host,)
    reasons = []
    for name in wanted:
        spec = settings.HOSTS.get(name)
        if spec is None:
            continue
        if not settings.installed(name):
            reasons.append(f"{name}: not installed"
                           + (f", run pip install 'munim[{spec.extra}]'"
                              if spec.extra else ""))
        elif spec.keys and not settings.resolve_key(name, backend)[0]:
            reasons.append(f"{name}: no key, run munim config ai key {name}")
        else:
            reasons.append(f"{name}: unavailable")
    return "agents are on and no model host can be built. " + "; ".join(reasons)


def agents_off(backend=None) -> dict | None:
    """None when agents are on. Otherwise the answer to give back, in one shape.

    Every tool that needs a model says the same thing in the same words, and
    says the command rather than only the state: a coding agent reading this can
    tell its operator what to run, which is the whole reason these tools stay
    registered instead of disappearing from the list.
    """
    if settings.ai(backend).enabled:
        return None
    return {
        "agents": "off",
        "why": "Agents are off, so this needs no model and reached none. "
               "Munim is local by default.",
        "fix": "munim config ai on",
    }
