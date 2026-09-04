"""One question, answered across every client at once.

This is the capability D15 says nothing else does, and until now it was a
deterministic DNS sweep: useful, but it could only answer questions the check
catalogue already asked. With a session per client against the providers' own
MCP servers, the same shape answers questions nobody wrote a check for, because
the provider's own tools are there.

The safety property is structural, not instructed. Every toolset here is built
read-only, so a tool that changes anything is not present to be called. "Read
across, write within" (D5) stops depending on the model doing as it is told.
"""

from strands import Agent

from munim.agent.model import agents_off, build_model
from munim.remote.servers import SERVERS
from munim.remote.storage import KeychainTokenStorage
from munim.remote.toolsets import toolsets_for

SYSTEM = """You answer one question about several clients at once.

You have each client's own tools, named with that client's prefix. A tool named
acme_ltd_* acts on Acme Ltd's account and no other. Never assume two clients
share anything.

Every tool you have is read-only. If answering would require changing something,
say what would have to change and which client it belongs to. Do not claim you
changed it.

Name the client beside every fact. A finding without a client attached is
useless to someone who looks after a dozen of them.

Be brief. No preamble."""


def connected_clients(clients, provider: str, backend=None) -> list:
    """Those with a session for this provider. Asking about the rest would open
    a browser, which is not a thing a question gets to do.

    Takes client records, not names: the session is filed under the identity,
    and looking it up by label found nothing at all once the two were split.
    """
    def has_session(client) -> bool:
        key = getattr(client, "id", client)
        store = (KeychainTokenStorage(key, provider, backend) if backend
                 else KeychainTokenStorage(key, provider))
        return store._read("tokens") is not None

    return [c for c in clients if has_session(c)]


async def ask(question: str, clients: list[str], *, backend=None) -> str:
    """Answer `question` using every connected client's read-only tools."""
    # Ahead of the per-provider keychain reads below, for the same reason as
    # within.work_on: this is importable, and refusing after doing the work
    # would be the same answer for more effort.
    off = agents_off()
    if off is not None:
        # This one returns prose rather than a dict, so the command has to be
        # folded into the sentence. A refusal with no next step is a complaint.
        return f"{off['why']} Turn them on with: {off['fix']}"

    toolsets = []
    reached: dict[str, list[str]] = {}
    for provider in sorted(SERVERS):
        present = connected_clients(clients, provider, backend)
        if not present:
            continue
        reached[provider] = present
        toolsets += toolsets_for(present, provider, backend=backend,
                                 read_only=True)

    if not toolsets:
        return ("No client has a session with a provider yet, so there is "
                "nothing to read across. Connect one with "
                "`munim connect \"<client>\" cloudflare`.")

    model, _ = build_model(backend)
    agent = Agent(model=model, tools=toolsets, system_prompt=SYSTEM,
                  callback_handler=None)

    roster = "\n".join(
        f"- {p}: {', '.join(getattr(c, 'name', str(c)) for c in cs)}"
        for p, cs in sorted(reached.items()))
    reply = await agent.invoke_async(
        f"Clients and the providers each is connected to:\n{roster}\n\n"
        f"Question: {question}"
    )
    return str(reply)
