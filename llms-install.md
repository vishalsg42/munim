# Installing Munim, for an agent doing it on somebody's behalf

This file is for you, the coding agent, not for the person reading over your
shoulder. The README is written for them. This one says the parts that are easy
to get wrong when nobody is watching the terminal.

## What it is, in one line

One MCP server holding a separate live session with every client's account, so
one agent can read across a dozen businesses and write inside only the one it
is told to.

## Install

```bash
uv tool install munim          # or: pipx install munim, or: pip install munim
```

Python 3.10 or newer. No Node, no build step, no account to create first. The
control room ships inside the wheel, so there is nothing to build after
installing.

Register it with whichever client you are configuring:

```bash
claude mcp add munim -- munim-mcp
```

For anything that takes a JSON config, the command is `munim-mcp` with no
arguments:

```json
{ "mcpServers": { "munim": { "command": "munim-mcp" } } }
```

## Stop here and hand back

**Do not run `munim connect`.** It opens a browser for an OAuth login on port
8976 and the person has to complete it themselves, on their own account, and
read the consent screen. An agent cannot do that step and should not try.

Tell them the two commands and stop:

```bash
munim clients add "Acme Ltd"          # write a client down
munim connect "Acme Ltd" cloudflare   # a browser opens; that is the whole setup
```

There is no wrong order. Connecting first lets the account name the client.

## What you can check without any credential

```bash
munim --version
munim servers          # every provider it knows, and what each one needs
munim doctor           # what is missing, and the fix for each
munim clients          # who is registered, and what is connected
```

All four work on a fresh install with nothing connected. `munim doctor` is the
one to run if something looks wrong: it reports only what is broken, and every
line names the file it read and the command that fixes it.

## Three things that will otherwise waste your time

**There is no API key to paste, for most providers.** Eight of the eleven
built-in providers register a client on demand and need nothing set up. If you
find yourself looking for where to put a token, you are probably on the wrong
path. `munim servers` says which of them need anything.

**Two do need setup, and the pages say what.** Gmail needs an OAuth application
registered by hand, about ten minutes of Google Cloud. Stitch takes an API key
in a header. Zoho needs the endpoint supplied with `--url`, because each
installation has its own. `docs/providers/` has a page for each.

**Credentials live in the operating system keychain, not in a file you can
write.** There is no `.env` to create for sessions. `~/.munim/.env` exists for
the two application credentials only, and `munim config app set` writes it for
you. Never invent a config file; `munim doctor` names the real one.

## Verifying the install worked

```bash
munim doctor
```

**`doctor` reports only what is wrong.** Run from a published install with an
empty home directory, a fresh install prints exactly this:

```
munim 0.8.1, python 3.13, agents off (local)

No problems found.  Run with --verbose to see what is connected. (0.0s)
```

Having no client connected is not a problem and is not listed, so that report
is the success case rather than a sign the check did not run. `agents off` is
also correct on a fresh install: the model is opt in.

Anything it does list comes with the fix on the next line, naming the command
or the file. Take the fix it gives rather than inferring one: several of those
lines exist because two commands disagreed about where configuration lives, and
guessing is how that happened.

## If you are adding a provider it has not met

Munim is not limited to its built-in list. Point it at any MCP server and it
works out how that server authenticates by calling it without credentials and
reading the challenge back:

```bash
munim servers add acme https://mcp.acme.com/mcp
munim servers export acme     # the row it derived, ready for a pull request
```

`add` prints what it worked out and what to do next, and `export` prints the row
plus where to paste it. Run end to end from a published install against a live
server, the export looks like this:

```python
    "acme": RemoteServer(
        provider="acme",
        url="https://mcp.acme.com/mcp",
        public_client=True,
        note="confirmed: registers clients at ..., auth methods [...]",
    ),
```

The second command is the one worth knowing: contributing a provider back is a
data row and a docs page, with no Python written. `CONTRIBUTING.md` has the
lane.
