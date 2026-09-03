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

from munim.checks.dns import run_all
from munim.connect.oauth import PROVIDERS as OAUTH_PROVIDERS
from munim.connect.token import TokenConnector
from munim.container import Container, KeychainBackend, UnknownClient
from munim.env import load as load_env
from munim.registry import ClientRecord, Registry
from munim.report import write as write_report
from munim.runlog import RunLog, all_runs, new_run_id

# Tools that change a client's account. The test suite asserts each one takes an
# explicit `client`; adding a mutating tool without it fails the build.
MUTATING = {"connect_provider", "check_domain"}

PROVIDERS = ("cloudflare", "vercel", "resend")


def build_server(backend=None, registry=None, runs_dir=None) -> FastMCP:
    server = FastMCP("munim")
    backend = backend or KeychainBackend()
    registry = registry or Registry(Path.home() / ".munim" / "registry.json")
    runs = Path(runs_dir) if runs_dir else None

    def container_for(client: str) -> Container:
        return Container.for_client(registry, client, backend)

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
        record = registry.get(client)
        if provider not in record.providers:
            record.providers.append(provider)
            registry.update(record)
        # The credential is deliberately not echoed.
        return {"client": client, "provider": provider, "connected": True,
                "oauth_available": provider in OAUTH_PROVIDERS}

    @server.tool()
    async def check_domain(client: str, domain: str = "",
                           dkim_selector: str = "resend") -> dict:
        """Run every check against one client's domain and write a run log.

        Deterministic: these results come from live DNS, not from a model.
        Open the control room to watch, or read the report afterwards.
        """
        record = registry.get(client)
        target = domain or record.domain
        if not target:
            raise ValueError(f"{client} has no domain registered; pass one")

        log = RunLog(new_run_id(), runs)
        log.append(client=client, stage="verify", kind="stage_start",
                   human_text=f"Checking {target}")
        results = await asyncio.to_thread(run_all, target, dkim_selector=dkim_selector)
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
                   human_text=f"Checked {target}.")
        report = write_report(log, domain=target, business=client)
        return {
            "run_id": log.run_id,
            "checked": sum(1 for r in results if r.status != "skip"),
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
