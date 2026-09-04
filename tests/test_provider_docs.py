"""Every provider has a page, and every page names a real provider.

Adding a provider is a row in a table, which is the point of the design and also
how a provider ends up shipped with nothing telling anyone how to use it. Gmail
sat in that table for weeks needing ten minutes of Google Cloud setup that was
written down nowhere.
"""

import pathlib
import re

from munim.remote.servers import SERVERS

DOCS = pathlib.Path("docs/providers")


def test_every_provider_has_a_page():
    missing = [name for name in SERVERS if not (DOCS / f"{name}.md").exists()]
    assert not missing, f"providers with no page: {missing}"


def test_every_page_names_a_provider_that_exists():
    """A page for a provider that was removed is worse than no page: it is
    instructions for something that cannot be connected."""
    pages = {p.stem for p in DOCS.glob("*.md")} - {"README"}
    orphans = sorted(pages - set(SERVERS))
    assert not orphans, f"pages for providers not in the table: {orphans}"


def test_the_index_links_every_page():
    index = (DOCS / "README.md").read_text()
    linked = set(re.findall(r"\(([a-z]+)\.md\)", index))
    missing = sorted(set(SERVERS) - linked)
    assert not missing, f"providers missing from the index: {missing}"


def test_providers_needing_setup_say_so_on_their_page():
    """The whole reason these pages exist. A provider that cannot register a
    client on demand needs one registered by hand, and the page has to say it
    rather than leaving somebody to discover it at a failed connect."""
    for name, server in SERVERS.items():
        if server.ready:
            continue
        page = (DOCS / f"{name}.md").read_text().lower()
        assert "registers a client on demand: **no**" in page, (
            f"{name} needs setup and its page does not say so")


def test_a_page_that_claims_a_live_connection_is_in_the_index_as_one():
    """Keeps "connected live" and "probed" from drifting apart, since the
    difference is exactly what a reader is trying to find out."""
    index = (DOCS / "README.md").read_text()
    for name in SERVERS:
        page = (DOCS / f"{name}.md").read_text()
        claims_live = "Not yet connected live" not in page and "probed" not in page.lower()
        listed_live = f"[{name.capitalize()}]({name}.md) | ✅ connected live" in index
        if listed_live:
            assert claims_live, f"{name} is listed as live but its page hedges"
