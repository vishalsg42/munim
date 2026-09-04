"""Every provider offered must be reachable by some route.

ARCHITECTURE.md states the rule: "A capability that is not implemented is
absent from the tool list rather than present and inert." Supabase was cut
during planning and left behind in three places that still offer it. It has no
MCP server, no entry in Container._AUTH and no adapter, so a credential stored
for it cannot be used by any code path, and `doctor` told every user to go and
register a Supabase OAuth application to reach it.

That is the exact shape of stub the project says it does not ship, and it was
visible in `doctor` output on a clean install.
"""

import re
import subprocess

from munim.connect.oauth import PROVIDERS as OAUTH_PROVIDERS
from munim.container import _AUTH
from munim.remote.servers import SERVERS


def _usable(provider: str) -> bool:
    """Two honest routes in: the provider's own MCP server, or a pasted key
    this codebase knows how to call with."""
    return provider in SERVERS or provider in _AUTH


def test_connect_only_offers_providers_that_can_work():
    """`munim connect <client> supabase` was accepted and led nowhere."""
    help_text = subprocess.run(
        ["munim", "connect", "--help"], capture_output=True, text=True).stdout
    offered = set(re.search(r"\{([a-z,]+)\}", help_text).group(1).split(","))

    dead = {p for p in offered if not _usable(p)}
    assert not dead, f"connect offers providers nothing can use: {sorted(dead)}"


def test_doctor_does_not_send_people_after_a_dead_provider():
    """It printed a fix telling the operator to register an OAuth application
    for a provider with no way to use the result."""
    dead = {p for p in OAUTH_PROVIDERS if not _usable(p)}
    assert not dead, (
        f"doctor reports a login route for providers nothing can use: "
        f"{sorted(dead)}"
    )


def test_every_provider_with_an_auth_profile_is_offered():
    """The other direction. A provider this codebase can call with, that
    `connect` does not offer, is a capability nobody can reach."""
    help_text = subprocess.run(
        ["munim", "connect", "--help"], capture_output=True, text=True).stdout
    offered = set(re.search(r"\{([a-z,]+)\}", help_text).group(1).split(","))

    missing = set(_AUTH) - offered
    assert not missing, f"has an auth profile but is not offered: {sorted(missing)}"
