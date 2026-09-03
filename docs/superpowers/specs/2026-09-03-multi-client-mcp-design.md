# Multi-client MCP — design

Status: **draft for review**, 2026-09-03.
Submission for the AWS Agents for Humans Hackathon (deadline 2026-09-14 17:00 PDT).
Read `docs/HACKATHON.md` for the contest analysis and the competitive scan this design reacts to.

---

## 1. The problem

One person maintains the digital estate of a dozen small businesses. **The clients own the
accounts** — Vercel, Cloudflare, Resend, Supabase — and pay the bills. The operator holds
delegated access and does the work.

Every account is single-tenant by design, so the only way to move between clients is to log
out and log back in. The operator's current workaround is **a separate coding-agent session
per client**: isolation built out of tabs and discipline.

That costs three things:

1. **Switching.** Every action on a different client means re-authenticating somewhere.
2. **No vantage point.** Questions that span clients — *whose domain renews this month?* —
   cannot be asked from anywhere, because no place exists that can see all of them.
3. **Silent failure during setup.** Standing up a new client is a copy-paste dance between
   accounts, and one of the handoffs fails invisibly (see §3).

## 2. Who it is for

**The operator** is the user of the tool. **The clients are the people it serves** — small
business owners whose site launches correctly and whose email does not quietly stop being
delivered. That is not a positioning choice; the accounts and the money are literally theirs.

## 3. The launch sequence, and where it breaks

The operator's real workflow, as described:

```
dev complete
  → get Vercel access from the client
  → deploy the project
  → configure the custom domain          Vercel emits A/CNAME values
  → write those records into Cloudflare
  → if email is needed: Resend           Resend emits DKIM / SPF / return-path
  → write those records into Cloudflare too
  → if a backend is needed: Supabase     Supabase emits connection strings
  → write those into Vercel env vars
  → verify, then email the client
```

Four handoffs, three of them between two different companies' dashboards:

| From | To | What crosses | Failure mode |
|---|---|---|---|
| Vercel | Cloudflare | A / CNAME | Site does not resolve — **visible immediately** |
| Resend | Cloudflare | DKIM, SPF, return-path | Mail silently goes to spam — **invisible for weeks** |
| Supabase | Vercel | DB URL and keys → env vars | App breaks on deploy — **visible immediately** |
| all | client | "your site is live" | — |

**The Resend→Cloudflare handoff is the one worth building around.** A wrong DKIM record breaks
nothing you can see; the client's mail just stops arriving and nobody finds out for a month.

This is also the honest justification for the whole architecture: **the output of one account
is the input of another**, so the job is structurally cross-account. Multi-account access is
not a convenience here, it is the task.

## 4. The concept

**A single MCP server, added once to whatever coding agent the operator uses** — Claude Code,
Codex, Antigravity, Cursor. It exposes tools for each provider. Every tool call is bound to
exactly one **client container**, and no other client's credentials are present in that call.

```
Claude Code / Codex / Antigravity
        │  MCP (stdio, local)
        ▼
   the server ──► container: acme     ─► acme's Vercel / Cloudflare / Resend / Supabase
              ├─► container: bharat   ─► bharat's credentials
              └─► container: …        ─► …
```

You never log out, because you were never logged in — the container is.

### Two rules that define it

**Read across, write within.** Questions may span every container: renewals, costs, versions,
who holds access. Nothing may be *changed* in a container that has not been explicitly entered.
Any mutation names its client first, and the other clients' credentials are not loaded.

**The coding agent never sees a credential.** Keys are held by the credential store and injected
inside the container at the point of the API call. The agent receives results, never tokens.

### Where Strands does the work

The MCP server is the door. Behind a tool like `launch_client`, a **Strands agent** runs the
multi-step job, because the launch is not a sequence of API calls — it needs judgement:

- **Waiting well.** DNS propagation and certificate issuance are non-deterministic. Poll, back
  off, and distinguish "not yet" from "wrong."
- **Diagnosing.** The certificate has not issued — propagation, a CAA record, or the wrong
  nameservers? That is reasoning over evidence.
- **Knowing when to stop.** Nameservers not yet delegated to Cloudflare is a human problem,
  not something to retry.

### The determinism split

Carried from `google-agentic-cinema` D16: **enumeration and checking are deterministic; only
interpretation and judgement are model work.** Provider adapters enumerate. Rules compute
findings with real dates. The model diagnoses, decides when to escalate, and writes for the
client. It cannot invent a DNS record or alter an expiry date.

## 4a. The tool surface

What the coding agent actually sees. Every tool that touches a provider takes `client` as its
first argument — there is no ambient "current client", because an implicit selection is exactly
how the wrong account gets written to.

**Containers**

| Tool | Purpose |
|---|---|
| `list_clients` | Which containers exist, and which providers each has connected |
| `add_client` | Register a client |
| `connect_provider` | Store a credential for one client and one provider. Runs once per pair |

**Read across** — may span every container, never mutates

| Tool | Purpose |
|---|---|
| `find_across_clients` | One question over every container: domains, renewals, versions, env keys present |
| `client_status` | Everything known about one client's estate |

**Write within** — names a client, loads only that client's credentials, confirms before acting

| Tool | Purpose |
|---|---|
| `launch` | The Strands workflow: deploy, domain, DNS, mail, backend, verify. §3 end to end |
| `deploy` | Deploy or redeploy one client's project |
| `set_env` | Set environment variables |
| `dns` | Read or write DNS records |
| `logs` | Fetch logs |
| `verify` | Re-run the launch checks: resolution, certificate, SPF/DKIM/DMARC |

`launch` is the only tool backed by a full Strands agent; the rest are direct adapter calls.
That keeps the agent where judgement is needed and out of the way where it is not.

**Deliberately absent:** any tool that returns a credential, and any tool that mutates without
naming a client.

## 5. Architecture

```
MCP server (local, stdio)
    │
    ├── container registry ── which clients exist, which providers each has
    │
    ├── credential store ──── per client, per provider; never returned to the agent
    │
    ├── container ─────────── one per client; only that client's credentials and tools
    │       │
    │       └── provider adapters, all to one contract:
    │               authenticate(client) → act() | enumerate() → [Asset]
    │
    ├── Strands agent ─────── multi-step workflows inside a container
    │                          (launch, diagnose, verify)
    │
    └── cross-container reader ── read-only queries spanning every container
```

**The adapter contract is what makes many providers affordable.** Each provider implements one
small interface. A check or a workflow step is written against the contract, not per provider,
so adding GoDaddy or Hostinger later adds assets, not logic.

### Providers

| Provider | v1 | Why |
|---|---|---|
| Vercel | yes | Deploy, domains, env vars — start of the chain |
| Cloudflare | yes | Destination of two of the three handoffs |
| Resend | yes | The silent-failure handoff; the reason this matters |
| Supabase | v1 if time | Fourth handoff, into Vercel env vars |
| GoDaddy, Gmail/Zoho Mail, Hostinger | later | Same contract; additive |

### Later, not now

Hosted deployment on AgentCore Runtime, which buys platform-enforced isolation, a live demo
URL, and the scheduled **watcher** — renewals and cost changes across every client, with a
plain-language update drafted for the channel that client uses. The watcher is only meaningful
once setup has settled, which is why it is phase two.

## 6. Scope

**In, v1**
- Local stdio MCP server, installable in Claude Code / Codex / Antigravity with one config line
- Container model with per-client credential isolation; read across, write within
- Adapters: Vercel, Cloudflare, Resend (Supabase if time)
- Strands agent running the launch workflow end to end, with verification and escalation
- Cross-container read queries
- Human confirmation on every mutation, showing the client name and the exact change

**Out, v1**
- Hosted deployment and the scheduled watcher
- Re-billing or invoicing (the clients pay the providers directly — settled 2026-09-03)
- Access auditing across clients
- Any provider not listed above

## 7. Definition of done for a launch

To be confirmed with the operator. Working assumption:

- Site resolves on the custom domain over HTTPS with a valid certificate
- A test message passes SPF, DKIM and DMARC
- If a backend was requested, the app builds and connects to it
- A note to the client is drafted

## 8. Risks

| Risk | Response |
|---|---|
| **Theme fit.** "Agents for Humans" — this is a tool for a developer, and the DevOps-agent lane is the most crowded in the contest (12+ repos, see `docs/HACKATHON.md`) | Lead with the client, not the operator. The demo ends on a business whose email works, not on a green terminal. This is the weakest criterion for this concept and the pitch must carry it. |
| Local isolation is enforced by our own code, not a platform | State it plainly. Subprocess-per-container, and a test proving credentials for client B are absent from a client A call. Do not claim platform-grade isolation until it runs on AgentCore. |
| Real client accounts in a public repo and video | Build against real stacks locally, never committed. Demo against a tenant the operator owns, clearly labelled. Same discipline as Passbook's bank statements. |
| Provider API surface larger than expected | Adapters are thin and read/act only what the workflow needs. No stubs — an unimplemented provider is absent, not faked. |
| Doing the right thing in the wrong client's account | The core safety property. Mutations name the client; other credentials are not loaded; confirmation shows the client name. |

## 9. How this maps to the judging criteria

| Criterion (20% each) | This design |
|---|---|
| Technological Implementation | Strands agent running a real multi-step cross-provider workflow with MCP tools, structured output and escalation |
| Design | One install line, works inside the tool the user already has; no new UI to learn |
| Potential Impact | Named audience: small businesses whose launches silently half-fail. The DKIM case is concrete and measurable |
| Creativity & Originality | Verified-empty lane: every comparable entry scanned is single-tenant (`docs/HACKATHON.md` §3) |
| Presentation | A launch has a finish line — site live, mail passing DKIM — which films far better than a dashboard |

## 10. Open questions

1. **Track.** Professional is the natural fit and the most crowded. Everyday and Good Neighbor
   are weaker fits. Unresolved.
2. **Name.** None chosen.
3. **Definition of done** (§7) needs the operator's confirmation.
4. **Where the operator has been burned** — the real failure cases are worth more than invented
   checks, and have not yet been captured.
5. **Supabase in or out of v1.**
