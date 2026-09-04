# Munim

[![PyPI](https://img.shields.io/pypi/v/munim)](https://pypi.org/project/munim/)
[![Python](https://img.shields.io/pypi/pyversions/munim)](https://pypi.org/project/munim/)
[![Tests](https://github.com/vishalsg42/munim/actions/workflows/tests.yml/badge.svg)](https://github.com/vishalsg42/munim/actions/workflows/tests.yml)
[![Licence](https://img.shields.io/pypi/l/munim)](LICENSE)

**One MCP server holding a live session with every client's account at once.**

A coding agent can be logged in to one Cloudflare account. One Vercel. One Resend.
Connect a second client and the first one goes away. So the person looking after a
dozen small businesses runs a dozen agent sessions, and no single one of them can
answer a question about more than one client.

Munim holds them all. Each client gets its own registration with the provider, its
own token and its own namespace in the tool list, so one agent can **read across
every client and write inside the one you named**.

```
Kloudfirst       -> Kloudfirst@gmail.com's Account          (3 tools)
Balaji Roofings  -> Tech.bajajiroofing@gmail.com's Account  (3 tools)

both sessions opened concurrently, one process, no logout
```

That is a real run against two real Cloudflare accounts, not a diagram. Reproduce
it with your own two: [`scripts/cross_account_probe.py`](scripts/cross_account_probe.py).

---

## Install

Requires Python 3.10+. Nothing else: no Node, no build step, no account to create
first.

```bash
uv tool install munim          # or: pipx install munim, or: pip install munim
claude mcp add munim -- munim-mcp
```

The control room ships inside the package, so there is nothing to compile.

### Three steps to something useful

**1. Point it at a model.** Any Strands-supported provider works: Amazon Bedrock,
Gemini, Anthropic, OpenAI, Ollama. Put one key in `.env` in the directory you run
from (see [`.env.example`](.env.example)):

```
GEMINI_API_KEY=...
```

Only the tools that reason need this: `check`, `work_on_client` and
`ask_across_clients`. Connecting accounts and reading them needs no model.

**2. Connect a client.** A browser opens, you sign in, and that is the setup. No
application to register, no client secret anywhere in this project, because the
providers each run their own MCP server and each issues a client on demand.

```bash
munim connect cloudflare
```

Leave the name out and the account you sign in to supplies it, which is what stops
a name and an account from drifting apart. To add a second client, **sign out of
the provider in your browser first**, or the consent screen hands you the same
account again and both clients end up bound to it.

```bash
munim connect cloudflare      # sign in as the second client
munim clients                 # who is connected, and to what
```

**3. Ask your coding agent something that spans them.** This is the part a single
logged-in session cannot do.

```
which of my clients has a domain expiring this quarter?
check ivyandfern.co.uk for Ivy & Fern Studio
```

Run `munim doctor` at any point. It says what is set up, what is not, and the
exact command to fix each gap.

---

## The problem it solves

One person maintains the web and email setup of a dozen small businesses. The
clients own the accounts and pay the bills; the operator holds delegated access and
does the work. Every provider allows one login at a time, so the workaround is a
separate agent session per client: isolation built out of browser tabs and
discipline.

That costs three things:

1. **Switching.** Every action on a different client means re-authenticating.
2. **No vantage point.** *"Which clients have a domain expiring this quarter?"*
   cannot be asked from anywhere, because no place can see all of them.
3. **Silent failure.** Standing up a client is a copy-paste dance between
   accounts, and one of the handoffs fails invisibly.

The third one is why this exists. Resend emits DKIM and SPF records that must be
written into Cloudflare. Get the A record wrong and the site does not load, and
you find out in minutes. **Get the SPF record wrong and nothing breaks**: the
client's invoices quietly stop arriving, and nobody notices for weeks.

---

## The tools your agent gets

Twelve, and this is the whole surface. Anything not listed here is not reachable,
whatever else is in the repository.

| Tool | |
|---|---|
| `list_clients` | every client and what each is connected to |
| `client_status` | what is known about one client |
| `add_client` | register one |
| `connect_provider` | store a pasted key, for providers with nothing better |
| `find_across_clients` | one deterministic question over all of them at once |
| `ask_across_clients` | one open question over all of them, read-only (see the note below) |
| `audit_all_clients` | the whole catalogue against every client, silent when they all pass |
| `check` | the 13-check catalogue against a client or a bare domain |
| `work_on_client` | do something inside one client's accounts, using their own provider tools |
| `plan_mail_setup` | what setting up email would change, touching no DNS |
| `apply_mail_setup` | carry out a plan, with approval required to replace a record |
| `launch_status` | read a run back |

**Repair is deliberately two calls rather than one.** A tool call returns once, so
there is nowhere for a mid-flight question to go. `plan` reads what is there and
says what would change; `apply` carries out a plan the operator has seen. Approval
is the gap between them.

`apply` refuses without `approved=true` when the plan would replace or combine a
record somebody put there on purpose. Creating one that does not exist is not a
judgement call; changing one that does is, and it is someone else's live mail.

**What `ask_across_clients` can actually see, and why it is less than it sounds.**
A cross-client tool is built from only the provider tools marked `readOnlyHint`,
default deny, so a tool that changes something is not present to be called. On
Cloudflare that leaves `docs` and `search`, because `execute` is the only tool
that reads live account data and it is also the only one that can write, so it
carries no read-only hint and is correctly refused. Asked to count DNS zones
across clients, the agent will tell you which API would answer rather than
answering.

This is the boundary working, not failing. The cost is real and worth stating:
the open-ended cross-client question is limited by what each provider chooses to
annotate. `find_across_clients` and `audit_all_clients` are unaffected, because
they read DNS directly rather than through a provider's tools, and they are what
the domain-expiry and mail-health questions actually run on.

---

## Any MCP server

Eleven providers are built in, and only the first needed any code. Point Munim at
any other MCP server and it works out how that server authenticates:

```bash
munim add-server acme https://mcp.acme.com/mcp
munim connect "Acme Ltd" acme
munim servers                       # what Munim knows about, and what each needs
```

Built in: Cloudflare, Vercel, Resend, Netlify, Linear, Notion, Sentry, Supabase
(all zero setup, via dynamic client registration), Gmail and Stitch (need a
registered application), Zoho (the endpoint URL is the credential).

---

## Every command

```bash
munim connect cloudflare                     # browser login; the account names the client
munim connect "Balaji Roofings" vercel       # or name the client yourself
munim connect "Balaji Roofings" zoho --url https://…   # Zoho: the URL is the credential
munim connect "<client>" resend --token      # paste a key instead of logging in

munim clients                                # who is connected, and to what
munim doctor                                 # what is missing, and the fix for each
munim servers                                # which MCP servers Munim knows about
munim add-server <name> <url>                # point it at any other MCP server

munim rename "<old>" "<new>"                 # the name is a label; the id is the identity
munim merge "<source>" "<target>"            # if one account became two clients
munim forget "<client>"                      # only when it holds nothing
munim disconnect "<client>" [provider]       # drop credentials, keep the client
munim disconnect --all                       # drop every credential
```

A rename is only a label change. Credentials are filed under a client id that never
changes, so renaming cannot orphan a session.

### Watching a run

The control room follows a run as it happens. It reads the same run log the
terminal does, so it can be opened mid-launch, or after one, and replays from the
beginning:

```bash
munim-room                              # http://127.0.0.1:8977
munim-room --port 8986                  # if 8977 is taken
munim-room --runs DIR --reports DIR     # serve a different set of runs
```

---

## Status

| | |
|---|---|
| Per-client credential containers, OS keychain | ✅ |
| Read across / write within | ✅ |
| Check catalogue, 13 checks, no credentials needed | ✅ |
| **Two accounts on one provider, concurrently, one process** | ✅ **live against two real Cloudflare accounts** |
| A session per client against the providers' own MCP servers | ✅ live |
| Dynamic client registration, so nothing is registered by hand | ✅ 8 of 11 providers |
| Client named and verified by the account it was authorised as | ✅ |
| Cross-client questions, writes structurally absent | ✅ |
| Run log with replay, control room live over SSE | ✅ |
| Launch report for the business owner | ✅ |
| OAuth connect (PKCE), issuer validated per RFC 9207 | ✅ |
| Cloudflare DNS writes: idempotent upsert, SPF merge | ◐ tested, not yet run against a live zone |
| Resuming an interrupted launch from the log | ⬜ |
| Vercel write operations | ⬜ |

Known gaps and why they are gaps: [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## Development

```bash
git clone https://github.com/vishalsg42/munim && cd munim
uv venv && uv pip install -e ".[dev]"

uv run pytest -q                       # the Python suite
node --test "tests/room/*.test.mjs"    # the control room's reducer
```

The control room is one HTML page and one ES module, served as written. There is
no build step and no `node_modules`; the only reason Node appears at all is to run
six tests over the reducer, and those need no install.

To check the claim this project rests on, connect two of your own accounts and run:

```bash
uv run python scripts/cross_account_probe.py
```

It fails if either account is empty, and fails if the two return the same
resources: two grants returning the same thing are one account wearing two names,
which would make the claim vacuous.

## Documentation

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | how it is built, and the four decisions that shape it |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | every design decision and its reasoning, including the wrong ones |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | what is not done, and why |

---

## Disclosure

Built with AI assistance (Claude Code), which the hackathon rules permit. No
pre-existing code was incorporated; the repository was created during the
submission period. Prior personal projects informed the working method but
contributed no source.

*A munim is the steward a business owner trusts to keep their books and handle
their affairs without being asked each time.*

## Licence

MIT. See [LICENSE](LICENSE).
