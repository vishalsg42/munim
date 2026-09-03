"""Resend: create a sending domain and hand back the records it needs.

This is one end of the handoff the whole project is about. Resend emits DKIM,
SPF and return-path records; they have to be written into Cloudflare, which is a
different company and a different login. Get the A record wrong and the site does
not load. Get these wrong and nothing breaks - the client's mail simply stops
arriving, and nobody notices for weeks.

Resend publishes no OAuth authorization endpoint, so it authenticates with an API
key. That is Resend offering nothing else, not a preference (see connect/oauth.py,
where it is deliberately absent from the provider table).
"""

from dataclasses import dataclass

from munim.container import Container
from munim.runlog import RunLog


class ResendError(RuntimeError):
    pass


@dataclass
class DnsRecord:
    """A record Resend needs published, in the shape Cloudflare wants it.

    Translating between the two vocabularies here is the point: Resend says
    `record: "SPF", type: "TXT", name: "send"`, Cloudflare wants a type, a fully
    qualified name and a content string. Doing it by hand is the copy-paste that
    goes wrong.
    """
    purpose: str            # SPF, DKIM, or the tracking/return-path record
    type: str               # TXT, CNAME, MX
    name: str               # as Resend gives it, often relative
    value: str
    priority: int | None = None
    status: str = "not_started"

    def fqdn(self, domain: str) -> str:
        """Resend returns names relative to the domain; Cloudflare wants them
        absolute. Getting this wrong publishes a record nobody can find."""
        if not self.name or self.name in ("@", domain):
            return domain
        if self.name.endswith(domain):
            return self.name
        return f"{self.name}.{domain}"

    @classmethod
    def from_api(cls, payload: dict) -> "DnsRecord":
        return cls(
            purpose=payload.get("record", "").upper(),
            type=payload.get("type", "TXT").upper(),
            name=payload.get("name", ""),
            value=payload.get("value", ""),
            priority=payload.get("priority"),
            status=payload.get("status", "not_started"),
        )


@dataclass
class Domain:
    id: str
    name: str
    status: str
    records: list[DnsRecord]

    @property
    def verified(self) -> bool:
        return self.status == "verified"


class Resend:
    name = "resend"

    def __init__(self, container: Container, log: RunLog | None = None) -> None:
        self._container = container
        self._log = log

    def _note(self, kind: str, text: str, **detail) -> None:
        if self._log:
            self._log.append(client=self._container.client, stage="mail",
                             kind=kind, human_text=text, detail=detail)

    @staticmethod
    def _ok(response) -> dict:
        if response.status_code >= 400:
            body = {}
            try:
                body = response.json()
            except Exception:
                pass
            raise ResendError(body.get("message") or response.text[:160]
                              or f"Resend returned {response.status_code}")
        return response.json()

    async def domains(self) -> list[Domain]:
        async with self._container.http("resend") as http:
            payload = self._ok(await http.get("/domains"))
        return [Domain(id=d["id"], name=d["name"], status=d.get("status", ""),
                       records=[DnsRecord.from_api(r) for r in d.get("records", [])])
                for d in payload.get("data", [])]

    async def find(self, domain: str) -> Domain | None:
        for existing in await self.domains():
            if existing.name.lower() == domain.lower():
                return existing
        return None

    async def ensure_domain(self, domain: str, region: str = "us-east-1") -> tuple[Domain, str]:
        """Create the sending domain, or return the one already there.

        Idempotent for the same reason every mutation here is: a launch that
        failed halfway and is re-run must not create a second sending domain and
        a second set of DKIM keys, which would leave the client with records that
        do not match the keys their mail is signed with.
        """
        existing = await self.find(domain)
        if existing is not None:
            self._note("observation", f"{domain} is already set up for sending",
                       check="resend_domain", action="unchanged")
            return existing, "unchanged"

        async with self._container.http("resend") as http:
            payload = self._ok(await http.post(
                "/domains", json={"name": domain, "region": region}))

        created = Domain(
            id=payload["id"], name=payload["name"],
            status=payload.get("status", "not_started"),
            records=[DnsRecord.from_api(r) for r in payload.get("records", [])],
        )
        self._note("mutation",
                   f"Created the sending domain and got {len(created.records)} "
                   "records to publish",
                   check="resend_domain", action="created",
                   records=[r.purpose for r in created.records])
        return created, "created"

    async def verify(self, domain_id: str) -> str:
        async with self._container.http("resend") as http:
            payload = self._ok(await http.post(f"/domains/{domain_id}/verify"))
        return payload.get("status", "unknown")

    @staticmethod
    def cloudflare_records(domain: Domain) -> list[dict]:
        """Translate Resend's records into what Cloudflare's API wants.

        This function is the handoff. Everything it does by rule is what an
        operator otherwise does by eye, between two browser tabs, once per
        client - and it is where the mistake that breaks nothing visible gets
        made.
        """
        out = []
        for record in domain.records:
            entry = {
                "type": record.type,
                "name": record.fqdn(domain.name),
                "content": record.value,
                "purpose": record.purpose,
            }
            if record.priority is not None:
                entry["priority"] = record.priority
            out.append(entry)
        return out
