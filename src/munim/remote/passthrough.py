"""One client's provider tools, forwarded rather than modelled.

Munim is not a Cloudflare client. It is a credential broker in front of
Cloudflare's own MCP server, and that server already publishes what it can do.
The two ways of using that were both wrong in the same direction:

  - a CLI verb per operation (`munim dns proxied <client> <record> off`) means
    modelling eleven providers and their tools as parameters, and Cloudflare's
    `execute` takes JavaScript, so its parameter space has no bottom;
  - a sub-agent per request means Munim starts a language model to decide which
    provider tool to call, while the thing that called Munim is already an
    agent with a model. That second model is the redundancy, and it is the part
    that keeps failing: expired Bedrock credentials, a missing key, agents off
    by default, and every write silently no-ops.

So forward the tools. Munim does the part only Munim can do, which is holding
the right credential for the right client and refusing to mix them, and the
caller chooses what to call.

What that costs is stated in D31 rather than glossed. The isolation guarantee
was structural: a sub-agent built with one client's toolsets has nothing to
reach a second account with. Here it is per call: every call names a client and
resolves credentials from that client's id alone, so a single call touches
exactly one account, and orchestration across clients becomes the caller's
business, recorded rather than prevented. Weaker on paper, and easier to audit,
which is why every call goes in the run log.
"""

import json

from munim.remote.servers import all_servers, server_for
from munim.remote.session import NeedsLogin, NoRemoteServer, session_for

# What a result is truncated to before it goes in the run log. The caller gets
# the whole thing; the log is an audit trail, not a copy of the internet.
LOGGED_RESULT = 2000


class UnknownTool(Exception):
    """That provider has no tool by that name. The message names the ones it has."""


class MissingArguments(Exception):
    """A required argument was not supplied. Caught before the call goes out."""


def _missing(tool, arguments: dict) -> list[str]:
    """Required properties the caller did not supply.

    Only the top level, and only when the schema says `required` outright.
    Anything cleverer would be reimplementing JSON Schema validation, which is
    the provider's job and which it does on its own side anyway.
    """
    schema = getattr(tool, "inputSchema", None) or {}
    required = schema.get("required") or []
    if not isinstance(required, list):
        return []
    return [name for name in required if name not in arguments]


def narrow(described: list[dict], *, names_only: bool = False,
           matching: str = "") -> list[dict]:
    """A listing small enough to hold, and the one the caller asked for.

    Resend publishes 103 tools and their schemas are 122KB; the names alone are
    2.1KB. An operator hit the second number as a hard limit, had to write the
    response to a file and parse it, and the question they wanted answered was
    "which of these take a teamId".

    So `matching` searches the **argument schema** as well as the name and the
    description. `teamId` appears in neither of the first two for any Vercel
    tool: a filter over name and description would have returned nothing for
    the exact example that justifies having a filter.
    """
    wanted = matching.strip().lower()
    if wanted:
        described = [t for t in described
                     if wanted in t["tool"].lower()
                     or wanted in (t.get("does") or "").lower()
                     or wanted in json.dumps(t.get("arguments") or {}).lower()]
    if names_only:
        return [{"tool": t["tool"], "read_only": t["read_only"]}
                for t in described]
    return described


def known_providers() -> list[str]:
    return sorted(all_servers())


def _check_provider(provider: str) -> None:
    if server_for(provider) is None:
        raise NoRemoteServer(
            f"{provider!r} runs no MCP server Munim knows about. "
            f"Choose from: {', '.join(known_providers())}")


def _read_only(tool) -> bool | None:
    """Whether the provider marks this tool read-only, or None if it says nothing.

    Deliberately three-valued. `toolsets._is_read_only` collapses the unknown
    case to False because it is deciding what a cross-client agent may hold,
    where default-deny is right. Here nothing is being decided: the caller is
    told what the provider said, including that it said nothing, because "not
    annotated" and "annotated as a write" are different facts and flattening
    them would make an unannotated tool look dangerous when it may be a read.
    """
    annotations = getattr(tool, "annotations", None)
    if annotations is None or annotations.readOnlyHint is None:
        return None
    return bool(annotations.readOnlyHint) and not annotations.destructiveHint


def _described(tool) -> dict:
    return {
        "tool": tool.name,
        "does": (tool.description or "").strip(),
        "read_only": _read_only(tool),
        "arguments": getattr(tool, "inputSchema", None) or {},
    }


async def tools_for(client: str, provider: str, *, keyring=None) -> list[dict]:
    """Everything this client's session with this provider exposes.

    Read-only, and it never opens a browser: a client whose session has expired
    gets a refusal naming the command to fix it, not a consent screen appearing
    out of an MCP call nobody is watching.
    """
    _check_provider(provider)
    async with session_for(client, provider, keyring=keyring,
                           allow_login=False) as session:
        listing = await session.list_tools()
    described = [_described(t) for t in listing.tools]

    # Remembered so an expired session is not a dead end. Both providers here
    # refuse `initialize` without a token, so there is no way to ask again once
    # the credential dies, and this is the only moment the answer exists. Names
    # and schemas only: nothing about the account and no result of any call.
    from munim import toolcache
    toolcache.remember(client, provider, described)
    return described


async def describe_tool(client: str, provider: str, tool: str, *,
                        keyring=None) -> dict:
    """One tool, in full, or UnknownTool naming the ones that exist.

    Separate from `tools_for` because a caller asking about a named tool wants
    a different failure: "that is not a tool" with the alternatives, rather
    than an empty result they have to search themselves.
    """
    described = await tools_for(client, provider, keyring=keyring)
    for one in described:
        if one["tool"] == tool:
            return one
    raise UnknownTool(
        f"{provider} has no tool called {tool!r}. It has: "
        f"{', '.join(sorted(one['tool'] for one in described))}")


def _flatten(result) -> dict:
    """An MCP CallToolResult as something a caller can read.

    Text content is returned as text, and parsed when it is JSON, because every
    provider here answers in JSON inside a text block and handing back a string
    of JSON makes the caller parse it a second time.
    """
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            parts.append({"type": getattr(block, "type", "unknown")})
            continue
        try:
            parts.append(json.loads(text))
        except (ValueError, TypeError):
            parts.append(text)

    structured = getattr(result, "structuredContent", None)
    failed = bool(getattr(result, "isError", False))
    out = {"failed": failed}
    if structured is not None:
        out["result"] = structured
    elif len(parts) == 1:
        out["result"] = parts[0]
    else:
        out["result"] = parts

    # Keep both halves when they are not the same thing. `structuredContent`
    # wins above because a caller that parses a result wants the shaped one,
    # and dropping the text alongside it loses whatever the provider only said
    # in prose.
    #
    # Not gated on `isError`, and that is the lesson rather than an oversight.
    # Checked against Vercel: a call that returns
    # `{"error": "Failed to list projects."}` comes back with `isError: False`.
    # A provider that does not flag its own failures makes any condition
    # resting on that flag unreliable, so this asks whether information would
    # be lost, which is a question about the payload rather than about a claim
    # the provider may not have made.
    #
    # Honesty about scope: an operator reported one Vercel tool naming a
    # missing scope and the fix while another said only "Failed to list
    # projects." I first said munim swallowed nothing, then found this discard
    # and said it was their bug. It is a real discard and it is *not* their
    # case: reproduced live, that call returns one text block, no structured
    # half, and nothing to lose. Their symptom is Vercel's own terseness.
    if structured is not None and parts:
        said = parts[0] if len(parts) == 1 else parts
        if said != structured:
            out["said"] = said
    return out


async def call_tool(client: str, provider: str, tool: str,
                    arguments: dict | None = None, *, keyring=None,
                    log=None, stage: str = "passthrough") -> dict:
    """Call one provider tool with one client's credentials.

    `arguments` is forwarded untouched. Cloudflare's `execute` takes a
    JavaScript string and Vercel's tools take nested objects; anything that
    reshaped them would be the parameter-modelling this module exists to avoid.

    A provider that refuses comes back as a result rather than an exception,
    because a refusal is something the caller should read and act on. Being
    unable to reach the provider at all still raises.
    """
    _check_provider(provider)
    arguments = dict(arguments or {})

    # Refusals are raised *after* the session closes, never inside it. The
    # transport runs in an anyio task group, so anything raised in there comes
    # back wrapped in an ExceptionGroup and no caller's `except UnknownTool`
    # ever fires. That was already true of UnknownTool and no test could see
    # it, because a fake session is not a task group.
    refuse = None
    result = read_only = None

    async with session_for(client, provider, keyring=keyring,
                           allow_login=False) as session:
        available = {t.name: t for t in (await session.list_tools()).tools}
        if tool not in available:
            refuse = UnknownTool(
                f"{provider} has no tool called {tool!r}. It has: "
                f"{', '.join(sorted(available))}")
        else:
            # Checked here rather than on the wire. The schema is already in
            # hand, and a provider's own validation error is written for
            # whoever wrote the provider: Vercel answers a bare list_projects
            # with "teamId: Invalid input: expected string, received
            # undefined", which is true and says nothing about what to do.
            missing = _missing(available[tool], arguments)
            if missing:
                refuse = MissingArguments(
                    f"{provider}.{tool} needs {', '.join(missing)}. "
                    f"See what each one is: munim tools \"<client>\" "
                    f"{provider} {tool}")
            else:
                read_only = _read_only(available[tool])
                result = await session.call_tool(tool, arguments)

    if refuse is not None:
        raise refuse

    flat = _flatten(result)
    if log is not None:
        _record(log, client, provider, tool, arguments, flat, read_only, stage)
    return {"client": client, "provider": provider, "tool": tool,
            "read_only": read_only, **flat}


def _record(log, client, provider, tool, arguments, flat, read_only, stage):
    """Put the call in the run log.

    This is the compensating control for the softer isolation guarantee, so it
    records what was called and with what, not merely that something happened.
    A tool the provider marks read-only is an observation; everything else is a
    mutation, including the unannotated case, because a call that might have
    changed something belongs in the same list as one that did.
    """
    outcome = "failed" if flat["failed"] else "returned"
    log.append(
        client=client,
        stage=stage,
        kind="observation" if read_only else "mutation",
        human_text=f"{provider}.{tool} {outcome} for {client}",
        detail={
            "provider": provider,
            "tool": tool,
            "arguments": arguments,
            "read_only": read_only,
            "failed": flat["failed"],
            "result": _clip(flat["result"]),
        },
    )


def _clip(value):
    text = json.dumps(value, default=str)
    if len(text) <= LOGGED_RESULT:
        return value
    return {"truncated": text[:LOGGED_RESULT], "full_length": len(text)}


__all__ = ["MissingArguments", "NeedsLogin", "NoRemoteServer",
           "UnknownTool", "call_tool", "describe_tool", "known_providers",
           "tools_for"]
