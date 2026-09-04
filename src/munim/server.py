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
from munim.connect.oauth import PROVIDERS as OAUTH_PROVIDERS
from munim.connect.token import TokenConnector
from munim.container import Container, KeychainBackend, UnknownClient
from munim.env import load as load_env
from munim.registry import ClientRecord, Registry
from munim.report import write as write_report
from munim.runlog import RunLog, all_runs, new_run_id

# Tools that change a client's account. The test suite asserts each one takes an
# explicit `client`; adding a mutating tool without it fails the build.
MUTATING = {"connect_provider"}

# Tools that span more than one client's container. None of them may mutate, and
# the set is named here rather than inferred, so adding one is a decision
# somebody makes rather than a thing that happens.
CROSS_CLIENT = {"find_across_clients", "ask_across_clients"}

PROVIDERS = ("cloudflare", "vercel", "resend")


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
    def list_clients() -> list[dict]:
        """List every client container and which providers each has connected."""
        out = []
        for record in registry.clients():
            container = Container(record.name, backend)
            out.append({
                "client": record.name,
                "domain": record.domain,
                "connected": [p for p in PROVIDERS if container.has(p)],
            })
        return out

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
        from munim.remote.servers import SERVERS

        names = [r.name for r in registry.clients()]
        reachable = sorted({c for p in SERVERS for c in connected_clients(names, p)})
        answer = await ask(question, names)
        return {
            "question": question,
            "clients_read": reachable,
            "clients_registered": len(names),
            "answer": answer,
        }

    # ---- registry --------------------------------------------------------

    @server.tool()
    def add_client(name: str, domain: str = "") -> dict:
        """Register a client. Holds no credential - only a name and a domain."""
        registry.add(ClientRecord(name=name, domain=domain or None))
        return {"client": name, "domain": domain or None}

    @server.tool()
    def client_status(client: str) -> dict:
        """What is known about one client. Never returns a credential."""
        record = registry.get(client)
        container = container_for(client)
        return {
            "client": record.name,
            "domain": record.domain,
            "connected": [p for p in PROVIDERS if container.has(p)],
            "oauth_available": [p for p in PROVIDERS if p in OAUTH_PROVIDERS],
        }

    # ---- write within ----------------------------------------------------

    @server.tool()
    def connect_provider(client: str, provider: str, credential: str) -> dict:
        """Connect one provider for one client using a credential you paste.

        Prefer `munim connect` for providers that publish an OAuth flow: it
        opens a browser, and no secret passes through the coding agent at all.
        This exists for providers that offer nothing else - Resend, for one.
        """
        registry.get(client)  # unregistered client fails before a secret is stored
        TokenConnector(backend).connect(client, provider, credential)
        # The credential is deliberately not echoed.
        return {"client": client, "provider": provider, "connected": True,
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
        log, results = await launch(target_domain, client,
                                    dkim_selector=dkim_selector, runs_dir=runs)
        failures = [r for r in results if r.status == "fail"]
        report = write_report(log, domain=target_domain, business=client,
                              out_dir=reports)
        return {
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
