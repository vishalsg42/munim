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


async def check(client_id: str, name: str, provider: str) -> Status:
    """Open one session and close it, reporting what happened."""
    from munim.remote.session import NeedsLogin, NoRemoteServer, session_for

    try:
        async with asyncio.timeout(TIMEOUT):
            # verify=False because this asks whether the session opens, not
            # whether it is bound to the account it was bound to before. The
            # drift check belongs to real work, not to a health report.
            async with session_for(client_id, provider, allow_login=False,
                                   verify=False) as session:
                listing = await session.list_tools()
        return Status(name, provider, LIVE, tools=len(listing.tools))
    except NeedsLogin:
        return Status(name, provider, EXPIRED, "the session expired")
    except NoRemoteServer:
        # Nothing to probe rather than something broken.
        return Status(name, provider, LIVE)
    except (TimeoutError, asyncio.TimeoutError):
        return Status(name, provider, UNREACHABLE, f"no answer in {TIMEOUT:.0f}s")
    except Exception as other:
        return Status(name, provider, UNREACHABLE,
                      f"could not be reached ({type(other).__name__})")


def check_all(registry, backend=None) -> list[Status]:
    """Every stored session for every client, probed together.

    Returns [] rather than raising when credentials cannot be read at all:
    `doctor._keychain` already reports that, and one broken check must not take
    the whole report down with it.
    """
    backend = backend or KeychainBackend()
    work = []
    for record in registry.clients():
        try:
            _, sessions = connections(record.id, backend)
        except Exception:
            continue
        work += [(record.id, record.name, p) for p in sessions]

    if not work:
        return []

    async def everything():
        return await asyncio.gather(*(check(*item) for item in work))

    try:
        return list(asyncio.run(everything()))
    except RuntimeError:
        # Already inside a loop, which no caller of this is. Skipping beats
        # crashing whatever asked.
        return []
