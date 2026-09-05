# Munim

[![PyPI](https://img.shields.io/pypi/v/munim)](https://pypi.org/project/munim/)
[![Python](https://img.shields.io/pypi/pyversions/munim)](https://pypi.org/project/munim/)
[![Tests](https://github.com/vishalsg42/munim/actions/workflows/tests.yml/badge.svg)](https://github.com/vishalsg42/munim/actions/workflows/tests.yml)
[![Licence](https://img.shields.io/pypi/l/munim)](LICENSE)

**One MCP server holding a live session with every client's account at once.**

A coding agent can be logged in to one Cloudflare account. One Vercel. One
Resend. Connect a second client and the first goes away. So the person looking
after a dozen small businesses runs a dozen agent sessions, and none of them can
answer a question about more than one client.

Munim holds them all. Each client gets its own registration with the provider,
its own token and its own namespace in the tool list, so one agent can **read
across every client and write inside the one you named**.

```
Kloudfirst       -> Kloudfirst@gmail.com's Account          (3 tools)
Balaji Roofings  -> Tech.bajajiroofing@gmail.com's Account  (3 tools)

both sessions opened concurrently, one process, no logout
```

That is a real run against two real Cloudflare accounts, not a diagram.
Reproduce it with your own two:
[`scripts/cross_account_probe.py`](scripts/cross_account_probe.py).

## Install

Requires Python 3.10+. Nothing else: no Node, no build step, no account to
create first.

```bash
uv tool install munim          # or: pipx install munim, or: pip install munim
claude mcp add munim -- munim-mcp
```

## Start

```bash
munim clients                          # who you look after, and what is connected
munim clients add "Ivy & Fern"         # write one down, connect nothing yet
munim connect "Ivy & Fern" cloudflare  # a browser opens; that is the whole setup
```

There is no wrong order. Connect first and the account you sign in to names the
client, or write the client down first and connect whenever. Both arrive in the
same place.

Then ask your coding agent something a single logged-in session cannot answer:

```
which of my clients has a domain expiring this quarter?
check ivyandfern.co.uk for Ivy & Fern Studio
```

**Munim is local by default.** The checks, the audit and the mail plan are
deterministic: they never needed a model and never call one. Three tools can
also reason about what they find (`check`, `work_on_client`,
`ask_across_clients`), and that is switched off until you ask for it, so having
a key lying around is not the same as consenting to use it.

```bash
munim config ai key gemini   # prompts, stored in ~/.munim/credentials.json
munim config ai on           # takes effect on the next call, no reconnect
munim config ai              # what is on, on what, and where each came from
```

Hosts are Amazon Bedrock, which works out of the box, plus Google Gemini and
Anthropic, which Strands ships as extras: `pip install 'munim[gemini]'`.

One thing this does not change: Munim runs as an MCP server, so whatever its
tools return goes into your coding agent's context and therefore to whichever
model that agent runs on. Turning agents off stops Munim calling a model of its
own; it cannot change how MCP works. The [privacy policy](site/privacy.html)
says so plainly.

**`munim doctor`** says what is set up, what is not, and the exact command to fix
each gap. Start there whenever something is unclear.

## Documentation

| | |
|---|---|
| [Commands](docs/COMMANDS.md) | the whole CLI |
| [Tools](docs/TOOLS.md) | what your coding agent gets, and what it deliberately cannot do |
| [Providers](docs/providers/README.md) | a page each: setup, what connecting grants, what is verified |
| [Architecture](docs/ARCHITECTURE.md) | how it is built, and the four decisions that shape it |
| [Decisions](docs/DECISIONS.md) | every design decision and its reasoning, including the wrong ones |
| [Roadmap](docs/ROADMAP.md) | what is not done, and why |
| [Development](docs/DEVELOPMENT.md) | running the tests, and reproducing the claim above |

## Why this exists

One person maintains the web and email setup of a dozen small businesses. The
clients own the accounts; the operator holds delegated access and does the work.
Every provider allows one login at a time, so the workaround is a separate agent
session per client.

The costly part is not the switching. It is that **a mistake in mail setup breaks
nothing visible**. Get an A record wrong and the site is down in minutes. Get the
SPF record wrong and the client's invoices quietly stop arriving, and nobody
notices for weeks.

*A munim is the steward a business owner trusts to keep their books and handle
their affairs without being asked each time.*

## Disclosure

Built with AI assistance (Claude Code), which the hackathon rules permit. No
pre-existing code was incorporated; the repository was created during the
submission period.

## Licence

MIT. See [LICENSE](LICENSE).
