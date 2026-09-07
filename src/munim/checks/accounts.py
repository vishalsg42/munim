"""Is this client's account still reachable? Asked of every provider at once.

The other two check families are per-thing: thirteen about DNS, three about
Vercel hosting. Writing a third family per provider does not scale and would not
finish, and most of what the other eight providers expose has no deterministic
question worth asking anyway.

This is the question that generalises. It is the same question for all eleven,
the provider is the only party who can answer it, and `health.check` already
asks it: open a session, see what happens, close it. What was missing was
treating the answer as a **check result** rather than as a connection status, so
it lands in the run log, the report and the room beside everything else.

Why it is worth having, in the words the owner would use:

    Your Sentry connection expired on 14 August, so nobody has seen an error
    from your site in three weeks.

That is a real small-business failure, it is deterministic, it needs no model,
and nothing else in this project would have told you.

**Not chips.** The room's chip grid is a fixed four-column layout whose whole
value is that nothing moves between renders. Eleven variable chips would break
that, so these render as findings in the stream instead.
"""

import asyncio
import logging

from munim import health, words
from munim.checks.dns import CheckResult

logger = logging.getLogger(__name__)

# Long enough for a slow provider, short enough that a client with eight
# connections does not add a minute to a check. The probes run together, so
# this bounds the whole family rather than each one.
TIMEOUT = 12.0


def name_for(provider: str) -> str:
    return f"account_{provider}"


def _result(client: str, status) -> CheckResult:
    """One provider's answer, in the shape every other check uses.

    Three states rather than two, because "we could not reach them" and "they
    told us this credential is dead" are different facts. The first may be a
    flaky network and is not the operator's fault or problem; the second needs
    a person to sign in again. Reporting the first as the second sends somebody
    to reconnect an account that was fine, which is the exact failure
    `connected.py` was written about.
    """
    if status.state == health.LIVE:
        return CheckResult(
            name_for(status.provider), "pass",
            f"{status.provider} answered, and published "
            f"{words.count(status.tools, 'tool')}.",
            f"Your {status.provider} connection is working.",
            detail={"provider": status.provider, "tools": status.tools})

    if status.state == health.EXPIRED:
        return CheckResult(
            name_for(status.provider), "fail",
            f"{status.provider} rejected the stored credential: {status.detail}",
            f"The connection to {status.provider} has expired, so nothing has "
            f"been able to read or change anything there since it did.",
            evidence=status.detail,
            detail={"provider": status.provider, "fix":
                    f'munim connect "{client}" {status.provider}'})

    # Unreachable. Deliberately a skip: this says nothing about the credential.
    return CheckResult(
        name_for(status.provider), "skip",
        f"{status.provider} could not be reached: {status.detail}",
        f"We could not reach {status.provider} just now, so its connection was "
        f"not checked. This does not mean anything is wrong with it.",
        detail={"provider": status.provider, "reason": "unreachable"})


async def run_accounts_async(client_id: str, client: str, providers,
                             *, keyring=None,
                             timeout: float = TIMEOUT) -> list[CheckResult]:
    """One result per provider this client has a session with.

    Concurrently, because serially this is one round trip after another and
    grows with every provider, exactly as `health.check_all` reasons about
    clients.
    """
    wanted = sorted(providers)
    if not wanted:
        return []

    async def ask(provider: str):
        return await health.check(client_id, client, provider, keyring=keyring)

    try:
        answers = await asyncio.wait_for(
            asyncio.gather(*(ask(p) for p in wanted), return_exceptions=True),
            timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        logger.debug("account probes for %s timed out after %ss", client, timeout)
        return [CheckResult(
            name_for(p), "skip",
            f"{p} did not answer in {timeout:g}s.",
            f"We could not reach {p} just now, so its connection was not "
            f"checked.",
            detail={"provider": p, "reason": "unreachable"}) for p in wanted]

    out = []
    for provider, answer in zip(wanted, answers):
        if isinstance(answer, BaseException):
            # One provider throwing is not the others throwing. `health.check`
            # already catches broadly, so reaching here means something further
            # out went wrong, and it should not lose the nine that answered.
            logger.debug("probing %s for %s raised: %s", provider, client, answer)
            out.append(CheckResult(
                name_for(provider), "skip",
                f"{provider} could not be checked: "
                f"{type(answer).__name__}: {answer}",
                f"We could not check the connection to {provider}.",
                detail={"provider": provider, "reason": "unreachable"}))
            continue
        out.append(_result(client, answer))
    return out
