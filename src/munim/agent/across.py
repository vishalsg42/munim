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

from pydantic import BaseModel, Field
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

SHAPE_IT = """Now put what you just found into the required structure.

One finding per client-and-provider you actually looked at. Do not add a finding
for a client whose tools you did not call: if you could not check something, say
so in the summary instead. `evidence` is quoted from a tool result, not written
from memory; leave it empty rather than inventing one."""


class Finding(BaseModel):
    """One fact about one client. Field names match `checks.dns.CheckResult` and
    the per-finding dict `audit_all_clients` returns, so the repo has one shape
    for "something true about a client" rather than three."""

    client: str
    provider: str
    says: str
    evidence: str = ""


class Answer(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""


def connected_clients(clients, provider: str, keyring=None) -> list:
    """Those with a session for this provider. Asking about the rest would open
    a browser, which is not a thing a question gets to do.

    Takes client records, not names: the session is filed under the identity,
    and looking it up by label found nothing at all once the two were split.
    """
    def has_session(client) -> bool:
        key = getattr(client, "id", client)
        store = (KeychainTokenStorage(key, provider, keyring) if keyring
                 else KeychainTokenStorage(key, provider))
        return store._read("tokens") is not None

    return [c for c in clients if has_session(c)]


async def ask(question: str, clients: list[str], *, keyring=None,
              log=None) -> tuple["Answer", list["Finding"]]:
    """Answer `question` using every connected client's read-only tools.

    Returns the answer and whatever was set aside for naming a client the agent
    never actually read. Both halves matter to the caller, which is why this
    stopped returning a string.

    `log` is optional and, when given, is what the control room reads. This was
    the only agent-bearing tool that wrote nothing, so its result could not be
    looked up afterwards and nothing could watch it happen.
    """
    # Ahead of the per-provider keychain reads below, for the same reason as
    # within.work_on: this is importable, and refusing after doing the work
    # would be the same answer for more effort.
    off = agents_off()
    if off is not None:
        # This one returns prose rather than a dict, so the command has to be
        # folded into the sentence. A refusal with no next step is a complaint.
        return Answer(summary=f"{off['why']} Turn them on with: "
                              f"{off['fix']}"), []

    toolsets = []
    reached: dict[str, list[str]] = {}
    for provider in sorted(SERVERS):
        present = connected_clients(clients, provider, keyring)
        if not present:
            continue
        reached[provider] = present
        toolsets += toolsets_for(present, provider, keyring=keyring,
                                  read_only=True)

    if not toolsets:
        return Answer(summary=(
            "No client has a session with a provider yet, so there is nothing "
            "to read across. Connect one with "
            "`munim connect \"<client>\" cloudflare`.")), []

    # No argument. `keyring` is the session store, vault-shaped; `build_model`
    # wants a CredentialBackend and reads a model key from it. Threading one
    # object into both is how this parameter came to be passed to a function
    # that has never accepted it: two shapes, one name, third time in this
    # repository.
    model, _ = build_model()
    agent = Agent(model=model, tools=toolsets, system_prompt=SYSTEM,
                  callback_handler=None)

    roster = "\n".join(
        f"- {p}: {', '.join(getattr(c, 'name', str(c)) for c in cs)}"
        for p, cs in sorted(reached.items()))

    # ---- phase one: investigate, with the provider tools and nothing else ---
    #
    # Deliberately two calls. Passing `structured_output_model` to a single
    # invocation registers the schema as one more tool from the first turn, so
    # the model may answer before calling anything and the loop stops there:
    # the result validates perfectly and may have seen no account at all. The
    # deprecated `Agent.structured_output()` is worse again, because it does not
    # run the tool loop and every backend hands it only the schema. Either way
    # the failure is an answer that looks right and is made up, which is a worse
    # outcome than the TypeError this function used to raise.
    reply = await agent.invoke_async(
        f"Clients and the providers each is connected to:\n{roster}\n\n"
        f"Question: {question}"
    )
    prose = str(reply)
    called = _clients_reached(reply, reached)

    # ---- phase two: shape what phase one found -----------------------------
    try:
        shaped = await agent.invoke_async(SHAPE_IT, structured_output_model=Answer)
        answer = shaped.structured_output
    except Exception:
        # A model that cannot produce the schema still produced prose, and prose
        # with the findings missing beats a traceback out of an MCP tool.
        answer = None

    if answer is None:
        return Answer(summary=prose), []

    # Anything naming a client whose tools never returned is set aside rather
    # than dropped. A model naming an account it could not see is the most
    # interesting thing that happened in the run, and quietly deleting it would
    # hand back a shorter, cleaner answer with no sign anything was removed,
    # which is the same lie this function is arranged to avoid.
    kept, discarded = [], []
    for finding in answer.findings:
        # Matched through `prefix_for`, not by string equality. A model writes
        # "Ivy_Fern" for a client registered as "ivy_fern", and an end-to-end
        # run discarded exactly that: a correct, grounded finding reported as an
        # account the agent never read. `prefix_for` is the same normaliser that
        # built the tool prefixes, so a name that reaches the same tools is the
        # same client by construction.
        settled = _match(finding.client, called)
        if settled is None:
            discarded.append(finding)
            continue
        # Answered under the name the operator registered, so a reply cannot
        # quietly rename somebody's client.
        finding.client = settled
        kept.append(finding)
    answer.findings = kept
    if not answer.summary:
        answer.summary = prose

    if log is not None:
        for finding in kept:
            log.append(client=finding.client, stage="across", kind="finding",
                       human_text=finding.says,
                       detail={"provider": finding.provider,
                               "evidence": finding.evidence,
                               "question": question})
        for finding in discarded:
            # `escalated` because it is the one that needs a person to look: the
            # agent described an account whose tools never answered.
            log.append(client=finding.client, stage="across", kind="escalated",
                       human_text=f"Named {finding.client}, which was never "
                                  f"read: {finding.says}",
                       detail={"provider": finding.provider,
                               "question": question})
        log.append(client="every client", stage="across", kind="run_done",
                   human_text=answer.summary,
                   detail={"question": question,
                           "findings": len(kept), "discarded": len(discarded)})
    return answer, discarded


def _match(named: str, known: set[str]) -> str | None:
    """The registered label this name refers to, or None if it refers to none.

    Case and punctuation are the model's to get wrong and not the operator's to
    pay for. Two different clients that normalise the same are already refused
    at toolset construction, so this cannot silently pick the wrong one.
    """
    from munim.remote.toolsets import prefix_for

    try:
        wanted = prefix_for(named)
    except ValueError:
        return None
    for label in known:
        try:
            if prefix_for(label) == wanted:
                return label
        except ValueError:
            continue
    return None


def _clients_reached(reply, reached: dict) -> set[str]:
    """Clients whose own tools actually returned something.

    Not the roster. Membership of the roster says a client was *offered*, and a
    client can be offered a provider that contributes no callable tools at all,
    so checking against it is a spell-checker on client names rather than a
    boundary. `metrics.tool_metrics` is keyed by the prefixed tool name and
    counts successes, and `prefix_for` is the same function that built those
    prefixes, so this maps back to who was really read.
    """
    from munim.remote.toolsets import prefix_for

    labels = {getattr(c, "name", str(c))
              for cs in reached.values() for c in cs}
    used = {name for name, m in
            getattr(reply.metrics, "tool_metrics", {}).items()
            if getattr(m, "success_count", 0) > 0}
    return {label for label in labels
            if any(name.startswith(prefix_for(label) + "_") for name in used)}
