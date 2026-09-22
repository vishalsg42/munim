"""A provider discovered on one machine, on its way to a pull request.

`munim servers add` works out how any MCP server authenticates and writes the
answer to `~/.munim/servers.json`. It stayed there. Nobody else benefited and
the next person repeated the discovery, which is a strange place for a project
whose whole design is that a provider is a row rather than code.

Two things have to hold for the row to be worth printing. It has to go back in
as the same row, or the contributor is pasting something that only looks right.
And it must never carry a credential, because the destination is a public pull
request.
"""

import json

import pytest

from munim.cli import _as_source, export_server
from munim.remote.servers import (SERVERS, CredentialInUrl, RemoteServer,
                                  shareable)


# ---- the row survives the trip ------------------------------------------

def test_every_built_in_row_exports_to_source_that_rebuilds_it(capsys):
    """The strongest form of the claim. Not "the fields are present" but "the
    block you paste reconstructs the row you exported", checked against all
    eleven rather than against one hand-written example."""
    for name in SERVERS:
        export_server(name)
        printed = capsys.readouterr().out
        # The block is a dict entry: `"name": RemoteServer(...),`
        built = eval(f"dict({{{printed.rstrip().rstrip(',')}}})")  # noqa: S307
        assert built[name] == SERVERS[name], f"{name} did not survive export"


def test_an_exported_row_reads_back_through_the_user_file(tmp_path, monkeypatch):
    """`shareable` is `remember`'s format on purpose, so the file Munim writes
    and the row a contributor pastes cannot drift into two shapes."""
    from munim.remote import servers

    monkeypatch.setattr(servers, "USER_SERVERS", tmp_path / "servers.json")
    mine = RemoteServer(provider="acme", url="https://mcp.acme.test/mcp",
                        public_client=True, probe_tool="ping",
                        rest_takes_session=True, scopes=("a", "b"),
                        header="X-Key", note="probed 2026-09-22")

    (tmp_path / "servers.json").write_text(
        json.dumps({"acme": shareable(mine)}))

    assert servers._user_servers()["acme"] == mine


def test_the_note_is_not_reworded_by_being_wrapped():
    """The note is the measurement, and wrapping it is presentation. An earlier
    version split on hyphens, so "per-installation" came back as "per-
    installation" and the note said something its author had not said."""
    note = ("confirmed 2026-09-15: a per-installation endpoint answers "
            "tools/list with 401 and a Bearer challenge, and its protected "
            "resource metadata names a per-installation authorization server")
    assert eval(f"({_as_source(note, 'note')})") == note  # noqa: S307


def test_only_what_differs_from_the_default_is_printed(capsys):
    """A row restating eight defaults reads as eight decisions, and a reviewer
    then checks each one to find the two that were measured."""
    export_server("cloudflare")
    printed = capsys.readouterr().out
    for never in ("register_at", "probe_tool", "header", "per_client_url",
                  "rest_takes_session", "scopes"):
        assert never not in printed, f"{never} is at its default and was printed"
    # The three that are always said, because a row without them says nothing.
    for always in ("provider=", "url=", "public_client="):
        assert always in printed


def test_the_block_is_quoted_the_way_the_file_it_goes_into_is(capsys):
    """`repr` is nearly right and wrong in the place that matters: it quotes
    with apostrophes and every string in servers.py is double quoted. A block
    somebody has to reformat before it fits is not paste-ready, which was the
    only reason to print source rather than JSON.

    Caught by mutation: swapping json.dumps for repr passed every other test
    here, because eval does not care which quote was used and the reviewer
    reading the diff is the one who does.
    """
    for name in ("cloudflare", "zoho", "stitch"):
        export_server(name)
        printed = capsys.readouterr().out
        assert "='" not in printed and "'," not in printed, (
            f"{name} exported with apostrophes; servers.py uses double quotes")


# ---- and never carries the credential -----------------------------------

def test_a_provider_whose_url_is_the_login_is_refused():
    """`auth="url"` means the address is the credential. The destination is a
    public pull request, so this is the one row that must not print."""
    secret = RemoteServer(provider="mine", public_client=True, auth="url",
                          url="https://mcp.example.test/abc123def456/message")
    with pytest.raises(CredentialInUrl) as refused:
        shareable(secret)
    assert "the URL is the credential" in str(refused.value)


def test_a_per_installation_row_that_somehow_has_an_address_is_refused():
    """The built-in rows never look like this: `per_client_url` implies an
    empty url and a test upstream holds that. A hand-edited servers.json can,
    and then the url may be one operator's own installation."""
    muddled = RemoteServer(provider="mine", public_client=True,
                           per_client_url=True,
                           url="https://acme-org.example.test/mcp/abc/message")
    with pytest.raises(CredentialInUrl):
        shareable(muddled)


def test_a_per_installation_row_with_no_address_exports_fine():
    """Zoho is the case. The table holds no address for it, so there is
    nothing to leak, and refusing would block the contribution that per
    installation providers most need: the row that says they are one."""
    assert shareable(SERVERS["zoho"])["per_client_url"] is True
    assert shareable(SERVERS["zoho"])["url"] == ""


def test_the_cli_refuses_rather_than_printing_a_secret(capsys, tmp_path,
                                                       monkeypatch):
    from munim.remote import servers

    path = tmp_path / "servers.json"
    path.write_text(json.dumps({"mine": {
        "url": "https://mcp.example.test/abc123def456/message",
        "public_client": True, "auth": "url"}}))
    monkeypatch.setattr(servers, "USER_SERVERS", path)

    assert export_server("mine") == 2
    said = capsys.readouterr()
    assert "abc123def456" not in said.out
    assert "abc123def456" not in said.err
    assert "the URL is the credential" in said.err


def test_an_unknown_name_says_what_is_known(capsys):
    assert export_server("not-a-provider") == 2
    assert "cloudflare" in capsys.readouterr().err
