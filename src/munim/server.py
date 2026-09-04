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

from munim.checks.dns import run_all, run_reachability
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

PROVIDERS = ("cloudflare", "vercel", "resend")


def build_server(backend=None, registry=None, runs_dir=None) -> FastMCP:
    server = FastMCP("munim")
    backend = backend or KeychainBackend()
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")
    runs = Path(runs_dir) if runs_dir else None

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
    def find_across_clients(need: str) -> list[dict]:
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

        hits = []
        for record in registry.clients():
            if not record.domain:
                continue
            for result in run_all(record.domain):
                if result.check in wanted and result.status == "fail":
                    hits.append({"client": record.name, "domain": record.domain,
                                 "check": result.check, "says": result.human_text})
        return hits

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
        Results come from live DNS, not from a model. Open the control room to
        watch, or read the report afterwards.
        """
        record = resolve(target)
        client = record.name
        target_domain = record.domain or target

        log = RunLog(new_run_id(), runs)
        log.append(client=client, stage="verify", kind="stage_start",
                   human_text=f"Checking {target_domain}")
        results = await asyncio.to_thread(run_all, target_domain,
                                          dkim_selector=dkim_selector)
        results += await asyncio.to_thread(run_reachability, target_domain)
        for r in results:
            if r.status == "skip":
                continue
            log.append(client=client, stage="verify",
                       kind="observation" if r.status == "pass" else "finding",
                       human_text=r.human_text or r.operator_text,
                       detail={"check": r.check, "operator_text": r.operator_text,
                               "evidence": r.evidence, "resolver": r.resolver})
        failures = [r for r in results if r.status == "fail"]
        log.append(client=client, stage="verify", kind="run_done",
                   human_text=f"Checked {target_domain}.")
        report = write_report(log, domain=target_domain, business=client)
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
