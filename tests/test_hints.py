"""A true answer that sends the reader the wrong way.

An operator deployed to Vercel, listed the projects, saw the new one, asked for
it by id and got 404. Then by name: 404. Then with the team slug: 404. Then
through Vercel's own MCP tools: 404. Six calls hunting a wrong project id, a
wrong team and a wrong slug, for a project that was there the whole time (#46).

Nothing was broken and nothing refused. Every one of those calls carried
`teamId`, and that is the parameter which makes a session token resolve to
somewhere it does not map into. Vercel answers 404 rather than 403, so it reads
as "you typed the wrong thing" instead of "drop that argument".

These hold the shape of the hint rather than its wording, except where the
wording is the instruction.
"""

from munim.remote.hints import about

TEAM = {"teamId": "team_kfv4rb4Gg31XbEG3GfcmQWfo"}


# ---- the case that cost six calls ---------------------------------------

def test_a_404_with_a_team_named_says_to_drop_it():
    said = about("vercel", "/v9/projects/prj_x", TEAM,
                 {"status": 404, "result": {"error": {"code": "not_found"}}})
    assert "teamId" in said and "left out" in said


def test_a_200_that_came_back_empty_says_the_same():
    """The quieter half, and the one nobody would think to question. The team
    that owns eighteen projects reported none of them, with a 200."""
    said = about("vercel", "/v9/projects", TEAM,
                 {"status": 200, "result": {"projects": []}})
    assert "teamId" in said


def test_the_slug_spelling_is_caught_too():
    """Measured: passing the team slug instead of the id fails identically, so
    a hint that only knew about teamId would send somebody to the other one."""
    said = about("vercel", "/v9/projects/advent", {"slug": "acme-projects"},
                 {"status": 404, "result": {}})
    assert "slug" in said


def test_a_tool_result_with_no_status_line_is_read_from_its_text():
    """`call_provider_tool` gets Vercel's own sentence rather than a status:
    "Failed to fetch project: 404 Not Found". Weaker than matching a status
    code and the only thing available on that route."""
    said = about("vercel", "get_project_deployment_protection", TEAM,
                 {"failed": True, "result": "Failed to fetch project: 404 Not Found"})
    assert "teamId" in said


# ---- and stays quiet otherwise ------------------------------------------

def test_nothing_is_said_when_no_team_was_named():
    """An account with no projects really does return an empty list. Without a
    scoping argument in the request there is nothing to blame, and guessing
    would send somebody to delete a parameter they never sent."""
    assert about("vercel", "/v9/projects", None,
                 {"status": 200, "result": {"projects": []}}) == ""


def test_nothing_is_said_when_the_call_worked():
    assert about("vercel", "/v9/projects/prj_x", TEAM,
                 {"status": 200, "result": {"id": "prj_x", "name": "acme"}}) == ""


def test_a_404_from_another_provider_is_left_alone():
    """This is one provider's measured behaviour, not a general rule about
    404s. Cloudflare and Resend were never measured this way."""
    assert about("cloudflare", "/zones/x", TEAM, {"status": 404}) == ""


def test_a_real_refusal_is_not_relabelled():
    """A 403 is Vercel saying no, which is a different problem with a different
    fix, and covering it with a hint about teamId would be the same fault this
    exists to remove."""
    assert about("vercel", "/v9/projects", TEAM,
                 {"status": 403, "result": {"error": {"code": "forbidden"}}}) == ""


# ---- the deploy warning -------------------------------------------------

def test_a_successful_deploy_says_the_site_will_not_be_reachable():
    """Vercel creates a new project with Vercel Authentication on, so the URL
    the deploy just returned redirects to a login for everyone else. The
    operator found this by sending somebody the link."""
    said = about("vercel", "deploy_to_vercel", {"name": "acme"},
                 {"failed": False, "result": {"url": "acme.vercel.app"}})
    assert "Vercel Authentication" in said
    # The route that works, named exactly, because the obvious one does not.
    assert "call_provider_api" in said and "ssoProtection" in said


def test_a_failed_deploy_is_not_told_about_sso():
    assert about("vercel", "deploy_to_vercel", {"name": "acme"},
                 {"failed": True, "result": "build failed"}) == ""
