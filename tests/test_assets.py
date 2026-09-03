"""The Asset model and the adapter contract.

The point of facets: a check is written once against a facet, not once per
provider. "Anything expiring inside 30 days" must catch a Cloudflare domain,
an ACM certificate and a Vercel cert with one rule (spec section 5).
"""

from datetime import datetime, timedelta, timezone

import pytest

from mcpc.assets import Asset, Expiry, Exposure, Freshness, expiring_within


def _at(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_an_asset_needs_no_facets():
    asset = Asset(client="acme", provider="vercel", kind="project", identifier="site")
    assert asset.expiry is None
    assert asset.exposure is None


def test_one_expiry_rule_catches_every_provider():
    assets = [
        Asset(client="acme", provider="cloudflare", kind="domain",
              identifier="acme.example", expiry=Expiry(expires_at=_at(9))),
        Asset(client="acme", provider="vercel", kind="certificate",
              identifier="www.acme.example", expiry=Expiry(expires_at=_at(3))),
        Asset(client="acme", provider="godaddy", kind="registration",
              identifier="acme.example", expiry=Expiry(expires_at=_at(400))),
        Asset(client="acme", provider="vercel", kind="project",
              identifier="site"),  # no expiry facet at all
    ]
    soon = expiring_within(assets, days=30)
    assert {a.provider for a in soon} == {"cloudflare", "vercel"}


def test_expiring_results_are_ordered_most_urgent_first():
    assets = [
        Asset(client="a", provider="cloudflare", kind="domain", identifier="later",
              expiry=Expiry(expires_at=_at(20))),
        Asset(client="a", provider="cloudflare", kind="domain", identifier="sooner",
              expiry=Expiry(expires_at=_at(2))),
    ]
    assert [a.identifier for a in expiring_within(assets, days=30)] == ["sooner", "later"]


def test_an_already_expired_asset_is_included():
    assets = [Asset(client="a", provider="cloudflare", kind="domain",
                    identifier="gone", expiry=Expiry(expires_at=_at(-5)))]
    assert len(expiring_within(assets, days=30)) == 1


def test_dns_records_carry_their_value_in_attributes():
    """SPF and DKIM checks read record values, so they must survive the model."""
    record = Asset(
        client="acme", provider="cloudflare", kind="dns_record",
        identifier="acme.example",
        attributes={"type": "TXT", "name": "@", "value": "v=spf1 include:amazonses.com ~all"},
    )
    assert record.attributes["value"].startswith("v=spf1")


def test_an_asset_cannot_carry_a_credential():
    with pytest.raises(Exception):
        Asset(client="a", provider="vercel", kind="project", identifier="x",
              token="sk-secret")


def test_facets_are_independent():
    asset = Asset(
        client="a", provider="aws", kind="bucket", identifier="invoices",
        exposure=Exposure(public=True, detail="serves invoices to anyone"),
        freshness=Freshness(last_changed=_at(-2), state="READY"),
    )
    assert asset.exposure.public is True
    assert asset.expiry is None
