"""The MCP surface.

Transport and tool registration only; no provider logic lives here.

Two rules hold across every tool (docs/DECISIONS.md D5, D6):

  - **No ambient client.** Anything that changes a client's account takes
    `client` explicitly. An implicit "current client" is how the right change
    lands in the wrong account.
  - **No credential crosses this boundary.** No tool returns a token, and no
    tool accepts one it then echoes back.

Read across, write within: `find_across_clients` may span every container and
mutates nothing; everything that writes names one client and loads only that
client's credentials.
"""

import asyncio
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from munim.agent.launch import launch
from munim.checks.dns import run_all_async, run_reachability_async
from munim.connect.oauth import PROVIDERS as OAUTH_PROVIDERS
from munim.connected import reachable
from munim.connect.token import TokenConnector
from munim.container import Container, KeychainBackend, UnknownClient
from munim.env import load as load_env
from munim.registry import ClientRecord, Registry
from munim.remote.session import NeedsLogin, NoRemoteServer
from munim.report import write as write_report
from munim.runlog import RunLog, all_runs, new_run_id

# Tools that change a client's account. The test suite asserts each one takes an
# explicit `client`; adding a mutating tool without it fails the build.
# Tools that change something. Every one names its client, because a write
# without a named account is the failure D5 exists to prevent. `plan_mail_setup`
# is here despite changing no DNS: it creates a sending domain in the operator's
# Resend account, and a tool that creates anything belongs on this list rather
# than in an argument about whether it counts.
MUTATING = {"connect_provider", "plan_mail_setup", "apply_mail_setup",
            "work_on_client", "call_provider_tool"}

# Tools that span more than one client's container. None of them may mutate, and
# the set is named here rather than inferred, so adding one is a decision
# somebody makes rather than a thing that happens.
CROSS_CLIENT = {"find_across_clients", "ask_across_clients",
                "audit_all_clients"}

PROVIDERS = ("cloudflare", "vercel", "resend")


def _shaped(record, stored: list[str], found) -> dict:
    """One client's row: what is stored, and what actually opens.

    Both are reported. `connected` answers "can I use this right now", which is
    what a caller acts on; `stored` answers "is there a credential here", which
    is what `munim disconnect` acts on. Collapsing them is what let two dead
    sessions read as connected, and dropping `stored` would hide a credential
    that exists but no longer works.
    """
    from munim import health

    mine = {s.provider: s for s in found if s.client == record.name}
    return {
        "client": record.name,
        "domain": record.domain,
        "checked": True,
        "stored": stored,
        "connected": sorted(p for p in stored
                            if p in mine and mine[p].live),
        "needs_login": sorted(p for p in stored if p in mine
                              and mine[p].state == health.EXPIRED),
        "unreachable": sorted(p for p in stored if p in mine
                              and mine[p].state == health.UNREACHABLE),
        # Everything stored that no probe covered. `stored` is API keys plus
        # MCP sessions; only the sessions half can be opened and therefore
        # probed. Without this bucket a pasted key fell out of all three
        # answers while `checked: true` claimed otherwise, which is a worse
        # lie than the one this surface was changed to fix. The four buckets
        # partition `stored`, and a test asserts that.
        "not_checked": sorted(p for p in stored if p not in mine),
    }


def build_server(backend=None, registry=None, runs_dir=None,
                 reports_dir=None) -> FastMCP:
    server = FastMCP("munim")
    backend = backend or KeychainBackend()
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")
    runs = Path(runs_dir) if runs_dir else None
    # A caller that redirects the run log means it away from the real home;
    # leaving reports behind wrote test output into ~/.munim/reports for every
    # check a test ran.
    reports = Path(reports_dir) if reports_dir else None

    def container_for(client: str) -> Container:
        return Container.for_client(registry, client, backend)

    def resolve(target: str) -> ClientRecord:
        """Turn whatever the operator said into a client.

        Accepts a client name, a domain already registered to one, or a domain
        nobody has mentioned before - which gets registered on the spot. Reads
        are safe to open this way because a DNS lookup is public; writes are not,
        and they still require a client that was named deliberately (D5).
        """
        target = target.strip()
        known = {r.name.lower(): r for r in registry.clients()}
        if target.lower() in known:
            return known[target.lower()]

        by_domain = registry.find_by_domain(target)
        if by_domain is not None:
            return by_domain

        if "." not in target:
            raise UnknownClient(
                f"No client called {target!r}, and it is not a domain either. "
                f"Known: {', '.join(sorted(r.name for r in registry.clients())) or 'none yet'}"
            )
        # First mention of a domain registers it, named after itself until the
        # operator renames it. Better than refusing and making them do setup.
        record = ClientRecord(name=target, domain=target)
        registry.add(record)
        return record

    # ---- read across -----------------------------------------------------

    @server.tool()
    async def list_clients(check: bool = True) -> list[dict]:
        """List every client and which providers each can actually reach.

        `connected` means the session opens right now, not that a credential is
        filed. Those are different facts, and reporting the second as the first
        is how two dead sessions read as connected for a day: nothing local can
        tell them apart, because OAuth grants a token and never says another
        word about it.

        So this asks each provider, concurrently. Pass `check=false` to skip
        that and report only what is stored, which is instant and was the old
        behaviour.
        """
        from munim import health

        records = registry.clients()
        stored = {r.name: reachable(r.id, backend) for r in records}
        if not check:
            return [{"client": r.name, "domain": r.domain,
                     "stored": stored[r.name], "checked": False}
                    for r in records]

        found = await health.check_all_async(registry, backend)
        return [_shaped(r, stored[r.name], found) for r in records]

    @server.tool()
    async def find_across_clients(need: str) -> list[dict]:
        """Answer one question across every client at once.

        Read-only by design: this is the one place that spans containers, so it
        can never mutate. `need` is one of: "email_unprotected", "no_dmarc",
        "domain_unresolved".
        """
        wanted = {
            "email_unprotected": ("spf_single", "dkim_present"),
            "no_dmarc": ("dmarc_present", "dmarc_policy"),
            "domain_unresolved": ("apex_resolves", "ns_delegated"),
        }.get(need)
        if wanted is None:
            raise ValueError(f"unknown question {need!r}")

        # Every client at once. Serially this was one blocking network call
        # after another inside the event loop, so the whole server froze for
        # the length of the slowest client - on the one tool whose entire
        # purpose is spanning them all.
        records = [r for r in registry.clients() if r.domain]
        per_client = await asyncio.gather(
            *(run_all_async(r.domain) for r in records))

        hits = []
        for record, results in zip(records, per_client):
            for result in results:
                if result.check in wanted and result.status == "fail":
                    hits.append({"client": record.name, "domain": record.domain,
                                 "check": result.check, "says": result.human_text})
        return hits

    @server.tool()
    async def ask_across_clients(question: str) -> dict:
        """Ask one question about every client at once, using their own accounts.

        Where `find_across_clients` answers the questions the check catalogue
        already asks, this reaches each client's provider account through that
        provider's own MCP server, so it can answer ones nobody wrote a check
        for. Only clients with a session are included.

        Read-only by construction: every tool it holds is filtered to those the
        provider marks read-only, so a tool that changes anything is not
        present to be called. Naming one client is what unlocks writes (D5).
        """
        from munim.agent.across import ask, connected_clients
        from munim.agent.model import agents_off
        from munim.remote.servers import SERVERS

        off = agents_off()
        if off is not None:
            return {"question": question, **off}

        records = registry.clients()
        reachable = sorted({c.name for p in SERVERS
                            for c in connected_clients(records, p)})
        answer = await ask(question, records)
        return {
            "question": question,
            "clients_read": reachable,
            "clients_registered": len(records),
            "answer": answer,
        }

    @server.tool()
    async def audit_all_clients(dkim_selector: str = "resend") -> dict:
        """Check every client at once and report only what needs attention.

        The thing an operator actually wants running: silent when everything
        passes, and a list when it does not. Nobody runs thirteen checks by
        hand on a dozen clients, which is why the failures that break nothing
        visible survive for weeks.

        Read-only across every client, like `find_across_clients`. It answers
        the whole catalogue rather than one question, and it names the client
        beside every finding, because a finding without one is useless to
        somebody looking after a dozen.
        """
        records = [r for r in registry.clients() if r.domain]
        if not records:
            return {"checked": 0, "clients": [],
                    "note": "no client has a domain yet, so there is nothing to "
                            "audit. Ask about a domain and it registers itself."}

        log = RunLog(new_run_id(), runs)
        log.append(client="all clients", stage="verify", kind="stage_start",
                   human_text=f"Auditing {len(records)} clients")

        async def audit(record):
            results = await run_all_async(record.domain, dkim_selector=dkim_selector)
            results += await run_reachability_async(record.domain)
            return record, results

        done = await asyncio.gather(*(audit(r) for r in records),
                                    return_exceptions=True)

        needs_attention, unreachable, clean = [], [], []
        for outcome in done:
            if isinstance(outcome, BaseException):
                unreachable.append({"error": f"{type(outcome).__name__}: {outcome}"})
                continue
            record, results = outcome
            failures = [r for r in results if r.status == "fail"]
            if not failures:
                clean.append(record.name)
                continue
            for failure in failures:
                needs_attention.append({
                    "client": record.name, "domain": record.domain,
                    "check": failure.check, "says": failure.human_text,
                    "evidence": failure.evidence, "resolver": failure.resolver,
                })
                log.append(client=record.name, stage="verify", kind="finding",
                           human_text=failure.human_text or failure.operator_text,
                           detail={"check": failure.check,
                                   "evidence": failure.evidence,
                                   "resolver": failure.resolver})

        log.append(client="all clients", stage="verify", kind="run_done",
                   human_text=(f"{len(clean)} of {len(records)} clients clean"
                               if not needs_attention else
                               f"{len(needs_attention)} thing(s) need attention "
                               f"across {len(records) - len(clean)} client(s)"))

        return {
            "checked": len(records),
            "clean": clean,
            "needs_attention": needs_attention,
            "unreachable": unreachable,
            "run_id": log.run_id,
            "report": f"http://127.0.0.1:8977/reports/{log.run_id}",
        }

    @server.tool()
    async def work_on_client(client: str, request: str) -> dict:
        """Do something inside one client's accounts, using their own tools.

        The other half of read across, write within. `ask_across_clients` spans
        every client and can only read; this is one client and can act, and
        naming them is what unlocks it.

        The agent is built with that client's sessions and no others, so a
        request needing a second account has nothing to reach with rather than
        a rule telling it not to. Every change is written to the run log as it
        happens: open the control room to watch, or read it back afterwards.
        """
        from munim.agent.model import agents_off
        from munim.agent.within import work_on

        off = agents_off()
        if off is not None:
            return {"client": client, **off}

        record = registry.get(client)
        log = RunLog(new_run_id(), runs)
        result = await work_on(record.id, record.name, request, log)
        return {**result, "run_id": log.run_id}

    # ---- the provider's own tools ----------------------------------------

    @server.tool()
    async def list_provider_tools(client: str, provider: str) -> dict:
        """What this client's account with this provider can actually be asked to do.

        Every provider here runs its own MCP server with its own tools, and
        this returns them: the name, what it does, its argument schema, and
        whether the provider marks it read-only. Pair it with
        `call_provider_tool`, which invokes one.

        This is how you do work Munim has no verb for. There is no per-operation
        tool to look for, because modelling one provider's tools as another
        tool's parameters is a losing game: Cloudflare's `execute` takes
        JavaScript. Read this list, then call what it names.

        `read_only` is what the provider says about its own tool, and null means
        it said nothing. It is reported, not enforced; naming a client is what
        unlocks writing (D5).
        """
        from munim.remote.passthrough import known_providers, tools_for

        record = registry.get(client)
        try:
            # No `backend` here. That one is the API-key store; sessions are
            # opened against the vault, and handing the wrong one over is what
            # made this tool fail while the identical CLI command worked.
            tools = await tools_for(record.id, provider)
        except NeedsLogin:
            return {"client": record.name, "provider": provider,
                    "error": f"{provider} is not connected for this client, or the "
                             f"session expired.",
                    "fix": f'munim connect "{record.name}" {provider}'}
        except NoRemoteServer as unknown:
            return {"client": record.name, "provider": provider,
                    "error": str(unknown), "providers": known_providers()}
        return {"client": record.name, "provider": provider,
                "count": len(tools), "tools": tools}

    @server.tool()
    async def call_provider_tool(client: str, provider: str, tool: str,
                                 arguments: dict | None = None) -> dict:
        """Call one of a provider's own tools with one client's credentials.

        The write half of the passthrough. `tool` and `arguments` come from
        `list_provider_tools`; the arguments are forwarded to the provider
        untouched, so anything that server accepts is reachable.

        Munim's part is the credential: the call names a client and resolves
        that client's session alone, so one call touches exactly one account,
        and it is recorded in the run log with the tool and the arguments it
        was given. Read `launch_status` afterwards to see what was done.

        No language model is involved, which is the point. This works with
        `munim config ai off`.
        """
        from munim.remote.passthrough import (
            MissingArguments, UnknownTool, call_tool, known_providers)

        record = registry.get(client)
        log = RunLog(new_run_id(), runs)
        try:
            result = await call_tool(record.id, provider, tool, arguments,
                                     log=log)
        except NeedsLogin:
            return {"client": record.name, "provider": provider, "tool": tool,
                    "error": f"{provider} is not connected for this client, or the "
                             f"session expired.",
                    "fix": f'munim connect "{record.name}" {provider}'}
        except NoRemoteServer as unknown:
            return {"client": record.name, "provider": provider, "tool": tool,
                    "error": str(unknown), "providers": known_providers()}
        except UnknownTool as missing:
            return {"client": record.name, "provider": provider, "tool": tool,
                    "error": str(missing),
                    "fix": "list_provider_tools names what this provider has"}
        except MissingArguments as short:
            return {"client": record.name, "provider": provider, "tool": tool,
                    "error": str(short).replace("<client>", record.name),
                    "fix": "list_provider_tools gives each tool's schema"}
        # The client goes back out under the operator's name. Everything below
        # this line worked in ids, because that is what credentials are filed
        # under, and handing an id back would be Munim's bookkeeping leaking.
        return {**result, "client": record.name, "run_id": log.run_id}

    # ---- repair ----------------------------------------------------------

    @server.tool()
    async def plan_mail_setup(client: str, domain: str) -> dict:
        """What setting up email for this client's domain would change.

        Reads what is already published and returns every record with the
        action it would take: create, update, merge or unchanged. Changes no
        DNS. Pair it with `apply_mail_setup`, which needs the plan id.

        The one write here is creating the sending domain in the operator's own
        Resend account, because Resend does not publish the DKIM and SPF values
        a plan is made of until it exists. That adds nothing to anyone's DNS.
        """
        from munim.agent.mailplan import plan as make_plan

        record = registry.get(client)
        log = RunLog(new_run_id(), runs)
        made = await make_plan(container_for(record.name), record.domain or domain, log)
        return {**made.to_dict(), "run_id": log.run_id}

    @server.tool()
    async def apply_mail_setup(client: str, plan_id: str,
                               approved: bool = False) -> dict:
        """Carry out a plan from `plan_mail_setup`.

        `approved` is required when the plan would replace or combine a record
        somebody put there on purpose. Creating one that does not exist is not
        a judgement call; changing one that does is, and it is someone else's
        live mail. Show the plan to the operator, then call this.
        """
        from munim.agent.mailplan import NotApproved, apply as run_plan, load

        record = registry.get(client)
        made = load(plan_id)
        if made.client != record.id and made.client != record.name:
            # A plan carries the client it was made for. Applying it to another
            # is a write in the wrong account, which is what D5 exists to stop.
            raise ValueError(
                f"plan {plan_id} was made for a different client; make a new "
                f"one for {record.name!r}")

        log = RunLog(new_run_id(), runs)
        try:
            result = await run_plan(container_for(record.name), made, log,
                                    approved=approved)
        except NotApproved as exc:
            log.append(client=record.name, stage="mail", kind="awaiting_confirm",
                       human_text=str(exc), detail={"plan_id": plan_id})
            return {"applied": False, "needs_approval": True,
                    "why": str(exc), "plan_id": plan_id, "run_id": log.run_id}
        return {"applied": True, **result, "run_id": log.run_id}

    # ---- registry --------------------------------------------------------

    @server.tool()
    def add_client(name: str, domain: str = "") -> dict:
        """Register a client. Holds no credential - only a name and a domain."""
        registry.add(ClientRecord(name=name, domain=domain or None))
        return {"client": name, "domain": domain or None}

    @server.tool()
    async def client_status(client: str, check: bool = True) -> dict:
        """What is known about one client. Never returns a credential.

        `connected` is the live answer, for the same reason as `list_clients`.
        """
        from munim import health

        record = registry.get(client)
        stored = reachable(record.id, backend)
        available = [p for p in PROVIDERS if p in OAUTH_PROVIDERS]
        if not check:
            return {"client": record.name, "domain": record.domain,
                    "stored": stored, "checked": False,
                    "oauth_available": available}

        found = await asyncio.gather(
            *(health.check(record.id, record.name, p) for p in stored))
        return {**_shaped(record, stored, found),
                "oauth_available": available}

    # ---- write within ----------------------------------------------------

    @server.tool()
    def connect_provider(client: str, provider: str, credential: str) -> dict:
        """Connect one provider for one client using a credential you paste.

        Prefer `munim connect` for providers that publish an OAuth flow: it
        opens a browser, and no secret passes through the coding agent at all.
        This exists for providers that offer nothing else - Resend, for one.
        """
        # Unregistered fails before a secret is stored. Filed under the id, not
        # the name the caller used: reads go by id, and storing under a label
        # means the credential is invisible the moment the label changes.
        record = registry.get(client)
        TokenConnector(backend).connect(record.id, provider, credential)
        # The credential is deliberately not echoed.
        return {"client": record.name, "provider": provider, "connected": True,
                "oauth_available": provider in OAUTH_PROVIDERS}

    @server.tool()
    async def check(target: str, dkim_selector: str = "resend") -> dict:
        """Check a client or a domain. Registers it on first mention.

        `target` can be a client you have already added, a domain belonging to
        one, or a domain nobody has mentioned before - there is no setup step.
        What passed or failed is decided by live DNS, never by a model. What a
        failure *means* is the agent's part: it reads more records if it needs
        them and writes the explanation the owner gets. Open the control room
        to watch, or read the report afterwards.
        """
        record = resolve(target)
        client = record.name
        target_domain = record.domain or target

        # The agent, not a copy of its first half. This tool used to run the
        # checks itself and return the JSON, so `launch` had no callers and the
        # Strands agent never ran: the architecture diagram promised a
        # diagnosis step that no code path could reach.
        # Both names go down. `client` is the label, which is what the log, the
        # report and the control room show; `client_id` is what credentials are
        # filed under. Passing only the label meant the diagnosis agent looked
        # up sessions by a name the store does not key on and silently found
        # none, for every client, since the two were split.
        log, results = await launch(target_domain, client,
                                    client_id=record.id,
                                    dkim_selector=dkim_selector, runs_dir=runs)
        failures = [r for r in results if r.status == "fail"]
        report = write_report(log, domain=target_domain, business=client,
                              out_dir=reports)
        # The checks are the valuable half and they ran. Saying agents are off
        # here matters because the coding agent is where people look: doctor is
        # a terminal command, and somebody upgrading from 0.2.1 would otherwise
        # just notice the prose had quietly stopped appearing.
        from munim import settings
        agents = "on" if settings.ai().enabled else "off"
        return {
            "agents": agents,
            **({"fix": "munim config ai on for plain-English explanations"}
               if agents == "off" else {}),
            "client": client,
            "domain": target_domain,
            "run_id": log.run_id,
            "checked": sum(1 for r in results if r.status != "skip"),
            "not_applicable": sum(1 for r in results if r.status == "skip"),
            "failing": [{"check": r.check, "says": r.human_text} for r in failures],
            "report": f"http://127.0.0.1:8977/reports/{log.run_id}",
            "report_file": str(report),
        }

    @server.tool()
    def launch_status(run_id: str = "") -> dict:
        """Read a run without waiting on it.

        A launch polls DNS and can outlast a single tool call, so progress is
        read from the run log rather than held open.
        """
        known = all_runs(runs)
        if not known:
            return {"runs": [], "run": None}

        # A run id that does not exist used to read back as events=0,
        # done=false, which is exactly what a launch that has not started yet
        # looks like. An agent given that answer waits for a run that will
        # never begin, and a typo is indistinguishable from patience.
        if run_id and run_id not in known:
            return {"error": f"no run {run_id!r}. Known runs are listed here.",
                    "runs": known, "run": None}

        chosen = run_id or known[-1]
        log = RunLog(chosen, runs)
        events = list(log.read())
        return {
            "runs": known,
            "run": chosen,
            "events": len(events),
            "findings": [e.human_text for e in events if e.kind == "finding"],
            "done": any(e.kind == "run_done" for e in events),
        }

    return server


def main() -> None:
    # The MCP server is a subprocess spawned by the coding agent and does not
    # inherit the operator's shell, so the model key comes from .env here.
    load_env()
    build_server().run()


if __name__ == "__main__":
    main()
