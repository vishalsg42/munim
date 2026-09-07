"""The checks that are not about DNS, and the reason there were none.

Three of these have existed in `adapters/vercel.py` since it was written, return
the same `CheckResult` type as the thirteen DNS checks, and are tested. Nothing
in `src/` called them. The only callers anywhere were in `tests/test_vercel.py`,
and the control room reserved two chips for them with a comment claiming they
were "real on a launch with Vercel connected", which was not true.

So the catalogue was DNS-only by accident rather than by design, and that is the
honest answer to "why does this only look at DNS". What was missing was not the
checks. It was the one line that maps a client's domain to a Vercel project,
because `projects()` returns names and ids and no domains.

**Skip, never fail.** Every path that cannot answer returns `skip`. D20 exists
because a check that fires wrongly is worth less than no check, and reporting
"we could not find your Vercel project" as "your deploy is stale" is exactly
that failure wearing a useful-looking hat.
"""

import logging

from munim.adapters.vercel import Vercel, VercelError
from munim.checks.dns import CheckResult
from munim.container import UnknownCredential, UnsupportedProvider

logger = logging.getLogger(__name__)

CHECKS = ("deploy_current", "env_applied", "env_scoped")


def _skipped(why: str, reason: str) -> list[CheckResult]:
    return [CheckResult(name, "skip", why, why, detail={"reason": reason})
            for name in CHECKS]


async def run_hosting_async(container, domain: str) -> list[CheckResult]:
    """The three Vercel checks for whoever serves this domain, or three skips.

    Takes a container rather than a project id because the caller has a client
    and a domain and should not have to know Vercel's addressing to ask a
    question about a client's website.
    """
    if container is None or not container.has("vercel"):
        return _skipped("No Vercel credential for this client, so its hosting "
                        "was not checked.", "no_credential")

    vercel = Vercel(container)
    try:
        project = await vercel.project_for(domain)
    except (UnknownCredential, UnsupportedProvider, VercelError) as exc:
        logger.debug("could not resolve a vercel project for %s: %s", domain, exc)
        return _skipped("Vercel could not be reached, so this client's hosting "
                        "was not checked.", "unreachable")

    if not project:
        return _skipped(f"No Vercel project serves {domain}, so there was "
                        f"nothing to check.", "no_project")

    out = []
    for name, ask in (("deploy_current", vercel.check_deploy_current),
                      ("env_applied", vercel.check_env_applied),
                      ("env_scoped", vercel.check_env_scoped)):
        try:
            out.append(await ask(project))
        except (VercelError, UnknownCredential, UnsupportedProvider) as exc:
            # One check failing is not the others failing. A 403 on the
            # environment endpoint should not take the deploy check with it.
            logger.debug("vercel %s failed for %s: %s", name, project, exc)
            out.append(CheckResult(
                name, "skip", f"Vercel would not answer about {name}.",
                f"Part of this client's hosting could not be checked.",
                detail={"reason": "unreachable", "project": project}))
    return out
