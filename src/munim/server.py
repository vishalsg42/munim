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
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from munim.agent.launch import launch
from munim.checks.dns import run_all_async, run_reachability_async
from munim.connect.oauth import PROVIDERS as OAUTH_PROVIDERS
from munim.connected import connections, reachable
from munim.connect.token import TokenConnector
from munim.container import Container, KeychainBackend, UnknownClient
from munim.env import load as load_env
from munim.registry import ClientRecord, Registry
from munim.remote.session import NeedsLogin, NoRemoteServer
from munim.report import write as write_report
from munim.room.link import links as room_links
from munim.runlog import RunLog, all_runs, new_run_id
from munim import words

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

# Every tool argument says what it is for. FastMCP builds the input schema from
# the signature, and it takes per-argument text from `Field` rather than from
# the docstring, so without these a coding agent sees six bare names and a type
# for `call_provider_api` and has to guess. Sixteen tools and thirty-eight
# arguments had none.
#
# `Says` rather than `Field` directly, and it is not only for readability.
# `Field`'s first positional argument is the **default**, so `Field("what this
# is for")` silently makes a required argument optional with a sentence as its
# value. That was written here first and caught by reading the generated schema
# rather than the code, which is the only place it shows.
def Says(text: str):
    """What this argument is for, in the schema the model actually sees."""
    return Field(description=text)


# Two arguments recur, and an argument that means the same thing should read
# the same way wherever it appears.
PROVIDER = Says("The provider to use, for example cloudflare, vercel or "
                "resend. Only what this client is actually connected to is "
                "reachable.")


def _shaped(record, stored: list[str], found, kinds=None) -> dict:
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
                 reports_dir=None, keyring=None) -> FastMCP:
    server = FastMCP("munim")
    backend = backend or KeychainBackend()
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")
    runs = Path(runs_dir) if runs_dir else None
    # A caller that redirects the run log means it away from the real home;
    # leaving reports behind wrote test output into ~/.munim/reports for every
    # check a test ran.
    reports = Path(reports_dir) if reports_dir else None

    def container_for(client: str) -> Container:
        # Both stores. `backend` holds pasted API keys and `keyring` holds MCP
        # sessions, and a container needs to know about the second only to
        # explain a refusal about the first. Threaded rather than defaulted so
        # a test watches the same store the server does.
        return Container.for_client(registry, client, backend, keyring=keyring)

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

    # `connected` means the session opens right now, not that a credential is
    # filed. Reporting the second as the first is how two dead sessions read as
    # connected for a day: nothing local can tell them apart, because OAuth
    # grants a token and then says nothing more about it.
    @server.tool()
    async def list_clients(
        check: Annotated[bool, Says("Ask each provider whether the session still opens. False reports only what is stored, which is instant.")] = True,
    ) -> list[dict]:
        """List every client and what each one can actually reach.

        Returns one row per client with their domain, `stored` (every provider
        with a credential filed), `api_key` and `mcp_session` saying which store
        each came from, and `connected`, `needs_login` and `unreachable` from
        asking each provider live. Pass `check=false` to skip the live probes and
        report only what is stored, which is instant.

        Use `client_status` for one client in the same shape.
        """
        from munim import health

        records = registry.clients()
        stored = {r.name: reachable(r.id, backend, keyring) for r in records}
        by_kind = {}
        for r in records:
            keys, sessions = connections(r.id, backend, keyring)
            by_kind[r.name] = {"api_key": keys, "mcp_session": sessions}
        if not check:
            return [{"client": r.name, "domain": r.domain,
                     "stored": stored[r.name], **by_kind[r.name],
                     "checked": False}
                    for r in records]

        found = await health.check_all_async(registry, backend)
        return [_shaped(r, stored[r.name], found, by_kind[r.name])
                for r in records]

    @server.tool()
    async def find_across_clients(
        need: Annotated[str, Says("What to look for, as one of the catalogue check names, for example spf_single or dmarc_policy.")],
    ) -> list[dict]:
        """Run one named check across every client at once.

        Returns one row per client with that check's result and the evidence
        behind it. Read-only, and it never writes.

        `need` is a check name from the catalogue, such as `spf_single`,
        `dmarc_policy` or `dkim_present`. Use `audit_all_clients` to run the whole
        catalogue instead of one check, and `ask_across_clients` when the question
        is open-ended rather than one of these.
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
    async def ask_across_clients(
        question: Annotated[str, Says("A question in plain English about every client at once, for example which of my clients has no DMARC policy.")],
    ) -> dict:
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
        # A log, like every other agent-bearing tool has. Without one this
        # answer could not be looked up afterwards and the control room had
        # nothing to render.
        log = RunLog(new_run_id(), runs)
        answer, discarded = await ask(question, records, log=log)

        # Computed here, never asked of the model. A model under-reporting what
        # it could not check is the exact reason a caller wants this field, so
        # putting it in the schema would make the answer its own auditor.
        answered = {f.client for f in answer.findings}
        shaped = {
            "question": question,
            "clients_read": reachable,
            "clients_registered": len(records),
            "findings": [f.model_dump() for f in answer.findings],
            "answer": answer.summary,
            "could_not_check": sorted(set(reachable) - answered),
            "run_id": log.run_id,
        }
        if discarded:
            # Surfaced, not swallowed: the agent named an account it never read.
            shaped["discarded"] = [f.model_dump() for f in discarded]
        return shaped

    # Silent when everything passes, because the failures this catches break
    # nothing visible and therefore survive for weeks. Nobody runs thirteen
    # checks by hand across a dozen clients.
    @server.tool()
    async def audit_all_clients(
        dkim_selector: Annotated[str, Says("The DKIM selector to look for. Change it only if the client sends through something other than Resend.")] = "resend",
    ) -> dict:
        """Run the whole check catalogue against every client, reporting only what
        needs attention.

        Returns one entry per client that has something wrong, naming the client
        beside each failing check, plus a `run_id`. Clients that pass are omitted
        entirely, so an empty result means every client is healthy.

        Read-only across every client, and it never writes. Use `check` for one
        client with a report, and `find_across_clients` when you want one
        specific check across everybody rather than the whole catalogue.
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
                               f"{words.things(len(needs_attention))} need attention "
                               f"across {words.count(len(records) - len(clean), 'client')}"))

        return {
            "checked": len(records),
            "clean": clean,
            "needs_attention": needs_attention,
            "unreachable": unreachable,
            "run_id": log.run_id,
            **room_links(log.run_id),
        }

    # The other half of read across, write within (D5). Naming the client is
    # what unlocks writing, and the isolation is structural rather than a rule:
    # the agent holds one container's sessions and no others.
    @server.tool()
    async def work_on_client(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        request: Annotated[str, Says("What to do, in plain English, for example add a TXT record for domain verification. The agent uses only this client's provider tools.")],
    ) -> dict:
        """Carry out a request inside one named client's provider accounts.

        Returns what was done in the agent's own words, and which providers it
        had available. Every change is written to the run log as it happens, so
        `launch_status` reads it back.

        The agent is built with only this client's sessions, so a request needing
        a second account has nothing to reach with. Use `ask_across_clients` to
        read across every client instead, and `fix` when the job is repairing DNS
        or mail, which is deterministic and stops for a person before replacing a
        record somebody published.
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

    # There is no per-operation tool to look for, because modelling one
    # provider's tools as another tool's parameters is a losing game:
    # Cloudflare's `execute` takes JavaScript.
    @server.tool()
    async def list_provider_tools(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        provider: Annotated[str, PROVIDER],
        names_only: Annotated[bool, Says("Return names and read-only flags only. Resend publishes 121KB of schemas and 2KB of names.")] = False,
        matching: Annotated[str, Says("Only tools whose name, description or argument schema contains this. Searching the schema is how you find every tool that takes a teamId.")] = "",
    ) -> dict:
        """List the tools this client's account with this provider actually
        publishes.

        Returns each tool's name, description, argument schema, and whether the
        provider marks it read-only. `read_only` is what the provider says about
        its own tool; null means it said nothing, and it is reported rather than
        enforced.

        Read this before `call_provider_tool`, which invokes one of them. Start
        with `names_only`, which returns names and read-only flags alone: for
        Resend that is 2KB against 122KB, and the full listing has exceeded a
        caller's response limit outright. `matching` filters on the name, the
        description and the argument schema, so "which tools take a teamId" is
        answerable.
        """
        from munim.remote.passthrough import known_providers, narrow, tools_for

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
        shown = narrow(tools, names_only=names_only, matching=matching)
        listed = {"client": record.name, "provider": provider,
                  "count": len(shown), "tools": shown}
        if len(shown) != len(tools):
            # So a filtered listing cannot be mistaken for the whole surface.
            listed["of"] = len(tools)
        return listed

    @server.tool()
    async def call_provider_tool(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        provider: Annotated[str, PROVIDER],
        tool: Annotated[str, Says("The provider tool to call, named exactly as list_provider_tools reported it.")],
        arguments: Annotated[dict | None, Says("The arguments that tool declares, as an object. Read its inputSchema first rather than guessing.")] = None,
    ) -> dict:
        """Call one of a provider's own tools with one client's credentials.

        Returns the provider's own result, plus a `run_id`. Arguments are
        forwarded untouched, so anything that server accepts is reachable. Take
        `tool` and `arguments` from `list_provider_tools` rather than guessing.

        One call resolves one named client's session and touches no other
        account, and the tool and its arguments go to the run log; read it back
        with `launch_status`. No model is involved, so this works with agents
        off.
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

    # The path is validated before the request is built and the built request's
    # host is compared with the provider's before anything is sent, because
    # httpx's `base_url` does not contain an absolute URL: it would leave with
    # the client's bearer token attached (D33).
    @server.tool()
    async def call_provider_api(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        provider: Annotated[str, Says("cloudflare, vercel or resend. Only these three have a known REST base URL and header shape.")],
        path: Annotated[str, Says("A path beginning with one slash, for example /v9/projects. Never a full URL: an absolute URL is refused before the request is built, because it would send this client's credential to another host.")],
        method: Annotated[str, Says("GET, POST, PATCH, PUT or DELETE. Every call is recorded as a mutation whatever the method, because an HTTP verb is a convention rather than a guarantee.")] = "GET",
        query: Annotated[dict | None, Says("Query string parameters, as an object.")] = None,
        body: Annotated[dict | None, Says("JSON request body, as an object.")] = None,
    ) -> dict:
        """Make one HTTP call to a provider's own REST API with one client's
        credential.

        Returns the status and the parsed body, plus a `run_id`. Every call is
        recorded as a mutation whatever the method, because an HTTP verb is a
        convention rather than a guarantee, and the response body is never written
        to the log.

        Use this only when the provider's MCP server publishes no tool for the
        job: `list_provider_tools` first, `call_provider_tool` if it names one.
        Vercel publishes no environment-variable write and no project-domain
        attach, which is what this exists for. Works for cloudflare, vercel and
        resend, the three whose REST shape Munim knows.
        """
        from munim.container import UnknownCredential, UnsupportedProvider
        from munim.remote.rawcall import UnsafePath, call as raw, providers
        from munim.remote.session import freshen

        record = registry.get(client)
        log = RunLog(new_run_id(), runs)
        # Before the container reads anything: where a REST call rides the MCP
        # session's token, only an async session can renew it, and `Container`
        # is synchronous.
        await freshen(record.id, provider)
        try:
            result = await raw(container_for(record.name), provider, path,
                               method=method, query=query, body=body, log=log)
        except UnsupportedProvider as unknown:
            return {"client": record.name, "provider": provider,
                    "error": str(unknown), "providers": providers()}
        except UnsafePath as unsafe:
            return {"client": record.name, "provider": provider,
                    "error": str(unsafe),
                    "fix": "pass a path beginning with '/', not a URL"}
        except UnknownCredential as missing:
            return {"client": record.name, "provider": provider,
                    "error": str(missing),
                    "fix": f'munim connect "{record.name}" {provider} --token'}
        except ValueError as bad:
            return {"client": record.name, "provider": provider,
                    "error": str(bad)}
        return {**result, "client": record.name, "run_id": log.run_id}

    # ---- repair ----------------------------------------------------------

    @server.tool()
    async def plan_mail_setup(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        domain: Annotated[str, Says("The domain to send mail from, for example acme.example. Uses the client's registered domain when omitted.")],
    ) -> dict:
        """Work out what setting up email for this client's domain would change.

        Returns a `plan_id` and every record that would be created or replaced,
        each with its current published value beside the proposed one, and a count
        of how many need a person to approve them. Touches no client DNS.

        One honest note: planning creates the sending domain in your own Resend
        account, because Resend publishes no DKIM values until the domain exists.
        Pass the `plan_id` to `apply_mail_setup` to carry it out, or use `fix`,
        which plans and applies in one call and stops for approval in between.
        """
        from munim.agent.mailplan import plan as make_plan
        from munim.container import UnknownCredential

        record = registry.get(client)
        log = RunLog(new_run_id(), runs)
        try:
            made = await make_plan(container_for(record.name),
                                   record.domain or domain, log)
        except UnknownCredential as missing:
            # Returned rather than raised, like every other refusal here that
            # has a next step. A caller reading "Error executing tool" has to
            # decide whether something broke; a `fix` field says it did not.
            return {"client": record.name, "domain": record.domain or domain,
                    "error": str(missing),
                    "fix": f'munim connect "{record.name}" resend --token'}
        return {**made.to_dict(), "run_id": log.run_id}

    @server.tool()
    async def apply_mail_setup(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        plan_id: Annotated[str, Says("The plan_id that plan_mail_setup returned. A plan made for a different client is refused.")],
        approved: Annotated[bool, Says("Required only when the plan would replace a record that already exists. That is the client's decision, so show them the plan before setting this.")] = False,
    ) -> dict:
        """Carry out a plan from `plan_mail_setup`.

        Returns what was published and what was left unchanged, plus a `run_id`.
        When approval is needed and not given it returns `needs_approval` and
        changes nothing, so calling it again with `approved=true` is safe.

        `approved` is required only for records that already exist. Creating one
        that is absent is not a judgement call; replacing one somebody published
        is theirs to make, so show them the plan first.
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
    def add_client(
        name: Annotated[str, Says("What you call this client, for example Acme Ltd. Used in tool names, so two clients cannot differ only by punctuation.")],
        domain: Annotated[str, Says("Their primary domain, if you know it. It can be added later by naming it in a check.")] = "",
    ) -> dict:
        """Register a client by name. Holds no credential, only a name and a domain.

        Returns the client's id, name and domain.

        Use this to write a client down before connecting anything. You do not
        need it first: naming a domain in `check` or `fix` registers it on the
        spot. Connecting a provider is a separate step, `connect_provider`.
        """
        registry.add(ClientRecord(name=name, domain=domain or None))
        return {"client": name, "domain": domain or None}

    # `connected` is asked live rather than inferred, for the same reason as
    # `list_clients`: a token on disk looks identical whether or not the
    # provider will still accept it.
    @server.tool()
    async def client_status(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        check: Annotated[bool, Says("Ask each provider whether the session still opens, rather than only reporting what is stored.")] = True,
    ) -> dict:
        """What is known about one client: their domain, what is stored, and
        what actually opens right now.

        Returns the client's name and domain; `stored`, every provider with a
        credential filed; `api_key` and `mcp_session`, saying which of the two
        stores each one came from; and `connected`, `needs_login` and
        `unreachable`, from asking each provider live. Never includes a
        credential value.

        Use this for one client and `list_clients` for all of them. The two
        stores are not interchangeable: `api_key` is what the mail tools call
        REST APIs with, `mcp_session` is what a provider's own tools run on, and
        a client can have one without the other.
        """
        from munim import health

        record = registry.get(client)
        stored = reachable(record.id, backend, keyring)
        keys, sessions = connections(record.id, backend, keyring)
        kinds = {"api_key": keys, "mcp_session": sessions}
        available = [p for p in PROVIDERS if p in OAUTH_PROVIDERS]
        if not check:
            return {"client": record.name, "domain": record.domain,
                    "stored": stored, **kinds, "checked": False,
                    "oauth_available": available}

        found = await asyncio.gather(
            *(health.check(record.id, record.name, p) for p in stored))
        return {**_shaped(record, stored, found, kinds),
                "oauth_available": available}

    # ---- write within ----------------------------------------------------

    @server.tool()
    def connect_provider(
        client: Annotated[str, Says("The client to act on, by the name you registered them under. A write resolves this one client's credentials and no other.")],
        provider: Annotated[str, PROVIDER],
        credential: Annotated[str, Says("The API key or token, pasted. It is stored and never returned by any tool.")],
    ) -> dict:
        """Store a pasted API key for one client and one provider.

        Returns which provider was connected, never the credential itself.

        Use this only for providers with no browser login, or when a REST API key
        is needed alongside a session: the mail tools call REST APIs and a browser
        session is a different credential. `munim connect` at the terminal does
        the browser login.
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
    async def check(
        target: Annotated[str, Says("A client name, or a bare domain. A domain nobody has mentioned before is registered as a new client, because a DNS lookup is public and reveals nothing.")],
        dkim_selector: Annotated[str, Says("The DKIM selector to look for. Change it only if the client sends through something other than Resend.")] = "resend",
    ) -> dict:
        """Run the deterministic check catalogue against one client or one domain.

        Returns the failing checks with an owner-facing sentence for each, counts
        of what was checked and skipped, a `run_id`, and `report_file`, where
        the report was written. `watch` and `report` are control room URLs and
        appear only while it is running. DNS
        decides pass or fail, never a model; with agents on, a model adds the
        explanation and nothing else.

        `target` may be a client name, a domain belonging to one, or a domain
        nobody has mentioned before, which registers it: there is no setup step.
        Use `audit_all_clients` to run the same catalogue across every client at
        once, and `fix` to repair what it finds rather than only reporting it.
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
            "report_file": str(report),
            **room_links(log.run_id),
        }

    @server.tool()
    async def fix(
        target: Annotated[str, Says("A client name, or a bare domain. The same resolution check uses.")],
        dkim_selector: Annotated[str, Says("The DKIM selector to look for. Change it only if the client sends through something other than Resend.")] = "resend",
    ) -> dict:
        """Check a client's domain, then repair what can be repaired safely.

        `check` explains what is wrong. This acts on it. The same thirteen
        deterministic checks run first and are still never decided by a model;
        what a model decides is which repair to reach for, out of a set of tools
        that cannot do anything else.

        Anything that would replace a record somebody already published stops
        and waits for a person. Approve it in the control room, or call
        `apply_mail_setup` with `approved=true`. Creating a record that is
        absent is not a judgement call and does not stop.

        `report_file` is always written. `watch` and `report` are control room
        URLs and appear only while it is running; `munim approve` answers
        without it.

        With agents off the checks still run and their findings still stand,
        exactly as `check` degrades: only the repair needs a model.
        """
        from munim.agent.graph import fix as run_fix
        from munim.agent.launch import _connected_toolsets

        record = resolve(target)
        target_domain = record.domain or target
        log = RunLog(new_run_id(), runs)

        try:
            container = container_for(record.name)
        except Exception:
            # A client with nothing stored is a reason to refuse the repair,
            # not a reason to skip the checks. The graph reports why.
            container = None

        toolsets = _connected_toolsets(record.id, record.name, log)
        shaped = await run_fix(target_domain, record.name,
                               client_id=record.id, container=container,
                               log=log, dkim_selector=dkim_selector,
                               toolsets=toolsets, keyring=keyring)
        report = write_report(log, domain=target_domain, business=record.name,
                              out_dir=reports)
        return {**shaped,
                "report_file": str(report),
                **room_links(log.run_id)}

    @server.tool()
    def launch_status(
        run_id: Annotated[str, Says("The run to read, as returned by check, fix or call_provider_tool. The newest run when omitted.")] = "",
    ) -> dict:
        """Read a run back without waiting on it.

        Returns that run's events in order: what was checked, what changed, what
        is waiting on a person. Defaults to the newest run.

        A check or a repair can outlast a single tool call, so progress is read
        from the run log rather than held open.
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
