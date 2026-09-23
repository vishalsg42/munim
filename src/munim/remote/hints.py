"""What a provider's answer means, when the answer is true and misleading.

A provider that refuses usually says so. The ones worth writing down here are
the ones that answer successfully with nothing, or answer 404 for something
that exists, because the caller then goes looking for a mistake they did not
make. An operator spent six calls hunting a wrong project id, a wrong team and
a wrong slug for a project that was there the whole time (#46).

Nothing here changes a request or a result. The provider's own answer is
returned exactly as it arrived and a sentence is put beside it, because a hint
that rewrote the answer would be a second thing to distrust.

Each entry is a measurement with a date, the same rule the provider table
follows. A hint guessed from documentation is worse than no hint: it sends
somebody confidently in one direction.
"""

# Vercel, measured 2026-09-17 against a live session token on a hobby team:
#
#   GET /v9/projects                                200, 18 projects
#   GET /v9/projects?teamId=team_...                200, projects: []
#   GET /v9/projects/prj_...?teamId=team_...        404  not_found
#   GET /v9/projects/prj_...?slug=<the team slug>   404  not_found
#   GET /v9/projects/<name>                         200, the whole project
#   GET /v2/user                                    200
#   GET /v2/teams                                   200, role OWNER of that team
#
# Every project in that listing has `accountId` equal to the same team the
# credential owns, so the team that owns them reports none of them. That is not
# a permission answer, it is a lookup landing somewhere else, and it happens
# only when `teamId` or `slug` is supplied.
#
# The likely mechanism is that the token an MCP session issues is already bound
# to one account context, so naming a team asks it to resolve somewhere it does
# not map into, and Vercel answers 404 rather than 403. That part is inference.
# The table above is not.
#
# Vercel's own MCP tools mark `teamId` **required**, which is why
# `get_project_deployment_protection` and `update_project_deployment_protection`
# cannot be called successfully on such a credential at all.
_SCOPING = ("teamId", "slug", "teamSlug")

_DROP_THE_TEAM = (
    "Vercel answered this way for a resource the same credential can read "
    "without {named}. A session token is already bound to one account, so "
    "naming a team asks it to look somewhere it does not map into, and Vercel "
    "returns 404 or an empty list rather than saying so. Retry with {named} "
    "left out.")

_SSO_ON_BY_DEFAULT = (
    "A new Vercel project is created with Vercel Authentication on, so every "
    "deployment URL redirects to a login and nobody else can open it. Munim "
    "cannot turn that off through Vercel's MCP tools, which require teamId and "
    "so always fail on this credential. Use call_provider_api instead: "
    "PATCH /v9/projects/<name> with {\"ssoProtection\": null} and no teamId.")


def _emptied(result) -> bool:
    """A 200 that carried nothing where something was asked for.

    Only a collection under a single key, which is the shape every Vercel
    listing uses. A genuinely empty account looks the same, so this is a hint
    and never an error.
    """
    if not isinstance(result, dict):
        return isinstance(result, list) and not result
    lists = [v for v in result.values() if isinstance(v, list)]
    return bool(lists) and all(not v for v in lists)


def about(provider: str, target: str, sent: dict | None, out: dict) -> str:
    """One sentence to put beside the provider's answer, or "".

    `target` is the path or the tool name, `sent` is the query or the
    arguments, `out` is the result as the caller will receive it.
    """
    if provider != "vercel":
        return ""

    if "deploy" in target.lower() and not out.get("failed"):
        return _SSO_ON_BY_DEFAULT

    named = [k for k in _SCOPING if (sent or {}).get(k)]
    if not named:
        return ""
    if out.get("status") == 404 or _looks_missing(out) or _emptied(out.get("result")):
        return _DROP_THE_TEAM.format(named=" or ".join(named))
    return ""


def _looks_missing(out: dict) -> bool:
    """A tool result that says not found without an HTTP status to say it with.

    `call_provider_tool` gets the provider's own sentence rather than a status
    line: Vercel's MCP server answers "Failed to fetch project: 404 Not Found"
    in a text block. Matching on that text is weaker than matching on a status
    and is the only thing available on that route.
    """
    if not out.get("failed") and "404" not in str(out.get("result", "")):
        return False
    said = str(out.get("result", "")).lower()
    return "404" in said or "not found" in said or "not_found" in said
