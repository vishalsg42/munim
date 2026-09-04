"""Every client's provider tools, in one Strands agent, namespaced per client.

This is where the project's claim and the framework meet. Strands' `MCPClient`
takes an `httpx.Auth` and a tool-name prefix, and the MCP SDK's
`OAuthClientProvider` is an `httpx.Auth`, so one agent can hold a session per
client against the same provider and tell them apart by name.

That is the cross-account capability stated as configuration rather than as
adapter code: `find_across_clients` becomes an agent that can see
`balaji_roofings_*` and `kloudfirst_*` at once and was never able to see either
without being told which.

The prefix is not cosmetic. It is the only thing standing between "update this
DNS record" and doing it in the wrong account, so it is derived from the
registered client name and nothing else.
"""

import re

from strands.tools.mcp import MCPClient

from munim.remote.servers import server_for
from munim.remote.session import NoRemoteServer, auth_for


def prefix_for(client: str) -> str:
    """A tool-name prefix from a client name.

    Lowercased, non-word characters collapsed to underscores. Two clients whose
    names differ only by punctuation would collide here, which is why
    `toolsets_for` refuses rather than letting the second quietly win.
    """
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", client.strip().lower()).strip("_")
    if not slug:
        raise ValueError(f"client name {client!r} leaves nothing to name tools with")
    return slug


def _is_read_only(tool, **_) -> bool:
    """Whether a provider tool is safe to hand to something spanning clients.

    Default deny. An MCP tool declares `readOnlyHint` and `destructiveHint` in
    its annotations; a tool that declares neither is not provably read-only, so
    it does not get into a cross-client set. That makes "read across, write
    within" (D5) a property of which tools exist rather than an instruction the
    model is asked to follow, and instructions are not a boundary.

    Stated plainly, because it is a trust assumption and not a proof: these are
    hints from the provider's own server. A server that mislabelled a
    destructive tool as read-only would get past this. That is a provider
    already trusted with the account, and the alternative, matching on tool
    names, is guessing.
    """
    annotations = getattr(getattr(tool, "mcp_tool", None), "annotations", None)
    if annotations is None or annotations.readOnlyHint is None:
        return False
    return bool(annotations.readOnlyHint) and not annotations.destructiveHint


def toolset_for(client: str, provider: str, *, backend=None,
                read_only: bool = False) -> MCPClient:
    """One client's tools from one provider, ready to hand to an Agent."""
    server = server_for(provider)
    if server is None:
        raise NoRemoteServer(f"{provider} runs no MCP server")
    return MCPClient(
        url=server.url,
        auth_provider=auth_for(client, provider, backend=backend),
        prefix=prefix_for(client),
        tool_filters={"allowed": [_is_read_only]} if read_only else None,
    )


def toolsets_for(clients: list[str], provider: str, *, backend=None,
                 read_only: bool = False) -> list[MCPClient]:
    """Every client's tools from one provider, for a single agent.

    Refuses on a prefix collision instead of resolving it. Two clients sharing a
    prefix means one of them silently answers for the other, and a mutation on
    the wrong account is the failure this project exists to prevent (D5).
    """
    seen: dict[str, str] = {}
    for client in clients:
        prefix = prefix_for(client)
        if prefix in seen:
            raise ValueError(
                f"{client!r} and {seen[prefix]!r} both become {prefix!r}, so a "
                "tool call could not say which account it meant. Rename one."
            )
        seen[prefix] = client
    return [toolset_for(c, provider, backend=backend, read_only=read_only)
            for c in clients]
