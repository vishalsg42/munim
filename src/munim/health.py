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
import time
from dataclasses import dataclass, replace

from munim.connected import connections
from munim.container import KeychainBackend

# How long one provider gets before the probe gives up on it. Short on purpose:
# this runs on every `doctor`, and a provider that has not answered in this
# long will not make the report more useful by answering later.
TIMEOUT = 8.0

LIVE = "connected"
PENDING = "connecting"
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
    def settled(self) -> bool:
        """Whether this is an answer rather than a question still open."""
        return self.state != PENDING

    @property
    def fix(self) -> str:
        # Only an expired session has a fix somebody can run. Telling a person
        # to reconnect when their wifi is off sends them through a browser
        # login for nothing, which is why UNREACHABLE is a separate state
        # rather than folded into EXPIRED.
        return (f'munim connect "{self.client}" {self.provider}'
                if self.state == EXPIRED else "")


async def check(client_id: str, name: str, provider: str,
                keyring=None) -> Status:
    """Open one session and close it, reporting what happened.

    `keyring` is the session store, and it is deliberately not the same thing
    as the `backend` the enumeration takes. `connections()` wants a
    CredentialBackend, with get/set/forget; `session_for` wants a vault-like
    object, with get_password/set_password. Passing the first where the second
    belongs raised AttributeError on every probe, and the broad except below
    relabelled it "could not be reached", so `doctor` reported the network as
    down when nothing had been tried. Two seams, two names.
    """
    from munim.remote.servers import server_for
    from munim.remote.session import NeedsLogin, NoRemoteServer, session_for

    try:
        async with asyncio.timeout(TIMEOUT):
            # verify=False because this asks whether the session opens, not
            # whether it is bound to the account it was bound to before. The
            # drift check belongs to real work, not to a health report.
            async with session_for(client_id, provider, keyring=keyring,
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
    except (OSError, BaseExceptionGroup) as other:
        # Only transport failures. A TypeError or AttributeError under here is
        # a bug in Munim, and reporting it as an unreachable provider is how
        # one hid for a whole afternoon: every session read "could not be
        # reached" while the real fault was an argument of the wrong type.
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


async def check_all_async(registry, backend=None, keyring=None) -> list[Status]:
    """Every stored session for every client, probed together.

    The async entry point, for the MCP server, which is already inside a loop.
    """
    work = _stored(registry, backend or KeychainBackend())
    if not work:
        return []
    return list(await asyncio.gather(
        *(check(*item, keyring=keyring) for item in work)))


class Stream:
    """Probes running on the caller's own event loop, pumped a slice at a time.

    Deliberately not a thread. A background thread probing while the main
    thread draws can write to the same stderr the menu owns: the MCP SDK logs
    a traceback on any OAuth failure that is not a plain NeedsLogin, and
    interpreter teardown can emit after the terminal has been restored. Either
    corrupts the operator's shell.

    So the loop lives here and the caller decides when it runs. `pump()`
    advances it by one slice and returns whether anything changed; the menu
    calls it from its idle path, between keypresses, on the one thread that
    already owns the screen.

    The work list is computed **once** and shared by the seed and the probes.
    Two calls to `_stored` are two chances to disagree, and a row set that
    shrinks under a moving cursor is how a menu acts on the wrong thing.
    """

    def __init__(self, registry, backend=None, keyring=None):
        self._keyring = keyring
        self._work = _stored(registry, backend or KeychainBackend())
        self.statuses = [Status(name, provider, PENDING)
                         for _, name, provider in self._work]
        self._loop = None
        self._tasks = None
        self._deadline = None

    @property
    def settled(self) -> bool:
        return all(s.settled for s in self.statuses)

    def _start(self):
        self._loop = asyncio.new_event_loop()
        # Keyed by (client, provider), not by position in `statuses`. That list
        # is public and the caller edits it: `browse` drops a row when a
        # credential is disconnected and appends one when it is reconnected, so
        # a position recorded here stops naming the same probe the moment
        # either happens. It crashed with IndexError once the list got shorter,
        # and before it got that far it wrote one client's result onto another.
        self._tasks = {
            self._loop.create_task(check(cid, name, provider,
                                         keyring=self._keyring)): (name, provider)
            for cid, name, provider in self._work}
        # A hard stop, because "keep ticking until everything settles" with no
        # ceiling is a menu that polls forever if one probe never reports.
        self._deadline = time.monotonic() + TIMEOUT + 2

    def pump(self, slice_seconds: float = 0.0) -> bool:
        """Advance the probes. True when something on screen should change."""
        if self.settled:
            return False
        if self._loop is None:
            self._start()

        pending = [t for t in self._tasks if not t.done()]
        if pending:
            self._loop.run_until_complete(
                asyncio.wait(pending, timeout=slice_seconds,
                             return_when=asyncio.FIRST_COMPLETED))

        changed = False
        for task, key in self._tasks.items():
            if not task.done():
                continue
            at = next((i for i, s in enumerate(self.statuses)
                       if (s.client, s.provider) == key), None)
            # Two reasons to drop a result on the floor, and both are normal.
            # The row is gone, because the credential was disconnected while
            # this probe was in flight. Or it is already settled, because a
            # reconnect answered the same question with something newer than
            # a probe that started before it.
            if at is None or self.statuses[at].settled:
                continue
            self.statuses[at] = task.result()
            changed = True

        if not self.settled and time.monotonic() > self._deadline:
            self.statuses = [s if s.settled
                             else replace(s, state=UNREACHABLE,
                                          detail="gave up waiting")
                             for s in self.statuses]
            changed = True
        if self.settled:
            self.close()
        return changed

    def close(self):
        if self._loop is None:
            return
        for task in self._tasks:
            task.cancel()
        try:
            self._loop.run_until_complete(
                asyncio.gather(*self._tasks, return_exceptions=True))
        finally:
            self._loop.close()
            self._loop = None


def check_all_for(record, provider: str, backend=None, keyring=None) -> Status:
    """One client's one provider, probed now.

    After a reconnect the cached status is stale by definition, and re-probing
    every client to refresh one of them would make the menu pay for the whole
    estate on every action.
    """
    try:
        return asyncio.run(check(record.id, record.name, provider,
                                 keyring=keyring))
    except RuntimeError:
        return Status(record.name, provider, UNREACHABLE, "could not be checked")


class NotChecked(RuntimeError):
    """The probes could not be run at all, which is not the same as nothing.

    An empty result reads as "this estate is connected to nothing", and the
    navigable view acted on exactly that: every client rendered as `nothing
    connected` with an offer to connect it, for an operator whose whole estate
    was fine. "I could not look" and "there is nothing there" need different
    answers.
    """


def check_all(registry, backend=None) -> list[Status]:
    """The same, for callers with no event loop of their own: doctor and the CLI."""
    try:
        return asyncio.run(check_all_async(registry, backend))
    except RuntimeError as why:
        # Called from inside a running loop, which means the caller wanted
        # check_all_async and reached for the wrong door.
        raise NotChecked(str(why)) from why
