"""What an adapter returns, and the facets checks are written against.

Every provider, however different, is enumerating the same handful of things a
business depends on. An adapter's only job is to return Assets; it never
interprets. This is what makes many providers affordable: a check is written
once against a facet, not once per provider (spec section 5).
"""

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    """Forbid unknown fields everywhere, so a credential cannot be smuggled
    into an Asset and end up in a log or a model's context (D6)."""

    model_config = ConfigDict(extra="forbid")


class Expiry(_Strict):
    """Domains, certificates, tokens, licences."""

    expires_at: datetime
    auto_renew: bool | None = None


class Reachability(_Strict):
    """Sites, endpoints, mailboxes."""

    responds: bool
    status_code: int | None = None
    detail: str | None = None


class Exposure(_Strict):
    """Buckets, DNS records, environment variables."""

    public: bool
    detail: str | None = None


class Permission(_Strict):
    """IAM principals, team members, admins."""

    principals: list[str] = []


class Freshness(_Strict):
    """Deploys, DNS edits, content."""

    last_changed: datetime
    state: str | None = None


class Asset(_Strict):
    client: str
    provider: str
    kind: str
    identifier: str

    expiry: Expiry | None = None
    reachability: Reachability | None = None
    exposure: Exposure | None = None
    permission: Permission | None = None
    freshness: Freshness | None = None

    # Kind-specific detail that no facet generalises - a DNS record's
    # type/name/value, a deployment's URL. Values only, never secrets.
    attributes: dict[str, str] = {}


@runtime_checkable
class Adapter(Protocol):
    """The only thing you write per provider.

    Enumeration is deterministic and does no interpretation. Only judgement is
    model work (docs/DECISIONS.md D7).
    """

    name: str

    def enumerate(self, container) -> list[Asset]: ...


def expiring_within(assets: list[Asset], days: int) -> list[Asset]:
    """Every asset with an expiry facet falling due inside `days`.

    One rule, every provider. Already-expired assets are included - they are
    the most urgent, not the least.
    """
    now = datetime.now(timezone.utc)
    matched = [
        a
        for a in assets
        if a.expiry is not None
        and (a.expiry.expires_at - now).total_seconds() <= days * 86400
    ]
    return sorted(matched, key=lambda a: a.expiry.expires_at)
