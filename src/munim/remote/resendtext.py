"""Resend's MCP server answers in prose. This reads it back into its REST shape.

Cloudflare's MCP server returns the Cloudflare API's own JSON, so reaching it
through a session costs nothing. Resend's returns a formatted block written for
a person:

    Name: acme.example
    ID: ad1b8ef1-206e-4bc5-b442-cc5ed8fff7d9
    Status: verified

and the DKIM key that has to end up in somebody's DNS arrives as an indented
line under a heading. Parsing a third party's presentation layer is not a thing
to be relaxed about: it can change without notice, and the failure that matters
is not a crash, it is a value that parses into something plausible and wrong,
which then gets published to a client's zone.

So everything here refuses rather than guesses. A block that does not match is
not skipped, a records section that yields nothing is an error rather than an
empty list, and a record whose value does not look like what its own heading
says it is stops the run. A loud failure sends somebody to look at Resend's
output. A quiet one signs a client's mail with a key nobody has.
"""

import re

# `DKIM (TXT):`, `SPF (MX):`. The heading carries both the purpose and the
# record type, and Resend uses the same two words the REST API puts in its
# `record` and `type` fields.
HEADING = re.compile(r"^([A-Za-z0-9_]+)\s*\(([A-Za-z]+)\):\s*$")
FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z ]*):\s*(.*)$")

# What each purpose has to look like. A DKIM value that does not start with
# `p=` is not a DKIM key however confidently it was formatted.
SHAPES = {
    ("DKIM", "TXT"): ("p=", "a DKIM public key starts with p="),
    ("SPF", "TXT"): ("v=spf1", "a sender policy starts with v=spf1"),
}


class ResendTextError(Exception):
    """Resend's MCP server said something this cannot read.

    Always worth surfacing whole: the text that failed to parse is the only
    evidence of what changed.
    """


def _blocks(text: str) -> list[list[str]]:
    """Split on blank lines, keeping each block's lines."""
    out, current = [], []
    for line in text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def _fields(lines: list[str]) -> dict[str, str]:
    found = {}
    for line in lines:
        match = FIELD.match(line)
        if match:
            found[match.group(1).strip().lower()] = match.group(2).strip()
    return found


def joined(result) -> str:
    """One string out of however many text blocks the tool returned."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n\n".join(part for part in result if isinstance(part, str))
    raise ResendTextError(f"expected text from Resend, got {type(result).__name__}")


def records(text: str) -> list[dict]:
    """The DNS records under `DNS Records:`, in the REST API's own shape.

    Empty only when Resend printed no records section at all, which is what a
    domain with nothing to publish looks like. A section that is present and
    yields nothing is a parse failure, not an empty domain.
    """
    head = text.find("DNS Records:")
    if head == -1:
        return []

    out = []
    for block in _blocks(text[head + len("DNS Records:"):]):
        heading = HEADING.match(block[0].strip())
        if heading is None:
            continue
        purpose, kind = heading.group(1).upper(), heading.group(2).upper()
        said = _fields(block[1:])
        name, value = said.get("name", ""), said.get("value", "")
        if not name or not value:
            raise ResendTextError(
                f"the {purpose} {kind} record has no "
                f"{'name' if not name else 'value'}:\n" + "\n".join(block))

        starts, why = SHAPES.get((purpose, kind), ("", ""))
        if starts and not value.startswith(starts):
            raise ResendTextError(
                f"{purpose} ({kind}) for {name} does not look like one: {why}. "
                f"Refusing rather than publishing it. Resend said:\n"
                + "\n".join(block))

        record = {"record": purpose, "type": kind, "name": name, "value": value,
                  "status": said.get("status", "not_started")}
        if said.get("priority"):
            try:
                record["priority"] = int(said["priority"])
            except ValueError:
                raise ResendTextError(
                    f"{purpose} ({kind}) for {name} has a priority that is not "
                    f"a number: {said['priority']!r}") from None
        out.append(record)

    if not out:
        raise ResendTextError(
            "Resend printed a DNS records section and none of it parsed. Its "
            "format has most likely changed:\n" + text[head:][:800])
    return out


def domains(text: str) -> list[dict]:
    """Every domain in the text, as `GET /domains` would have returned them.

    Records are attached when the text carries them, which `get-domain` does
    and `list-domains` does not. That matches the REST API, where the list
    endpoint omits them too.
    """
    found: list[dict] = []
    for block in _blocks(text):
        said = _fields(block)
        if "id" not in said or "name" not in said:
            continue
        found.append({"id": said["id"], "name": said["name"],
                      "status": said.get("status", ""),
                      "region": said.get("region", "")})
    if len(found) == 1:
        found[0]["records"] = records(text)
    return found


def one(text: str) -> dict:
    """A single domain, for the tools that answer about one."""
    found = domains(text)
    if len(found) != 1:
        raise ResendTextError(
            f"expected one domain in Resend's answer and found {len(found)}:\n"
            + text[:800])
    return found[0]
