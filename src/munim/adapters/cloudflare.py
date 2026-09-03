"""Cloudflare DNS: read, and write.

Every mutation here is **read-before-write, upserted on (type, name)**. That is
not tidiness. Re-running a launch that failed halfway would otherwise add a
second SPF record beside the first, and two SPF records means receivers ignore
both - the exact fault this product exists to catch. A tool that causes the bug
it reports is worse than no tool.

Writes are also idempotent for a second reason: a launch polls DNS and can
outlive one tool call, so it must be safe to resume.
"""

from dataclasses import dataclass

from munim.container import Container
from munim.runlog import RunLog


class CloudflareError(RuntimeError):
    pass


@dataclass
class Record:
    id: str
    type: str
    name: str
    content: str
    ttl: int = 1
    proxied: bool = False

    @classmethod
    def from_api(cls, payload: dict) -> "Record":
        return cls(id=payload["id"], type=payload["type"], name=payload["name"],
                   content=payload["content"], ttl=payload.get("ttl", 1),
                   proxied=payload.get("proxied", False))


def _ok(payload: dict) -> dict:
    if not payload.get("success", False):
        errors = "; ".join(e.get("message", str(e)) for e in payload.get("errors", []))
        raise CloudflareError(errors or "Cloudflare rejected the request")
    return payload


class Cloudflare:
    """One client's Cloudflare account, reached through their container.

    The container vends an authenticated HTTP client, so no token ever becomes
    a value in this file (D6).
    """

    name = "cloudflare"

    def __init__(self, container: Container, log: RunLog | None = None) -> None:
        self._container = container
        self._log = log

    def _note(self, kind: str, text: str, **detail) -> None:
        if self._log:
            self._log.append(client=self._container.client, stage="dns",
                             kind=kind, human_text=text, detail=detail)

    async def zone_id(self, domain: str) -> str:
        async with self._container.http("cloudflare") as http:
            payload = _ok((await http.get("/zones", params={"name": domain})).json())
        zones = payload.get("result") or []
        if not zones:
            raise CloudflareError(
                f"{domain} is not a zone in this client's Cloudflare account. "
                "Either the nameservers are not delegated here, or the wrong "
                "client was named."
            )
        return zones[0]["id"]

    async def records(self, zone: str, *, type: str = "", name: str = "") -> list[Record]:
        params = {"per_page": 100}
        if type:
            params["type"] = type
        if name:
            params["name"] = name
        async with self._container.http("cloudflare") as http:
            payload = _ok((await http.get(f"/zones/{zone}/dns_records", params=params)).json())
        return [Record.from_api(r) for r in payload.get("result", [])]

    async def upsert(self, zone: str, *, type: str, name: str, content: str,
                     ttl: int = 1, proxied: bool = False) -> tuple[Record, str]:
        """Create or update. Returns the record and what happened.

        Read-before-write on (type, name): identical content is left alone, a
        differing single record is updated in place, and only a genuinely new
        (type, name) is created. Nothing is ever blindly appended.
        """
        existing = [r for r in await self.records(zone, type=type, name=name)]

        for record in existing:
            if record.content == content:
                self._note("observation", f"{type} record for {name} is already correct",
                           check="dns_write", action="unchanged", record=name)
                return record, "unchanged"

        body = {"type": type, "name": name, "content": content,
                "ttl": ttl, "proxied": proxied}

        if len(existing) == 1:
            async with self._container.http("cloudflare") as http:
                payload = _ok((await http.put(
                    f"/zones/{zone}/dns_records/{existing[0].id}", json=body)).json())
            self._note("mutation", f"Updated the {type} record for {name}",
                       check="dns_write", action="updated", record=name)
            return Record.from_api(payload["result"]), "updated"

        if len(existing) > 1:
            # Appending here is what creates the duplicate-SPF fault. Refuse and
            # let the caller decide, because merging is a judgement call.
            raise CloudflareError(
                f"{len(existing)} {type} records already exist for {name}. "
                "Adding another would leave several in place; decide how to "
                "combine them before writing."
            )

        async with self._container.http("cloudflare") as http:
            payload = _ok((await http.post(f"/zones/{zone}/dns_records", json=body)).json())
        self._note("mutation", f"Created the {type} record for {name}",
                   check="dns_write", action="created", record=name)
        return Record.from_api(payload["result"]), "created"

    async def merge_spf(self, zone: str, domain: str, merged: str) -> tuple[Record, str]:
        """Replace every SPF record with one. The only safe way to end up with
        a single policy when a domain already carries more than one."""
        spf = [r for r in await self.records(zone, type="TXT", name=domain)
               if r.content.lower().startswith("v=spf1")]
        if not spf:
            return await self.upsert(zone, type="TXT", name=domain, content=merged)

        async with self._container.http("cloudflare") as http:
            payload = _ok((await http.put(
                f"/zones/{zone}/dns_records/{spf[0].id}",
                json={"type": "TXT", "name": domain, "content": merged, "ttl": 1})).json())
            for extra in spf[1:]:
                _ok((await http.delete(f"/zones/{zone}/dns_records/{extra.id}")).json())

        self._note("mutation",
                   f"Merged {len(spf)} sender policies into one",
                   check="spf_single", action="merged", removed=len(spf) - 1)
        return Record.from_api(payload["result"]), "merged"
