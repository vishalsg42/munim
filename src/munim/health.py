"""Whether a stored credential still works, which only the provider can say.

`connected.connections()` reports what is *stored*: a token blob or an
endpoint. That is not the same question, and the gap between them cost a day.
Both Cloudflare and Vercel sessions had died, and `list_clients`,
`client_status` and `doctor` all reported them connected, because a token on
disk looks identical whether or not the provider will still accept it.

Nothing local can close that gap. OAuth grants a token and says nothing more:
no absolute expiry for the refresh token, no revocation signal. The only
authority on whether a credential still works is the party that issued it, so
this module asks them.

Which is why it is the one thing in munim that goes out to the network to
answer a question about local state, and why `check_all` runs the probes
together. Serially it is one round trip after another and grows with every
client; concurrently it is bounded by the slowest provider, so eight clients
cost about what one does.
"""

import asyncio
from dataclasses import dataclass

from munim.connected import connections
from munim.container import KeychainBackend

# How long one provider gets before the probe gives up on it. Short on purpose:
# this runs on every `doctor`, and a provider that has not answered in this
# long will not make the report more useful by answering later.
TIMEOUT = 8.0

LIVE = "connected"
EXPIRED = "needs authentication"
UNREACHABLE = "could not be reached"


@dataclass(frozen=True)
class Status:
    client: str          # the operator's name for them, not the id
    provider: str
    state: str           # LIVE, EXPIRED or UNREACHABLE
    detail: str = ""     # why, when it is not live
    tools: int = 0

    @property
    def live(self) -> bool:
        return self.state == LIVE

    @property
    def fix(self) -> str:
        # Only an expired session has a fix somebody can run. Telling a person
        # to reconnect when their wifi is off sends them through a browser
        # login for nothing, which is why UNREACHABLE is a separate state
        # rather than folded into EXPIRED.
        return (f'munim connect "{self.client}" {self.provider}'
                if self.state == EXPIRED else "")


async def check(client_id: str, name: str, provider: str,
                backend=None) -> Status:
    """Open one session and close it, reporting what happened.

    `backend` is threaded through rather than defaulted here. Without it
    `session_for` builds its own store against the real credentials, so a
    caller that injected one enumerated from theirs and probed the operator's,
    which makes the injection seam a lie.
    """
    from munim.remote.servers import server_for
    from munim.remote.session import NeedsLogin, NoRemoteServer, session_for

    try:
        async with asyncio.timeout(TIMEOUT):
            # verify=False because this asks whether the session opens, not
            # whether it is bound to the account it was bound to before. The
            # drift check belongs to real work, not to a health report.
            async with session_for(client_id, provider, backend=backend,
                                   allow_login=False, verify=False) as session:
                listing = await session.list_tools()
        return Status(name, provider, LIVE, tools=len(listing.tools))
    except NeedsLogin:
        return Status(name, provider, EXPIRED, "the session expired")
    except NoRemoteServer as absent:
        # Two very different things raise this. `session_for` raises it when a
        # provider runs no MCP server at all, which is a non-answer. `auth_for`
        # raises it when a provider that will not register a client on demand
        # has no application registered by hand, and that is a session which
        # cannot be opened at all. Gmail is the second, and it was being
        # reported as connected.
        if server_for(provider) is None:
            return Status(name, provider, LIVE)
        return Status(name, provider, EXPIRED, str(absent))
    except (TimeoutError, asyncio.TimeoutError):
        return Status(name, provider, UNREACHABLE, f"no answer in {TIMEOUT:.0f}s")
    except Exception as other:
        return Status(name, provider, UNREACHABLE,
                      f"could not be reached ({type(other).__name__})")


def _stored(registry, backend) -> list[tuple[str, str, str]]:
    """(client id, client name, provider) for everything with a credential.

    Skips a client whose credentials cannot be read rather than raising:
    `doctor._keychain` already reports an unreadable store, and one broken
    check must not take the whole report down with it.
    """
    work = []
    for record in registry.clients():
        try:
            _, sessions = connections(record.id, backend)
        except Exception:
            continue
        work += [(record.id, record.name, p) for p in sessions]
    return work


async def check_all_async(registry, backend=None) -> list[Status]:
    """Every stored session for every client, probed together.

    The async entry point, for the MCP server, which is already inside a loop.
    """
    backend = backend or KeychainBackend()
    work = _stored(registry, backend)
    if not work:
        return []
    return list(await asyncio.gather(
        *(check(*item, backend=backend) for item in work)))


def check_all_for(record, provider: str, backend=None) -> Status:
    """One client's one provider, probed now.

    After a reconnect the cached status is stale by definition, and re-probing
    every client to refresh one of them would make the menu pay for the whole
    estate on every action.
    """
    try:
        return asyncio.run(check(record.id, record.name, provider,
                                 backend=backend))
    except RuntimeError:
        return Status(record.name, provider, UNREACHABLE, "could not be checked")


def check_all(registry, backend=None) -> list[Status]:
    """The same, for callers with no event loop of their own: doctor and the CLI."""
    try:
        return asyncio.run(check_all_async(registry, backend))
    except RuntimeError:
        # Called from inside a running loop, which means the caller wanted
        # check_all_async. Skipping beats crashing whatever asked.
        return []
