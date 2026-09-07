"""The checks that are not about DNS, and the line that was missing.

`check_deploy_current`, `check_env_applied` and `check_env_scoped` have been in
`adapters/vercel.py` since it was written, return the same `CheckResult` type as
the thirteen DNS checks, and were tested. Nothing in `src/` called them. The
control room even reserved chips for two of them and claimed in a comment that
they were "real on a launch with Vercel connected", which was false for the life
of the project.

What was missing was not the checks. `projects()` returns names and ids and no
domains, so nothing could answer "which project serves acme.example". These test
that answer, and the rule that governs every path that cannot find one:

    Skip, never fail.

D20 exists because a check that fires wrongly is worth less than no check, and
reporting "we could not find your Vercel project" as "your deploy is stale" is
that failure wearing a useful-looking hat.
"""

import httpx
import respx

from munim.checks.hosting import CHECKS, run_hosting_async
from munim.container import Container

API = "https://api.vercel.com"


class Keychain:
    def __init__(self, has_vercel=True):
        self.has_vercel = has_vercel

    def get(self, client, provider):
        if provider == "vercel" and self.has_vercel:
            return "vc-token"
        return None


def _container(has_vercel=True):
    return Container("acme", Keychain(has_vercel))


def _statuses(results):
    return {r.check: r.status for r in results}


def _reasons(results):
    return {r.detail.get("reason") for r in results}


# ---- the paths that must skip ---------------------------------------------


async def test_no_container_skips_rather_than_failing():
    results = await run_hosting_async(None, "acme.example")

    assert [r.check for r in results] == list(CHECKS)
    assert set(_statuses(results).values()) == {"skip"}


async def test_a_client_with_no_vercel_credential_skips():
    """Most clients will never have Vercel connected. That is not a fault in
    their hosting and must not be reported as one."""
    results = await run_hosting_async(_container(has_vercel=False),
                                      "acme.example")

    assert set(_statuses(results).values()) == {"skip"}
    assert _reasons(results) == {"no_credential"}


@respx.mock
async def test_a_domain_no_project_serves_skips():
    """The important one. Guessing a project here would report somebody else's
    stale deploy as this client's."""
    respx.get(f"{API}/v9/projects").mock(
        return_value=httpx.Response(200, json={"projects": []}))

    results = await run_hosting_async(_container(), "acme.example")

    assert set(_statuses(results).values()) == {"skip"}
    assert _reasons(results) == {"no_project"}


@respx.mock
async def test_vercel_being_down_skips_rather_than_failing():
    respx.get(f"{API}/v9/projects").mock(
        return_value=httpx.Response(500, json={"error": {"message": "boom"}}))

    results = await run_hosting_async(_container(), "acme.example")

    assert set(_statuses(results).values()) == {"skip"}
    assert _reasons(results) == {"unreachable"}


# ---- resolving the project ------------------------------------------------


@respx.mock
async def test_a_project_named_after_the_domain_is_found_by_search():
    """One call answers the common case: Vercel's search matches the project
    name, which is usually the apex label."""
    respx.get(f"{API}/v9/projects", params__contains={"search": "acme"}).mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "prj_1", "name": "acme"}]}))
    respx.get(f"{API}/v9/projects/prj_1/domains").mock(
        return_value=httpx.Response(200, json={
            "domains": [{"name": "acme.example"}]}))
    respx.get(f"{API}/v6/deployments").mock(
        return_value=httpx.Response(200, json={"deployments": []}))
    respx.get(f"{API}/v9/projects/prj_1/env").mock(
        return_value=httpx.Response(200, json={"envs": []}))

    results = await run_hosting_async(_container(), "acme.example")

    assert [r.check for r in results] == list(CHECKS)
    # No deployments and no variables, so these are honest skips and passes
    # from the checks themselves rather than from not finding the project.
    assert _reasons(results) != {"no_project"}


@respx.mock
async def test_a_project_whose_name_does_not_match_is_found_by_its_domains():
    """A project called `website` serving `acme.example` is normal, and search
    alone would miss it."""
    respx.get(f"{API}/v9/projects", params__contains={"search": "acme"}).mock(
        return_value=httpx.Response(200, json={"projects": []}))
    respx.get(f"{API}/v9/projects", params__contains={"limit": "100"}).mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "prj_9", "name": "website"}]}))
    respx.get(f"{API}/v9/projects/prj_9/domains").mock(
        return_value=httpx.Response(200, json={
            "domains": [{"name": "acme.example"}]}))
    respx.get(f"{API}/v6/deployments").mock(
        return_value=httpx.Response(200, json={"deployments": []}))
    respx.get(f"{API}/v9/projects/prj_9/env").mock(
        return_value=httpx.Response(200, json={"envs": []}))

    results = await run_hosting_async(_container(), "acme.example")

    assert _reasons(results) != {"no_project"}


@respx.mock
async def test_a_name_collision_alone_is_not_a_match():
    """A project called `acme` that serves a different domain is somebody
    else's site. Matching on the name alone is how a client gets told about
    it."""
    respx.get(f"{API}/v9/projects", params__contains={"search": "acme"}).mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "prj_x", "name": "acme"}]}))
    respx.get(f"{API}/v9/projects/prj_x/domains").mock(
        return_value=httpx.Response(200, json={
            "domains": [{"name": "somethingelse.test"}]}))
    respx.get(f"{API}/v9/projects", params__contains={"limit": "100"}).mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "prj_x", "name": "acme"}]}))

    results = await run_hosting_async(_container(), "acme.example")

    assert _reasons(results) == {"no_project"}


@respx.mock
async def test_the_search_for_a_project_is_bounded():
    """A busy account must not turn one check into fifty round trips."""
    many = [{"id": f"prj_{i}", "name": f"p{i}"} for i in range(40)]
    respx.get(f"{API}/v9/projects", params__contains={"search": "acme"}).mock(
        return_value=httpx.Response(200, json={"projects": []}))
    respx.get(f"{API}/v9/projects", params__contains={"limit": "100"}).mock(
        return_value=httpx.Response(200, json={"projects": many}))
    asked = respx.get(url__regex=rf"{API}/v9/projects/prj_\d+/domains").mock(
        return_value=httpx.Response(200, json={"domains": []}))

    await run_hosting_async(_container(), "acme.example")

    assert asked.call_count <= 10, \
        f"asked {asked.call_count} projects what they serve"


# ---- one check failing is not all of them failing --------------------------


@respx.mock
async def test_one_endpoint_refusing_does_not_take_the_others_with_it():
    """A 403 on the environment endpoint should not lose the deploy check."""
    respx.get(f"{API}/v9/projects", params__contains={"search": "acme"}).mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "prj_1", "name": "acme"}]}))
    respx.get(f"{API}/v9/projects/prj_1/domains").mock(
        return_value=httpx.Response(200, json={
            "domains": [{"name": "acme.example"}]}))
    respx.get(f"{API}/v6/deployments").mock(
        return_value=httpx.Response(200, json={"deployments": []}))
    respx.get(f"{API}/v9/projects/prj_1/env").mock(
        return_value=httpx.Response(403, json={"error": {"message": "nope"}}))

    results = await run_hosting_async(_container(), "acme.example")

    assert [r.check for r in results] == list(CHECKS)
    assert len(results) == 3, "a refused endpoint dropped the other checks"


# ---- the guard that would have caught the orphans --------------------------


def test_every_check_a_provider_adapter_produces_has_a_caller():
    """The bug this whole file exists because of.

    ARCHITECTURE.md: "A capability that is not implemented is absent from the
    tool list rather than present and inert." Three checks were written, tested,
    documented in the room's chip list, and reachable from nothing. Nobody
    noticed for the life of the project, because tests calling a function look
    exactly like production calling it.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).parent.parent / "src" / "munim"
    adapters = (root / "adapters").glob("*.py")
    src = "\n".join(p.read_text(encoding="utf-8")
                    for p in root.rglob("*.py")
                    if "adapters" not in p.parts)

    orphans = []
    for path in adapters:
        text = path.read_text(encoding="utf-8")
        for name in re.findall(r"async def (check_\w+)", text):
            if name not in src:
                orphans.append(f"{path.name}:{name}")

    assert orphans == [], (
        "these produce a CheckResult and nothing outside adapters/ calls them, "
        f"so they can never run: {', '.join(orphans)}")


def test_the_chip_list_and_the_checks_agree():
    """The room's chip list is hand-maintained in JavaScript and the checks are
    in Python, so nothing but this connects them. It claimed two Vercel chips
    were live while their producers had no caller."""
    import pathlib
    import re

    root = pathlib.Path(__file__).parent.parent
    reducer = (root / "src" / "munim" / "room" / "static" / "reduce.mjs")
    chips = set(re.findall(r'"([a-z_]+)"',
                           reducer.read_text(encoding="utf-8")
                           .split("export const CHECKS = [", 1)[1]
                           .split("]", 1)[0]))

    assert set(CHECKS) <= chips, \
        f"hosting checks with no chip: {set(CHECKS) - chips}"
