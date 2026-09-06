"""Work inside one client's accounts, using their own provider tools.

The other half of "read across, write within" (D5). `ask_across_clients` spans
every client and is filtered to tools the provider marks read-only, so it can
answer and never act. This is the opposite: one client, named by the operator,
with everything their accounts can do.

Naming the client is what unlocks the writes, and it is the only thing that
does. There is no tool here that takes two clients, and the agent is built with
one container's sessions and no others, so a request that would need a second
account cannot quietly reach for one: it has nothing to reach with.

Every mutation goes to the run log as it happens, which is what makes the
control room show it and what leaves a record afterwards of what was changed in
somebody else's account.
"""

from strands import Agent

from munim.agent.model import agents_off, build_model
from munim.remote.servers import SERVERS
from munim.remote.storage import KeychainTokenStorage
from munim.remote.toolsets import toolset_for
from munim.runlog import RunLog

SYSTEM = """You are working inside one client's accounts, and only that one.

Every tool you have belongs to that client. There are no others: a request that
would need a second client's account cannot be done here, and you should say so
rather than approximate it.

Before changing anything that already exists, say what is there now and what it
would become. Creating something absent is not the same as replacing something
somebody put there on purpose, and the second deserves a sentence.

Report what you did in plain words, naming each record or resource. Somebody
who does not know the provider's vocabulary has to be able to check your work.

Be brief. No preamble."""


def connected_providers(client_id: str, keyring=None) -> list[str]:
    """Providers this client has a session with. Nothing else is reachable.

    Token **or** endpoint: a URL-authenticated provider like Zoho stores an
    endpoint and no tokens, so asking only about tokens makes it invisible.
    """
    return [p for p in sorted(SERVERS)
            if KeychainTokenStorage(client_id, p, keyring)._read("tokens")
            or KeychainTokenStorage(client_id, p, keyring).endpoint()]


async def work_on(client_id: str, label: str, request: str, log: RunLog, *,
                  keyring=None) -> dict:
    """Carry out `request` inside one client's accounts."""
    # Before the keychain is touched and before any MCPClient is built. This
    # function is importable, so a guard living only in the MCP tool would miss
    # other callers, and doing the credential reads first to then refuse would
    # be work nobody asked for.
    off = agents_off()
    if off is not None:
        return {"client": label, "did": None, **off}

    providers = connected_providers(client_id, keyring)
    if not providers:
        return {
            "client": label, "did": None,
            "why": f"{label} has no provider connected, so there is nothing to "
                   f"work with. Connect one: munim connect {label!r} cloudflare",
        }

    toolsets = [toolset_for(client_id, provider, keyring=keyring, label=label)
                for provider in providers]

    # No argument: see the note in across.ask. `keyring` is the session store
    # and `build_model` wants a CredentialBackend.
    model, model_label = build_model()
    log.append(client=label, stage="work", kind="stage_start",
               human_text=f"Working on {label}",
               detail={"providers": providers, "model": model_label,
                       "request": request})

    agent = Agent(model=model, tools=toolsets, system_prompt=SYSTEM,
                  callback_handler=None)
    reply = await agent.invoke_async(
        f"Client: {label}\nTheir connected providers: {', '.join(providers)}\n\n"
        f"{request}")

    said = str(reply)
    log.append(client=label, stage="work", kind="stage_done",
               human_text=said.strip()[:400], detail={"model": model_label})
    return {"client": label, "providers": providers, "did": said}
