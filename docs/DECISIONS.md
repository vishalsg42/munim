# Decision log

Why this project is shaped the way it is. Each entry records the decision, what drove it, and
what it costs, including the ones that were wrong first time. Reversals are kept rather than
tidied away, because the reasoning is the useful part.

This project began as an entry for a hackathon with a 2026-09-14 deadline, which it
missed. Some early entries reason about contest criteria, judges and a competitive scan,
and those references are left as written. The decisions they justify are still the
decisions in the code, and a log edited to look like it was always something else is a
log nobody should trust. Where a decision no longer applies, it is marked, not deleted.

---

## D1: The concept came from the operator's workflow, not from the inspiration text

**Context.** Devpost publishes an "Inspiration" section. Every one of its examples was checked
against a ~100-repo scan of the live field on 2026-09-03: bills-before-due-date, family
calendar, contractor compliance, teacher materials, solo researcher, shop-owner bookings, food
bank volunteer matching, **all already occupied**, most by four or more entries.

**Decision.** Treat the inspiration text as a crowding predictor, not an idea source. Build from
work the operator actually does.

**Cost.** Several hours of conversation before a concept emerged, and a concept that has to
explain itself rather than borrowing the organiser's framing.

---

## D2: The graveyard

Concepts raised and killed, with the evidence that killed them.

| # | Concept | Why it died |
|---|---|---|
| 1 | LinkedIn daily posting | Automated posting scores badly on Potential Impact and reads as spam-adjacent to judges whose job is developer trust |
| 2 | Lead generation | Commercially self-serving, "for humans" is a stretch, and it is the most saturated category in the wider agent space |
| 3 | Cheap low-latency voice agent | Real, felt problem and near-zero competition, but it is infrastructure rather than an agent for humans, Stage One theme-fit risk, and cost/latency graphs do not demo |
| 4 | r/zoho community answering agent | Genuinely empty lane and the operator's own lived loop, but Reddit blocked every verification path available, subreddit AI-content rules were unknown, and the posting path could have been dead on arrival |
| 5 | Housing society / RWA agent | No real org access, and `quorum-wip` (pushed 2026-09-01) already occupies residential-building coordination |
| 6 | Indian SMB statutory compliance | Genuinely empty lane, but no real access to a business's filings and US-based judges would not feel the pain |
| 7 | Re-billing provider costs into Zoho invoices | **Killed on a fact**: the clients own the provider accounts and pay directly. There is nothing to re-bill |
| 8 | Cross-client cost and renewal watcher | Not killed, deferred. It is meaningless until a client's setup has settled, so it is phase two (D8) |

---

## D3: It is an MCP server, not a CLI and not a dashboard

**Context.** The operator's first message on the topic asked for "containerized mcp… authenticate
multiple accounts at the same time without relogging & logout." Three subsequent design passes
drifted to a dashboard, then a watcher, then a standalone CLI. Each was corrected.

**Decision.** A single MCP server, added once to whatever coding agent is in use, Claude Code,
Codex, Antigravity, Cursor.

**Why.** MCP is the only interface that satisfies "inside any coding agent." A standalone CLI
would be another thing to switch to, which is the problem being solved.

**The process lesson.** The answer was in the first message. Three redesigns happened because
the stated request was treated as a symptom to interpret rather than a specification to build.
When a user names a mechanism, check whether they mean it before reframing it.

---

## D4: Local stdio first, hosted later

**Decision.** Ship as a local stdio MCP server. AgentCore Runtime deployment comes later.

**Why.** Everything the operator described, deploy, configure DNS, pull logs, launch a client,
is work done at their own machine. Local means no hosting, no cost, credentials never leave the
machine, and a one-line install a judge can reproduce.

**Cost, stated plainly.** Isolation is then enforced by our own code (subprocess per container,
only the named client's credentials loaded) rather than by a platform. On AgentCore Runtime the
wall is enforced by the platform, which is a stronger claim. **Do not claim platform-grade
isolation while running locally.** The hosted path also unlocks the scheduled watcher, which
local cannot do at all.

**Contest note.** AgentCore is *recommended*, not required; a live demo link is called out as
strengthening the Technical score. Local costs some of that and buys installability.

---

## D5: Read across, write within

**Decision.** Cross-container queries are read-only and may span every client. Mutations require
explicitly entering one container, and no other client's credentials are loaded for that call.

**Why.** The two things the operator wants are in tension. Isolation is the safety property.
Today, logging out is the seatbelt, and removing it needs a replacement. But the valuable
questions (*whose domain renews this month?*) are exactly the ones that span clients. This rule
gives the vantage point without giving up the wall.

**Consequence.** The failure mode being designed against is not "the agent did something
dangerous" but **"the agent did the right thing in the wrong client's account."** That is a
different claim from the human-approval framing that 11+ competitors are building, and it is
the honest risk here.

---

## D6: The coding agent never sees a credential

**Decision.** Keys live in the credential store and are injected inside the container at the
point of the API call. The coding agent receives results, never tokens.

**Why.** It is a real security property, it is cheap to hold, and it survives a judge reading
the repository. It also means a transcript, a log or a leaked context never contains a client's
key.

---

## D7: Enumeration is deterministic; only judgement is model work

**Decision.** Carried directly from `google-agentic-cinema` D16. Adapters enumerate. Rules
compute findings with real dates. The model diagnoses, decides when to escalate, and writes for
the client.

**Why.** The model cannot then invent a DNS record or alter an expiry date, which is the class
of error that would be fatal in someone else's production account.

---

## D8: Launch first, watcher second

**Context.** The design drifted twice toward a monitoring product. The operator corrected it
twice: *"initially I have to setup everything on vercel, cloudflare dns update or configuring
resend… then the watcher comes into picture when the initial setup settles down."*

**Decision.** Build the launch workflow. The watcher is phase two.

**Why.** You cannot monitor a stack you have not stood up. A launch also has a finish line,
site live, certificate valid, mail passing DKIM, and a monitoring dashboard has no ending,
which matters when Presentation is 20% of the score.

---

## D9: The Resend → Cloudflare handoff is the one worth building around

**Finding.** The launch has four cross-account handoffs. Three fail visibly: a wrong A record
means the site does not resolve, wrong env vars mean the build breaks. **A wrong DKIM record
breaks nothing observable**: the client's mail silently stops being delivered and nobody finds
out for weeks.

**Consequence.** Resend is in v1 despite being the third provider, and the invisible-failure
case is the demo's emotional centre.

---

## D10: Do not lead with the approval boundary

**Context.** The two previous submissions (`google-agentic-cinema`, `web-mcp-2026`) both led on
evidence provenance and the human-approval boundary. The 2026-09-03 scan found those to be the
two most crowded framings in this contest: 13+ repos on "evidence-first / only acts on what it
can prove", 11+ on "bounded autonomy / capability is not authority". Several are written in the
same vocabulary.

**Decision.** Build the rigour; never lead with it. Approval and evidence discipline belong in
the README and the architecture section, not the tagline, the Devpost headline, or the video's
first thirty seconds.

**Carried from Passbook.** *"Approval-gating and revocation are the most crowded framings in this
ecosystem; leading with either caps the submission at mid-field."*

---

## D11: Providers in v1

**Decision.** Vercel, Cloudflare, Resend. Supabase if time. GoDaddy, Gmail/Zoho Mail and
Hostinger later, through the same adapter contract.

**Why.** Vercel and Cloudflare are two ends of two handoffs; Resend is the third and carries the
silent failure. Everything else is additive rather than structural.

**Not negotiable.** No stubs. An unimplemented provider is **absent**, not faked. A competitor
in this field currently ships a README saying "WordPress API integration (currently stubbed)",
which is exactly what that costs from outside.

---

## D12: Real data for building, an owned tenant for the film

**Decision.** Calibrate against real client stacks locally, never committed and never filmed.
Demo exclusively against a tenant the operator owns, clearly labelled as a demo estate.

**Why.** The repository is public and the video is public; the accounts belong to clients who
have not consented to appear in either. Same discipline Passbook applied to the real bank
statements.

---

## D13: AgentCore is justified by hosting, not by the rules *(revises D4)*

**Context.** D4 chose local-first, which left AgentCore barely used. The obvious fix was to move
the agents onto AgentCore Runtime. Challenged on 2026-09-03: *does it really need AgentCore, and
how would we justify it?*

**Finding.** For the local mode it is not needed, and forcing it would be visible. Twelve AWS
judges know their own product. Shipping a client's API keys to a cloud vault when the OS keychain
would keep them on the operator's own machine is not a stronger design, for this use case it is
arguably a weaker one. Also worth stating precisely: **Strands is required, AgentCore is only
recommended.** The criterion's subject is Strands.

**Decision.** One `Container` interface, two backends.

| Backend | Isolation | Credentials | When |
|---|---|---|---|
| `LocalBackend` | subprocess per container | OS keychain | One operator, own machine. **Built first** |
| `AgentCoreBackend` | Runtime per-session isolation | AgentCore Identity | Multiple clients' keys on shared infrastructure |

Strands sits above both and is identical either way; the backend only decides where the walls
come from.

**Why this is the honest justification.** AgentCore appears **because hosting other people's
credentials changes the threat model**, not because the rules suggested it. "We wrote our own
sandbox" is the wrong answer once twelve clients' keys share a host; per-session isolation is
the right one. And OAuth flows cannot be completed interactively on a headless box, which is
what Identity handles.

**Cost, stated.** If `AgentCoreBackend` never ships, we forfeit the live-demo-link boost on
Technical and an easy differentiator in a field where few use AgentCore. The README then states
why local is correct for a single operator, which is an answer rather than a gap.

**Not a reason to change concept.** The challenge that produced this entry was about where keys
live. The concept was never in question: verified-empty lane, real workflow, a demo with a
finish line, and genuine work for a Strands agent to do.

---

## D14: Keychain locally, Identity only when hosted *(revises D13)*

**Context.** D13 concluded AgentCore Identity should be used in both modes, on the grounds that
it vends short-lived scoped credentials and gives an audit trail. Challenged immediately: *the
credentials still travel over the network.*

**Finding: the challenge is correct.** The data flow differs by one hop:

```
Keychain    at rest: this machine        in flight: machine → provider
Identity    at rest: AWS vault           in flight: AWS → machine → provider
```

TLS both ways, tokens short-lived, but the extra hop is real and the earlier entry glossed
over it.

**The counter-argument, kept because neither option dominates.** The two protect against
different threats. Against the network, keychain wins. Against device compromise, Identity
wins: a stolen laptop yields 48 long-lived provider tokens from a keychain, versus one scoped,
expiring workload token, and recovery is one central revocation rather than rotating 48
credentials across 4 providers for 12 clients by hand. Identity also logs every credential use,
which a password manager cannot.

**Decision.** `KeychainBackend` for local, which is the mode that gets used daily.
`AgentCoreBackend` (Identity + Runtime) only when hosted, where the credentials are in the cloud
regardless and hand-rolling a vault would be strictly worse.

**Result.** AgentCore appears exactly once, for a reason that survives being asked about. Both
backends sit behind the same `Container` interface, so this is reversible.

**Also settled:** AgentCore **Gateway is rejected.** It would expose provider APIs as generic
MCP tools, but the adapters carry the verification logic from §7 of the spec, which is the
product. Genericising them would remove the point.

---

## D15: Prior art: the switching problem is solved; the work is not

**Searched 2026-09-03**, GitHub-wide and not limited to the hackathon.

**`ibhugeloo/mcpwarden`.** TypeScript, created 2026-06-25, last pushed 2026-07-29, **0 stars**.
States this exact problem in the same words:

> *"Most MCP clients (Claude, Cursor…) bind one account per connector via OAuth. The moment you
> have two Supabase accounts, a personal + a client Vercel, or several Sentry orgs, you hit a
> wall."*

Its answer: replace the single connector with **N namespaced MCP servers, one per account**, a
local registry holding secret *references*, and a launcher that resolves each secret from
Vaultwarden at spawn so it exists only in the child process env. Read-only/scope policy per
server. It is a good design and it is honestly built.

**What it does not do, and these are the gaps this project occupies:**

1. **`mcpwarden profile use` selects one active context.** It removes the *re-login*, not the
   *switching*. You are still on one client at a time, so cross-client questions remain
   impossible.
2. **N servers, not N containers.** Twelve clients across four providers is 48 registered MCP
   servers and 48 namespaces in the client's tool list.
3. **It is a config manager and launcher, not an agent.** No workflow, no verification.
4. **No cross-account work at all.** which is the actual job here, because the output of one
   account is the input of another (Resend DKIM → Cloudflare DNS).

**`sagemcp` (44★) and `Super-I-Tech/mcp_plexus` (30★)** solve the *inverse* problem: hosting one
MCP server for many customers, SaaS-style. Many users, one operator. Not one operator, many
accounts. Different problem, despite the shared phrase "multi-tenant".

**Official provider MCP servers.** `cloudflare/mcp-server-cloudflare` (4.1k★), `supabase/mcp`
(2.9k★), `resend/resend-mcp` (566★): all bind a single account. The wall mcpwarden describes
is real and current.

**Nothing found at all** for agency/MSP multi-client cloud management, or for cross-provider
launch automation (DNS + DKIM/SPF + deploy verification). Three independent searches, no results.

**The most useful data point.** mcpwarden built the credential layer *as the product* and has
**0 stars after two months**. That is evidence for what was argued from taste earlier: the
plumbing alone does not attract users. The value is in the work done across accounts, not in
holding the keys.

**Consequence for the claims.** "Nobody has done multi-account MCP" is now false and must never
be said. The defensible claims are narrower and stronger:

- Existing work removes the re-login but keeps you on **one account at a time**.
- **No prior work performs a task that spans two client accounts**, which is what a launch is.
- **No prior work verifies the result.** the silent-failure catalogue in spec §7 has no
  equivalent anywhere found.

---

## D16: What the rules actually require, confirmed by the organisers

Three official answers from a Devpost manager, on the hackathon forum, 2026-09-03/04.

**Local-only is compliant.** Asked directly whether a locally-installed tool satisfies the
"available for testing" rule:

> *"A public repo with clear install instructions can serve as your 'test build.' **No hosted
> endpoint is required.**"*

This vindicates D4 and removes the AgentCore Runtime quota from the critical path entirely.

**Judges will not run the project.**

> *"**Judges will not install anything locally**"*, and *"Judges are not required to test the
> Project and may choose to judge based solely on the text description, images, and video."*

**This is the most consequential finding in the whole analysis.** Every criterion, including
Technological Implementation, is scored from the video, the description, the architecture
diagram, and a repo skim. The contest analysis treated the video as one criterion worth 20%.
It is in fact the entire evaluation surface. Consequences:

- The video is the deliverable; the code is what makes it truthful. It is not a last-week task.
- The architecture diagram is promoted: it is how a judge understands a system they will never run.
- Install-experience polish drops down the list. Correctness does not: a judge reading the repo
  can still catch a lie.
- **A check nobody sees run may as well not exist.** The verification catalogue must be visible
  on screen, not merely implemented.

**AgentCore is not required.** Quoted from Official Rules §4 in two separate threads:

> *"Deploying with Amazon Bedrock AgentCore is a smart architectural choice and will strengthen
> your Technical Implementation score, but it's not required."*

Only Strands is mandatory.

---

## D17: Bedrock is unreachable on this account; Gemini is the working host

**Context.** The AWS account is an **AISPL** (AWS India) account. Every Anthropic model on
`bedrock-runtime` fails:

> `AccessDeniedException: Model access is denied due to INVALID_PAYMENT_INSTRUMENT: A valid
> payment instrument must be provided. Your AWS Marketplace subscription for this model cannot
> be completed at this time.`

**Cause, established rather than guessed.** Bedrock model access is provisioned as an AWS
Marketplace subscription with contract pricing. AWS Marketplace has not supported stored card
payments for AISPL customers since March 2022, because of RBI payment-aggregator regulation.
UPI AutoPay (PhonePe) is enabled, Default, and green in Payment Preferences. It covers regular
AWS invoices but not the Marketplace subscription. IAM is `AdministratorAccess`, so it is not a
permissions problem. A 20-minute poll confirmed it is not propagation either.

**Also established along the way:**
- `anthropic.claude-sonnet-5` / `opus-5` return `AccessDenied: not available for this account`
  on **both** `us.` and `global.` inference profiles. An account-tier gate; unrelated to the
  above, and the use case form does not lift it.
- Bare model ids fail: `anthropic.claude-sonnet-4-5-...` needs an inference profile, hence the
  `us.` / `global.` prefix.
- The Anthropic **use case details form was submitted successfully** and that gate did clear,
  the error changed from `ResourceNotFoundException` to `AccessDeniedException`, which is how
  the real cause was found.

**Decision.** Raise an AWS support case (drafted; Basic support covers Account & Billing), and
**do not wait for it.** Run on **Gemini** via `strands-agents[gemini]`, key supplied through
`GEMINI_API_KEY` in the environment. `MUNIM_BEDROCK_MODEL` and the provider fallback chain remain,
so restoring Bedrock is a config change with no code change.

**Why this is not a compromise.** Strands is the requirement; the model host is not (D16). And
Strands advertises model portability. This exercises it under real duress rather than claiming
it. The README should say so plainly.

**The process lesson.** The cause sat in the API response for an hour while the probes printed
`e.response['Error']['Code']` and truncated messages to 95 characters. `INVALID_PAYMENT_INSTRUMENT`
appears ~40 characters into a message that was being cut at 95, visible, and not looked at. Same
shape as `google-agentic-cinema` D28: the answer was in the output and nobody read it. **Never
truncate an error message in a diagnostic.**

---

## D18: The control room is a window, not a dashboard *(reconciles D3)*

**The contradiction.** D3 is titled "It is an MCP server, not a CLI and **not a
dashboard**", and records that the design drifted to a dashboard three times and
was corrected each time. Then a control room was built and made a never-cut
component. The repository is public: a judge reading this log next to the video
finds the decision log arguing against the hero artefact.

**The distinction that resolves it.** A dashboard is a place you go to do work.
The control room is not: it has exactly one interactive element in the whole
application, the confirmation button, and it appears only when the agent has
stopped and needs a person. Everything else is read-only.

The operator works in their coding agent, which is what D3 settled and has not
changed. The room exists because a process that takes four minutes and touches
three companies is otherwise invisible, and the organisers confirmed judges will
not install anything (D16), so a component that cannot be seen earns nothing.

**The test of it.** If the room were removed, nothing about how the product is
used would change. If the coding agent were removed, there would be no product.
That is the difference between a window and an interface.

---

## D19: Reads may register a client; writes may not

**Context.** Naming a client, then connecting it, then checking it, is three
steps before anything useful happens. Nobody wants a setup wizard.

**Decision.** The first mention of a domain registers it. Saying the domain of a
client already registered reaches that client rather than creating a second.
A bare name that is not a domain and is not known is refused.

**Why the asymmetry is safe.** A DNS lookup is public: checking a domain reveals
nothing a stranger could not already look up, so there is nothing to protect on a
read. A write is different, and auto-registering a mistyped name on a write is
precisely how a change lands in the wrong account (F5). `connect_provider` still
refuses a client that was not named deliberately, and a test asserts it.

---

## D20: A check that fires on a platform domain is worth less than no check

**Found by running the catalogue against a real client's Vercel URL.** It
reported six failures, no SPF, no DKIM, no DMARC, no MX, no nameservers, no www
,  and every one was correct behaviour. Nobody sends mail from a `vercel.app`
address, and it has no nameservers of its own because it is a subdomain of the
platform.

**Decision.** Mail and delegation checks report "not applicable" on
platform-owned suffixes and say why.

**Why it matters more than it looks.** A tool that cries wolf on a preview URL is
one people stop opening, and then the checks that do matter go unread too. The
value of the catalogue is not how much it reports; it is that everything it
reports is worth a person's attention.

**Fixtures would not have found this.** Real client infrastructure did, in one
run. That is the argument for D12's "real data for building" in a sentence.

---

## D21: The fan-out claim, measured twice and corrected once

**The claim.** That answering one question across a dozen clients concurrently is
a differentiator, and that it is "parallel fan-out, not a for-loop."

**First measurement: 0.9x. Slower than serial.** One thread per client, each
still doing thirteen sequential DNS lookups inside it. The concurrency was at the
wrong level, and the claim was not earned.

**After fanning out at the level of the lookups** and deduplicating the records
several checks share:

```
6 clients, cold cache : 5.33s serial → 2.61s concurrent   (2.0x)
4 clients, warm cache : 1.23s serial → 2.26s concurrent   (0.5x)
```

**Both numbers stay in the code.** Against a warm resolver a lookup costs
microseconds and thread overhead dominates, so concurrency loses. The case that
happens: an operator asking about a dozen clients they have not touched today,
is the cold one, and there it halves the wait. Quoting only the 2.0x would be the
kind of unearned number `web-mcp-2026/docs/PROJECT-RULES.md` exists to prevent.

**Also decided: no Strands `Graph` here.** `Graph` genuinely runs nodes
concurrently, and one agent node per client would photograph well in an
architecture diagram. It would also make twelve model calls to do work that needs
zero, because the per-client work is deterministic DNS. That is feature-counting,
and the criterion says *skilfully*, not *thoroughly*.

---

## D22: OAuth stays, because the project outlives the contest *(revises the review consensus)*

**Context.** Three independent reviewers said cut OAuth. Their reasoning was
sound *for the contest*: judges will not install anything (D16), so a browser
login and a pasted token are indistinguishable on video. It earns nothing
visible and is the only work item gated on a provider approving a developer app.

**Decision.** Build it anyway, on the operator's call: the tool is open source
first and a submission second.

**Why that changes the answer.** `mcpwarden` solves the same credential problem,
asks you to paste a token per account, and has no adopters (D15). For a tool
strangers are meant to install, browser login is not polish. It is whether
anyone gets past step one. There is also a judge-shaped upside the reviewers
missed: Lahari Chowtoori sits on the panel as Open Source TPM, AI/ML.

**What it cost, stated.** Roughly a day and a half, paid for by cutting the
Vercel write path and the intervention handler.

**Where it is honest.** Resend is absent from the provider table because it
publishes no authorization endpoint. That is Resend offering nothing, not a
preference. Cloudflare's endpoints are recorded but unused until a client id
exists; their own MCP server reads one they were issued, and whether registration
is self-serve is unconfirmed. `TokenConnector` ships regardless, so a provider
approval that never arrives cannot block the submission.

---

## D23: The cross-account claim, measured against two real accounts

**Context.** D15's defensible claim is that no prior work performs a task
spanning two client accounts. Until 2026-09-04 that claim had never been run
against two real accounts, only against one account plus fixtures. A claim the
whole submission rests on, resting in turn on nothing.

**What was run.** Two genuine Vercel teams, connected by browser login minutes
apart, both grants held at once in the OS keychain under `(client, provider)`:

```
Acme Ltd: 2 projects   (acme-quote, acme-fe-webapp)
Kloudfirst:     15 projects   (kf-webapp, khatalens, lpg-inventory, …)

read concurrently in 0.94s, no logout between them
overlap: none
```

Reproducible by anyone with two accounts: `scripts/cross_account_probe.py`. It
fails if either account is empty and if the two share a project, because two
grants returning the same projects are one account wearing two names, which
would make the claim vacuous.

**What it cost to get there.** Four defects, each found by running the flow
rather than reading about it:

1. Vercel has two OAuth systems. `/oauth/authorize` serves "Sign in with Vercel"
   apps (`cl_…`); handed an Integration's `oac_…` id it answers *"The app ID is
   invalid"*, and even on success returns identity claims rather than access to
   a team's projects. The integration's external installation flow starts at
   `/integrations/<slug>/new`, takes only `state`, and exchanges at
   `/v2/oauth/access_token` with the secret and no PKCE.
2. The callback listener served exactly one request, so the first thing to touch
   the port consumed it: a favicon prefetch, a port scan, and the login failed
   with "no callback received" having received one.
3. `ClientRecord.providers` was a second copy of a fact the keychain held, and
   `munim connect` never updated it. Removed rather than synchronised.
4. `.gitignore`'s `.env.*` had been swallowing `.env.example` since the repo was
   created, so no clone ever carried the list of variables to set.

**What it also showed.** The first grant landed on the wrong team: the operator
picked the scope that did not own the client's project. Nothing in the tool can
catch that: the account picker is the one step only a person can get right,
which is why `connect` prints the team id it just authorised.

---

## D24: OAuth follows MCP's own authorization spec, including where it does not apply

**Context.** The operator's instruction was to keep the same experience MCP
already provides rather than invent one, and to prefer OAuth over pasted tokens
because the project is open source first. The MCP authorization specification
(revision 2026-07-28) settles most of what that means.

**What the spec says about a server like this one.** Its subject is an MCP
server acting as an OAuth *resource server*: a client authenticating *to* the
server over HTTP. Munim is local and speaks stdio, and the spec is explicit that
stdio implementations "SHOULD NOT follow this specification, and instead
retrieve credentials from the environment". So none of the resource-server
machinery applies: no protected resource metadata, no `WWW-Authenticate`
challenge, no audience validation of an inbound token, because there is no
inbound token.

What does apply is one sentence: "If the MCP server makes requests to upstream
APIs, it may act as an OAuth client to them. The access token used at the
upstream API is a separate token, issued by the upstream authorization server."
That is exactly Munim's shape, and the design already matched: a token per
`(client, provider)` in the OS keychain, never passed through, never returned to
calling code.

**Registration.** The spec names three ways a client obtains an id: Client ID
Metadata Documents, pre-registration, and Dynamic Client Registration. As of
2026-07-28 DCR is **deprecated**, demoted to MAY and "retained for backwards
compatibility"; Client ID Metadata Documents, where the client id is an HTTPS
URL the authorization server fetches metadata from, is the new SHOULD.

Cloudflare's discovery document advertises neither: no `registration_endpoint`
and no client-id-metadata support. That leaves pre-registration, which the spec
lists as a first-class mechanism, and the decision is to ship the id rather than
ask each user to make one. Cloudflare supports `none` for token endpoint
authentication, so the flow is a public PKCE client and its id is public by
design. A test refuses to let an id be shipped for any provider whose flow needs
a secret.

**Issuer validation.** The same revision requires clients to record the expected
issuer and compare it against `iss` in the authorization response before the
code is transmitted anywhere (RFC 9207), with a plain string comparison and no
URI normalisation. This was missing: `state` was checked and `iss` was not.
State proves a response answers our request; only the issuer proves it came from
the server the user was sent to. For a tool holding a dozen grants across four
providers that is the mix-up attack it exists to prevent.

**Where this leaves Vercel.** Vercel's integration flow needs a client secret,
so its id cannot ship and each operator registers their own integration. That
asymmetry is a property of Vercel's flow, not a preference, and it is recorded
here so nobody tries to "fix" it by committing a secret.

---

## D25: Wrapping the providers' own MCP servers, and why it was never considered

**Open, not settled.** Recorded because "why not wrap Cloudflare's MCP server?"
is the first question a sharp reader asks, and the honest answer starts with an
admission.

**It was never evaluated.** Twenty-four decisions, a spec and a plan, and the
option appears in none of them. Worse, it was in front of us: D15 describes
`mcpwarden` as "N namespaced MCP servers, one per account, a local registry
holding secret references, and a launcher that resolves each secret at spawn".
That is the wrapper approach. It was studied, four gaps were written down, and
the gaps were used to justify building adapters instead of building on it, when
three of the four (cross-client reads, the agent, the cross-account handoff) sit
above the transport and could have been built on top.

**The actual miss:** nobody asked whether the providers ship their own MCP
servers. For a project whose entire premise is MCP that is a first-principles
question, and it costs five minutes. Cloudflare has run OAuth-authenticated
remote MCP servers throughout, including the one the operator already had
connected while this was being built.

**What the check found, 2026-09-04:**

- `mcp.cloudflare.com/mcp` exposes 2,500+ endpoints through a search/execute
  Code Mode pair. DNS writes are reachable.
- Authentication is OAuth against Cloudflare, who are the client. **The
  registration step disappears**, along with the shipped-client-id question D24
  answers.
- `dns-analytics.mcp.cloudflare.com/mcp` is read-only, so there is no typed,
  narrower alternative for writes.
- **Correction, same day.** An earlier draft of this decision said Vercel had no
  MCP server. It does: `https://mcp.vercel.com`, remote, OAuth, implementing the
  2026-07-28 authorization spec, and able to deploy code. Written from memory
  rather than checked, in a decision whose whole subject is failing to check.
- Vercel's server carries a gate Cloudflare's does not: "Vercel MCP only
  supports AI clients that have been reviewed and approved by Vercel." A wrapper
  design makes Munim the client, so Vercel would have to approve it. That is a
  dependency on someone else's review queue, ten days before a deadline, for a
  capability we already have working.
- Connecting to Vercel MCP "grants the AI system you're using the same access as
  your Vercel user account". The integration we registered is scoped: Projects,
  Deployments and Domains read-only, environment variables read/write and only
  their names and scopes. Wrapping would widen what a client's grant covers, not
  narrow it, which runs against the whole premise (D5, D6).
- **Second correction, same day, same fault.** This decision also said Resend
  publishes no MCP server. It does: `https://mcp.resend.com/mcp`, remote, OAuth
  or bearer token, with tools to create, list, update, verify and remove sender
  domains. Twice in one document a provider's capability was asserted absent
  from memory rather than checked, in the decision whose whole subject is
  failing to check. Both were caught by the operator, not by the author.

  The rule that follows: a capability is never recorded as absent without a
  check in the same sitting, and the check is cited. "I do not believe X exists"
  is not a finding.

**So all three providers ship an MCP server**, which removes the argument that a
wrapper design would be a hybrid whichever way it went. What actually remains
against it is narrower and worth stating without the padding:

1. **Vercel gates its clients.** "Vercel MCP only supports AI clients that have
   been reviewed and approved by Vercel." A wrapper makes Munim the client.
2. **Wrapping widens grants.** Vercel MCP gives "the same access as your Vercel
   user account"; the registered integration is scoped to three read permissions
   plus environment variable names and scopes. D5 and D6 both point the other
   way.
3. **Where you wrap decides whether the claim survives**, as set out above: at
   the config level it is mcpwarden and the cross-client read is gone.
4. **The judgement is ours either way.** A generic execute tool will post a
   third SPF record; `merge_spf` is what refuses to.

That is a real case, and it is a smaller one than "nobody else has built this".

### Measured, 2026-09-04, rather than read

D24 concluded Cloudflare does not support Dynamic Client Registration, from
`dash.cloudflare.com/.well-known/openid-configuration` having no
`registration_endpoint`. That is the *dashboard's* authorization server. Each
provider's **MCP server** runs a different one, and every one of them supports
DCR. Third generalisation from a single check in one day.

Probed by following the MCP discovery chain from an unauthenticated request:

| Provider | MCP server | Registration endpoint | CIMD | `none` auth |
|---|---|---|---|---|
| Cloudflare | `mcp.cloudflare.com/mcp` | `/register` | yes | yes |
| Vercel | `mcp.vercel.com` | `api.vercel.com/login/oauth/register` | no | **see below** |
| Resend | `mcp.resend.com/mcp` | `api.resend.com/oauth/register` | yes | yes |

All three registrations were then run, not just read about. Each returned
HTTP 201 with `token_endpoint_auth_method: none` and no secret.

Vercel is why that distinction matters. Its authorization server metadata omits
`none` from `token_endpoint_auth_methods_supported`, so this code asked for
`client_secret_post` and was handed a public client regardless. The metadata
understates what the server does, and reading it produced a wrong entry in
`remote/servers.py` that only registering corrected. The note beside every
provider now records how it was verified, and a test refuses an entry that
records no confirmation, because a note holding a guess reads exactly like one
holding a measurement.

Cloudflare's was not read about but exercised: one unauthenticated POST returned
a `client_id` bound to `http://localhost:8976/oauth/callback` with
`token_endpoint_auth_method: none` and no secret. No human, no dashboard, no
shipped id.

Vercel requires a client secret, which DCR issues at registration time and the
client stores locally, so that is not an obstacle and certainly not a reason to
put a secret in the repository.

**The multi-account question, measured up to the consent screen.** Two
registrations run concurrently against `mcp.cloudflare.com/register`, one per
client, returned two distinct client ids and stored them in separate
directories, each reading back only its own. No collision and no dedupe.

That is the crux, and it resolves the way the protocol is built rather than the
way the tooling happens to behave. "One account at a time" comes from one client
id sharing one token store. Dynamic Client Registration issues a client id per
registration, so two clients are two applications as far as the provider is
concerned, and there is no shared state to clobber. `mcpwarden` reaches the same
place by spawning N servers; this reaches it by registering N clients inside one
process, which is what keeps a question that spans them askable.

What remains unverified is the sign-in itself, which needs a person: two browser
consents, as two different accounts. `scripts/probe_mcp_wrapper.py` does exactly
that and stops at listing tools.

**What this costs the argument.** The friction that justified building adapters,
that each operator would have to register an application per provider, does not
exist on the MCP path. D24's shipped-client-id machinery answers a question the
wrapper route never asks. What survives is only points 1 to 4 above, of which 2
and 3 are real and 1 is unverified: whether Vercel's "reviewed and approved
clients only" policy rejects a dynamically registered client is not something a
discovery document answers.

**What wrapping does not buy.** The adapter is not valuable for making HTTP
calls. It is valuable because `upsert` refuses to append beside existing
duplicates, `merge_spf` deletes before it writes so a partial failure leaves one
working policy rather than two ignored ones, and it reads the records back
instead of trusting two HTTP 200s. A generic `execute` tool will post a third
SPF record without complaint, which is the first item in this project's own
catalogue. Wrapping replaces the lines that make the call and keeps every line
that decides which call to make.

**The load-bearing question, now answered.** Whether two OAuth sessions to the
same remote MCP server can coexist in one client. Claude Code keys its MCP
authorisation state by *server name*, not by provider or account:
`mcp-needs-auth-cache.json` holds `"cloudflare-api"` and `"claude.ai Canva"` as
top-level keys. So two Cloudflare accounts can coexist, by registering the same
URL twice under two names. That is precisely `mcpwarden`'s model.

**Which makes the choice about where to wrap, not whether.**

- *At the client config level*, registering the provider's server once per
  client: multi-account for free, no code at all. It is also mcpwarden exactly.
  Twelve clients across four providers is 48 entries in the tool list, and
  nothing can read across two entries, so cross-client questions become
  impossible again. Every gap D15 recorded returns.
- *Inside Munim*, holding N MCP sessions and re-exposing them namespaced: the
  container, `find_across_clients` and the cross-account handoff all survive,
  because they sit above the transport. The cost is that Munim becomes an MCP
  client with per-session OAuth, which is the resource-server machinery D24
  records this project as not needing today.

The free version costs the claim the project rests on. The version that keeps
the claim is not free. Stated plainly so the choice is made on that basis rather
than on "wrapping is obviously better", which is what it looks like until you
ask where.

---

## D26: No AWS credits application

**Decided 2026-09-04 by the operator.** The credits form was submitted once
while unregistered on Devpost and would have needed re-submitting by Sep 11.

**Skipped, and the reason is not laziness.** Bedrock is unreachable on this
account through an AISPL and Marketplace billing limitation (D17), which credits
do not lift. Strands is model-portable, so the agent runs on Gemini with one
environment variable and no code change, and `MUNIM_PREFER=gemini` is now set
because build_model otherwise constructs a BedrockModel from stale credentials
and only discovers the problem when the call fails.

Credits would fund a host the account cannot reach. The Strands requirement is
satisfied by the SDK, not by which model answers, which is the point D17 made
and this confirms.

## D27: Reasoning is opt-in, and the gate is where the data would leave

**Decided 2026-09-04.**

Munim reached a model host whenever one happened to be configured. A
`GEMINI_API_KEY` in `~/.munim/.env` was enough for `check`, `work_on_client` and
`ask_across_clients` to send a client's provider data to Google, and nobody had
decided that. Having a key was treated as consent. For a tool whose subject is
credential isolation that is the wrong default, so agents are off until asked
for.

**The gate is inside `build_model`, not in each tool.** That is the boundary
where data would actually leave, and across all of `src/` it is the only place a
Strands model is constructed. One check there covers the three call sites that
exist and any written later, which a check per tool would not.
`tests/test_model_hosts.py` holds that as a rule rather than a list.

**The tools stay registered.** Omitting them from the MCP tool list when agents
are off was the alternative, and it is the move `across.py` makes for write
tools. It does not transfer. There, the model might ignore an instruction, so
absence is a security boundary; here a tool called with agents off returns early,
so absence buys no safety and costs discoverability, because an agent that cannot
see a tool cannot say how to turn it on. The stronger objection is that
`build_server()` runs once: conditional registration would make the tool list a
cached derivation of mutable state, and the two would drift the moment somebody
ran `munim config ai on`. Reading the setting at the point of use leaves one
source of truth, and the switch takes effect with no reconnect.

**The switch is never read from a file.** `load_dotenv` writes into the process
environment permanently and the MCP server loads once at startup, so a `MUNIM_AI`
in a `.env` would go sticky for the life of that process and silently beat every
later write. `munim config ai on` would report success while the running server
stayed off, which is the two-commands-disagree failure this project has hit
before. `doctor` reports a file that carries one.

**Two things were found while doing it, and both were older than this change.**

The privacy policy said "Nowhere else" after listing the providers and Munim's
own model host, and never mentioned that Munim is an MCP server whose every tool
result reaches the coding agent's model provider. The first draft of this work
would have made that page claim "nothing leaves the machine", which is worse than
what it said before. The disclosure is now on the page, and it is the more
important half of this change.

`pyproject.toml` pinned bare `strands-agents`, and Strands ships Gemini and
Anthropic as extras. Two of the three documented hosts raised
ModuleNotFoundError out of `build_model` while `doctor` reported them as fine,
because it only checked whether a key was set. An opt-in switch is worth nothing
if turning it on crashes, so the extras are declared, every branch catches
`ImportError`, `doctor` checks the backend imports, and `auto` skips a host it
cannot build instead of picking Bedrock and failing at the first call.

## D28: One keychain item per session was tried, and reverted

**Decided 2026-09-05.**

macOS files a keychain access rule per item per binary, and a session was stored
as four items: tokens, registration, endpoint and account. Fifteen clients
across three providers is a hundred and eighty items, so consolidating each
session into one looked like a four-fold reduction in approval prompts.

It was built, and it was wrong on three counts, each verified by running it.

`move_to()` wrote the destination blob wholesale, so moving a provisional
session onto a client erased that client's remembered account. That value is the
only input to the wrong-account guard, so the "this account is already
connected, refresh it" path silently disarmed the mechanism protecting D5. The
migration also deleted old items whose contents it had failed to parse, which
destroys a credential rather than leaving it for a person to look at. And it
made the common path more expensive rather than less: answering "who is
connected?" for a fifteen client estate took 825 keychain reads against 165
before, because every empty session paid four extra misses on every command.

The premise had also never been measured, which is not this project's standard.
Approvals are durable and per item, so the real cost may be a dozen clicks
spread over months. What actually makes prompts recur is the binary changing,
and the operator who reported this was running two installs on two different
Pythons. That is now a `doctor` check (D27's neighbour in `_one_interpreter`),
and it addressed the reported symptom without touching storage at all.

**A single keychain item holding one encryption key, with credentials in an
encrypted file, was considered and rejected.** It is neutral against a stolen
laptop and an unencrypted backup, since the key lives in the same login keychain
that already protects everything. Against a hostile script running under an
interpreter the operator has already approved it is worse: today an unfamiliar
client is a new item with no rule, so a client connected next month is still a
fresh decision, and one approved key removes every future decision point
including for clients that do not exist yet. For a tool whose subject is
credential isolation, that trades a usability annoyance for a durable grant.

What survived from the exercise is the read-only `KeychainTokenStorage.holds()`,
which is what lets `disconnect` name every item it will remove before removing
it.

## D29: The keychain prompts were three bugs, not a storage problem

**Decided 2026-09-05.**

macOS was asking for the login password on `munim` commands, and moving
credentials to `~/.munim/credentials.json` at mode 0600 was proposed to stop it.
Two independent reviews rejected it and both demanded the same thing first: a
measurement. The measurement ends the argument.

Two separate processes, nothing clicked, five credentials in the keychain:

```
$ munim clients
AcmeLtd                    -        cloudflare (mcp), vercel (mcp)
exit: 0
$ munim clients
exit: 0
```

There is no prompt. Apple documents why in `security add-generic-password -h`:
"the application which creates an item is trusted to access its data without
warning." The interpreter that ran `munim connect` is the one reading the result
back. `docs/COMMANDS.md` says the same thing under "Installing it, and why macOS
may ask for your keychain password", marked verified, and the proposal
contradicted it without citing it.

The prompts were three bugs, each fixed separately:

- The test suite read the operator's real keychain. `tests/conftest.py` swapped
  `munim.remote.storage.keyring` for the tests that cared and never
  `munim.container.keyring`, so more than twenty test files reached the real
  thing. Both doors are closed now, and closing them took the suite from 45
  seconds to 11.
- Two installs on two Pythons, a project venv and a pipx one, each asking for
  items the other had created. `doctor._one_interpreter` detects it now.
- Ad-hoc scripts run during this session under the wrong interpreter, which is
  the same bug committed by hand.

**What the file store would have cost.** The threat model written for it claimed
a backup was unchanged. That is false: Time Machine and hourly APFS local
snapshots would hold the credentials in the clear where the keychain puts
ciphertext in the same backup, and `os.replace` on APFS leaves prior versions in
unreclaimed blocks, so `munim disconnect` would stop being a delete. It would
also be pure loss on Linux and Windows, where Secret Service and Credential
Manager have no per-item, per-binary rule and therefore no prompt to remove.

**And the argument for it did not survive contact with D28.** D28 rejected a
single master key because it took per-item authorisation decisions from N to
one, for every client including ones that do not exist yet. A plaintext file
takes them to zero. The claim that D28's objection did not transfer was
reasoning assembled after the conclusion.

**If the prompts ever return**, the cause will be the interpreter changing
identity: a Homebrew Python upgrade, or a move between 3.12 and 3.13. `doctor`
reports it. Click Always Allow once per item, which is bounded and keeps the
strongest model. If that is still too much friction, an opt-in permissive ACL on
munim's own keychain items removes the prompt while keeping encryption at rest,
backup protection and stolen-laptop protection. That option was dismissed during
this discussion as "strictly worse than the file option", which was wrong: it is
strictly better on macOS, and the error probably decided the original call.

A plaintext file is not on that list.

## D30: Credentials move to a file, and D29 is reversed

**Decided 2026-09-05 by the operator, after D29 argued the other way.**

D29 concluded the keychain should stay, on the grounds that the prompting which
prompted the question had been three bugs rather than a storage problem, and the
measurement supported that. It still does: a single install does not prompt.

The operator chose the file store anyway, and that is the right call to be
theirs. The reason D29 was not the end of it is that "no prompt today" is not
"no prompt", and what makes it fragile is structural. macOS binds a keychain
item's access rule to a code-signing identity. A signed application keeps that
identity across updates; a pip-installed Python package cannot have one, because
the application macOS sees is the interpreter. So every Homebrew Python upgrade,
every move between 3.12 and 3.13, and every second install re-opens it. This
project hit all three in one day.

**What it costs, stated rather than buried.** Any process running as the
operator can read `~/.munim/credentials.json` without a prompt, where the
keychain would have asked. It is not encrypted, so a Time Machine backup or an
APFS snapshot holds it in the clear, and `os.replace` leaves prior versions in
unreclaimed blocks, which means `munim disconnect` is an unlink rather than an
erase. The same exposure as `~/.ssh/id_rsa`, `~/.aws/credentials`, and Claude
Code's own `~/.claude/.credentials.json`.

**What it buys.** One behaviour on every platform, no dialogs, no dependence on
an interpreter's identity, and enumeration: the orphan sweep used to shell out
to `security dump-keychain` and only work on macOS, because `keyring` cannot
list what it holds. A file can be read.

**What the earlier reviews were right about, and is built.** An inter-process
lock over the whole read-modify-write, because the MCP server refreshes tokens
while the CLI writes. Mode 0600 set on the temporary file before the rename, so
there is no window where it exists world-readable. `fsync` on the file and on
the directory. A refusal to overwrite a store that cannot be read, rather than
starting fresh and losing it. And adoption from the keychain that copies and
verifies but never deletes, because a copy left behind is untidy and a deletion
after a write that silently failed is not recoverable.

D29 stands as the record of why this was argued against, and this is what
overruled it. Both are worth keeping: the next person deserves the argument, not
just the outcome.


---

## D31: Forward the provider's tools instead of modelling them, and the isolation guarantee changes shape

**Date:** 2026-09-05

Munim could authenticate and diagnose. It could not change anything without
starting a language model of its own, and that model was the single point of
failure: Bedrock credentials expired, a Gemini key sat in a repo `.env` invisible
from any other directory, and agents are off by default, correctly, so every
write attempt no-opped. A day of real work on a live outage produced zero changes
made through Munim.

The model was doing a job nobody needed it to do. Munim is not a Cloudflare
client; it is a credential broker in front of Cloudflare's own MCP server. To
change a DNS record something has to pick a tool and call it with the right
arguments, and Munim's answer was to spin up a sub-agent to decide. But the thing
calling Munim is already an agent with a model. The operator is talking to a
coding agent, and Munim was starting a second one.

**Rejected first: a CLI verb per operation.** `munim dns proxied <client>
<record> off` reads fine until you count. Eleven providers, three to thirty-seven
tools each, and Cloudflare's `execute` takes JavaScript, so its parameter space
has no bottom. Every provider release would be a Munim release. Modelling one
tool's arguments as another tool's parameters is a losing game.

**Built: two tools that forward.** `list_provider_tools` asks a client's live
session what it exposes; `call_provider_tool` invokes one with that client's
credentials, arguments untouched. Munim does the part only Munim can do, and the
caller chooses what to call. No model host anywhere in this path, so the failure
that blocked every write stops existing. Every provider in `servers.py` becomes
reachable on the day this lands, not the three the mail tools happened to use.

**What this costs, and it is the part worth reading.** D5's write-within
guarantee was structural: a sub-agent built with one client's toolsets has
nothing to reach a second account with, so the boundary is a property of which
objects exist rather than an instruction a model is asked to follow. The
passthrough cannot have that shape, because there is no agent to build. The
guarantee becomes per call: `call_provider_tool` requires a named client and
resolves credentials from that client's id alone, so one call touches exactly one
account. Orchestration across clients becomes the caller's business, recorded
rather than prevented.

That is weaker on paper. Saying it is equivalent would be false. What it is
instead is auditable, which is why every call goes to the run log with the tool,
the client and the arguments before the result comes back, and why the tests
assert that record rather than assuming it. A read-only tool is logged as an
observation; anything else, including anything the provider did not annotate, is
logged as a mutation, because a call that might have changed something belongs in
the same list as one that did.

`ask_across_clients` keeps its sub-agent and its read-only filter unchanged.
Open-ended questions across a dozen clients are genuinely what an agent is for,
and the structural boundary is worth keeping where it still fits. `work_on_client`
stays too: this adds a way to work without a model, it does not remove the way
that uses one.

**`read_only` is reported, never enforced.** `list_provider_tools` passes on what
the provider says about each tool, including that it said nothing. Filtering
writes out here would defeat the purpose, because naming a client is what unlocks
writing. It is three-valued for the same reason: `toolsets._is_read_only`
collapses unknown to False because it decides what a cross-client agent may hold
and default-deny is right there, but nothing is being decided here, and flattening
"unannotated" into "writes" would make Munim assert something the provider never
said.

**It never opens a browser.** `allow_login=False` on every session. A tool call is
the least attended place in this system: it runs inside a coding agent, in
response to a model's decision, with nobody looking at a terminal. A consent
screen appearing there is worse than a failure, so an expired session is a
refusal naming the `munim connect` command that fixes it.


## D32: An agent path may not open a browser, and an answer may not describe what it did not read

Three faults shipped together and none of them failed where anyone could see it.
`ask_across_clients` and `work_on_client` raised `TypeError` the moment agents
were on, because they passed `backend=` to helpers taking `keyring=`. `check`'s
diagnosis agent looked sessions up by label in a store keyed by identity, matched
nothing for every client, and diagnosed with no provider tools at all. And every
test replaced the toolset helpers with `**k` stubs, so the real signatures had
never once been called.

**Two names, and the third time this cost something.** A `CredentialBackend` has
`get/set/forget`; a keyring is vault-shaped with `get_password/set_password`.
Calling both `backend` shipped in `health.py`, then in `server.py`, and then
here, where it took out the SDK the project is built on. The agent paths now
carry one seam, `keyring`, reaching `KeychainTokenStorage` and `auth_for` and
never `build_model`, which takes its own default. `uvx ty check src/munim/`
names this class of fault in seconds and is worth running: neither ruff nor mypy
is configured.

**Fixing a crash can be worse than leaving it.** `toolset_for` built its auth
provider with the SDK default `allow_login=True`. Dead code cannot open a
browser; live code can, and an unattended cross-client question that opens one
and blocks for five minutes is precisely what `NeedsLogin` exists to prevent. So
agent paths pass `allow_login=False` and the door that can log a person in is
`session_for`. The lesson is the ordering: the safety property had to land in
the same commit as the repair, not after it.

**Structured output has to see the account before it describes it.** Passing
`structured_output_model` to a single invocation registers the schema as one
more tool from the first turn, so the model can answer before calling any
provider and the loop stops there. The deprecated `Agent.structured_output()` is
worse: it never runs the tool loop and every backend hands it only the schema.
Both produce a validated `Answer` whose `evidence` no provider produced, which
is worse than the `TypeError` it replaced, because a traceback is honest.

So two calls. Phase one investigates with the provider tools and nothing else;
phase two shapes what phase one found. A finding survives only if that client's
own prefixed tools actually returned, read from `metrics.tool_metrics`. Checking
against the roster instead would be a spell-checker on client names, since a
client can be offered a provider whose every tool the read-only filter removed.
Anything that fails is returned under `discarded` rather than deleted: a model
naming an account it could not see is the most interesting event in the run, and
quietly dropping it would be the same lie in a tidier shape.

**And the prefix has to name the provider.** The client alone keeps two accounts
apart and does not keep one account's providers apart. Vercel and Supabase both
publish `list_projects`, so a client on both produced the same prefixed name
twice and Strands refused to build the agent. Found by running it; no test could
have, because a stubbed toolset has no tool names.


## D33: A way down a layer, and the three things that pay for it

An operator using Munim from another agent put the problem exactly: *the ceiling
on what munim can do for a provider is set by whoever wrote that provider's MCP
server.* Cloudflare publishes `execute`, so anything its API allows is reachable.
Vercel publishes a curated 37 tools, and there is no environment-variable write
and no way to attach a domain to a project, so those were reachable through no
tool at any layer. Munim was already holding the credential.

`call_provider_api` makes one HTTP call to the provider's own API. Two
independent reviews argued against building it a week before judging, and their
objections are the reason it is shaped the way it is rather than reasons it does
not exist.

**The host is asserted, because nothing else contains it.** `Container.http`
sets an httpx `base_url` and it is natural to read that as pinning the request.
Measured, it does not: an absolute URL wins outright and the client's
`Authorization: Bearer` goes with it, in cleartext if the scheme is `http`.
Without a refusal this tool is a way to send any client's credential to any
host. So the path is validated before the request is built and the built
request's host is compared with the provider's before anything is sent. The
first draft of the plan claimed the containment was inherited; it is entirely
new code, and saying otherwise in a docstring would have been worse than the
bug.

**Every call is a mutation in the log, whatever the method.** "Read-only by
default" would really mean "GET by default". `call_provider_tool` records an
observation only when the provider itself said `readOnlyHint` (D31), and
claiming the same from an HTTP verb is exactly the guess this codebase refuses
elsewhere.

**The response body is never logged.** `adapters/vercel.py` deliberately drops
environment variable values on the floor (D6) so a coding agent's context never
holds a client's secrets. A raw call to the same endpoint returns them, and
writing that to the run log would undo D6 through the back door. The log holds
the request and the status.

It works for cloudflare, vercel and resend, the three with an auth profile. It
is not the universal escape hatch the report asked for, and inventing base URLs
for the other eight would be guessing.

**And one credential is borrowed, on evidence.** Sending each stored MCP session
token at its provider's REST API gave Resend 403, Cloudflare 400, and Vercel
200. So `RemoteServer.rest_takes_session` is set for Vercel alone, defaulting
False, and a REST call there rides the session rather than asking for a second
credential. Refresh belongs to the SDK and only happens inside a session, and
`Container` is synchronous, so `session.freshen` opens and closes one first.


---

## D34: A graph, because the edge is the boundary

`check` explains what is wrong. `fix` acts on it, and the difference is that
something in somebody else's account changes, so the question worth designing
is not which agent does the repairing. It is what decides whether the repairing
agent is reached at all.

The thirteen checks run before the graph, as they already did, and the predicate
on the `triage -> repair` edge reads their results. It never reads what a model
said. Every term of it is deterministic: is there a failure this repair path can
actually produce a record for, does this client have the API keys the repair
needs, and is this a domain anybody is allowed to change. A model that is
confident, wrong, or talked into it cannot traverse an edge, because the edge is
not listening to it.

**Why not a swarm**, since `strands.multiagent` ships one and it would have been
easy. In a swarm the diagnosing model decides to hand off to the repairing one.
That is model-chosen control flow, and it is the one thing this product must not
have: D5 says reads may span clients and writes may not, D7 says enumeration is
deterministic and only judgement is model work. A swarm puts the write boundary
inside the model's discretion; a graph puts it in a predicate over DNS answers.
The contest analysis this project was planned against warns that "a swarm that a
single agent would have done better is a worse answer, not a richer one", and
that warning applies to picking either one for the wrong reason.

**The first version of this predicate was wrong, and a review caught it.** It
read `bool(findings)` where `findings` was the return of `run_checks`, which
returns every result regardless of status. It was a constant `True`: an `if`
statement wearing a graph, which would have routed every clean domain into the
repair node. There is now a test for a domain where everything passes,
specifically.

**A skipped repair says why.** An edge that does not traverse is silent, and in
the room's rail a silent step looks exactly like one that hung. That is the bug
the ghost stage cells were, and reintroducing it one layer up would be worse,
because here there really was a decision and it really had a reason.

**One correction to the SDK's naming, verified in the installed source.**
`cancel_node` does not skip a node. `graph.py:1010` raises `RuntimeError` after
yielding its cancel event, and that escapes `stream_async`, so `invoke_async`
never returns a result at all. The guard marks its own refusals so a deliberate
policy stop is not reported to the operator as a crash.

---

## D35: The model may not approve its own change

`mailplan.apply` has always refused to replace a record somebody published
without `approved=true`. The question this raises, once an agent rather than a
person is calling it, is where that boolean comes from.

**The two writing tools take no arguments at all.** Not a style choice. If
`apply_repair(plan_id)` existed, the model could pass the id of a plan approved
earlier, sitting in `~/.munim/plans/`, and inherit somebody's answer about a
different domain. With no parameters, the only influence the model has over the
write is whether to call it, and calling it is what raises the question rather
than answering it.

Four enforcement points, deliberately redundant, because the interesting failure
is a guard that silently stopped being registered:

1. **Schema.** No tool the model can see has an approval-shaped parameter, and
   a test asserts it against the schema Strands generates rather than against
   the source, because the schema is what the model is shown.
2. **The gate hook**, on `BeforeToolCallEvent`, which raises Strands' own
   interrupt and sets `cancel_tool` on a refusal.
3. **The tool body**, which re-reads the decision from disk rather than trusting
   the hook. A mis-registered hook must not become an approval.
4. **`mailplan.apply`**, unchanged, still refusing before any network call.

**An earlier draft failed this outright**, and it is worth recording because the
prose was already written and the code did not match it. The repair node was
given the provider's own write-capable toolsets alongside the gated tool, so the
model could have called `cloudflare_dns_update` and never touched the approval
path. Its tool set is now pinned by a test, because an allowlist that is only a
comment is not an allowlist.

**A plan that only creates records is not gated.** `Change.needs_a_person`
already draws that line and is already tested. Creating something absent is not
a judgement call; replacing something somebody put there on purpose is.

---

## D36: The room gets the one button it was always specified to have *(amends D18)*

D18 says the control room "has exactly one interactive element in the whole
application, the confirmation button, and it appears only when the agent has
stopped and needs a person". That element was written, styled and rendered in
`index.html`, and no click handler was ever attached to it. It has been shipping
as a dead control: a judge clicking it in a demo would have seen nothing happen.

So this is not a reversal of D18. It is the affordance D18 specified, finally
reaching something, and it is the second capability in this repository found
"present and inert" against the rule `ARCHITECTURE.md` states.

**D18's test still passes**, and keeping it passing is the constraint that
shaped the design. Its test is *"if the room were removed, nothing about how the
product is used would change."* A browser-only approval would break that, so the
decision has two writers: the room's button, and the existing
`apply_mail_setup(client, plan_id, approved=true)` from the coding agent. Both
write the same record. The room stays a window with one button rather than a
place you go to do work.

**A file, and no lock.** The room is a separate process on purpose, because the
MCP server is a stdio subprocess the coding agent kills on every reconnect. A
file is the only channel that survives one of them dying mid-question: if the
server is killed while waiting, the click still lands and the next
`apply_mail_setup` reads it. `record` renames a complete file into place, and
`os.replace` is atomic, so a reader sees nothing or everything and never half.
The 8.07 seconds of dead server this project shipped once had its root cause in
reaching for a locking primitive at all; the absence of one here is the fix.

**Running out of time is never approval.** Nobody said yes, so the answer is
absent, and the caller treats it as a refusal that can be retried.

**Loopback is not the same as safe.** Binding to 127.0.0.1 stops another
machine; it does not stop another tab. Any page the operator's browser visits
while the room is open could otherwise POST an approval for a client's DNS
change. The endpoint refuses cross-site requests, and that is what makes "it is
unauthenticated because it is local and single-user" a defensible sentence
rather than a hopeful one.

---

## D37: The check catalogue was DNS-only by accident, not by design

Asked why munim only looks at DNS, the honest answer turned out not to be a
design decision at all.

`adapters/vercel.py` has contained three deterministic checks since it was
written. They return the same `CheckResult` type as the thirteen DNS ones, and
they are tested. **Nothing in `src/` ever called them.** The only callers
anywhere were in `tests/test_vercel.py`, which is why nobody noticed: a test
calling a function looks exactly like production calling it. The control room
went further and reserved chips for two of them, with a comment claiming they
were "real on a launch with Vercel connected".

What was missing was not the checks. `Vercel.projects()` returns names and ids
and no domains, so nothing could answer "which project serves this domain".
That is one method, and it is now there, bounded so a busy account cannot turn
one check into fifty round trips, and refusing to match on a project name alone
because a project called `acme` serving a different domain is somebody else's
site.

**Three families now, and the labels are the honest part:**

  - **Thirteen about DNS**, needing no credential and no account. Anyone can run
    them against any domain.
  - **Three about Vercel hosting**, when a client has a Vercel key.
  - **One per connected provider**, asking the only party who can answer whether
    that account is still reachable. This is the family that generalises across
    all eleven with no per-provider code, and *"your Sentry connection expired
    on 14 August, so nobody has seen an error from your site in three weeks"* is
    a real finding nothing else here would have produced.

**Skip, never fail**, everywhere the answer is not known. D20 exists because a
check that fires wrongly is worth less than no check, and a test caught this
project committing exactly that: the first version reported "Vercel is down" as
"no project serves this domain". Both skip, only one is true, and an operator
acts differently on each.

**Per-provider check families for the other eight are declined**, rather than
deferred. There is no version of that which finishes and is defensible, and
inventing checks nobody measured is what this repository refuses everywhere
else.

Two guards so the orphan class cannot recur: every `check_*` in `adapters/` must
be named somewhere outside `adapters/`, and every hosting check must have a chip
in the room. The chip list is hand-maintained JavaScript and the checks are
Python; nothing else connected them.

---

## D38: The room describes the run it is watching, not the run it hoped for

The room drew one shape for every run: a six step rail, sixteen check chips,
and the word "Launching". Most runs are not that shape. Of the 493 in the log,
344 are a disconnect and 105 are a single provider tool call, and every one of
them rendered as six grey cells and sixteen grey chips describing work that was
never going to happen, under a heading naming work it was not doing.

That is the same fault as the seven ghost chips and the `deploy` and `domain`
ghost cells, told about a whole run instead of one step, and it survived both
of those fixes because both were fixed by hand-writing the producers into a
list. The list then went wrong in the other direction: it named six stages,
`src/` emits eleven, and the five it omitted are the ones most runs are made
of.

**Two kinds of run, and the room says which it has.** A `check` or a `fix` is a
pipeline, and gets the rail and the chips. A disconnect, a provider tool call, a
raw API call, a cross-client question, and `work_on_client` are one action each.
They get a heading saying what they are and no rail at all, because there is no
sequence to draw and inventing one is the lie the grey cells were.

**The heading is derived from what the run emitted**, not from which tool was
called, so it cannot disagree with the rail underneath it. A stage that was
reached and deliberately not run does not get to name the run either: a `fix`
whose repair edge refused says "Checking" over a rail that shows the repair
cell dashed, rather than "Repairing" over a rail saying no repair happened.

**The list is read out of the source now.** `tests/room/reduce.test.mjs` scans
`src/munim/**/*.py` for every way a stage gets set and asserts that each one is
either a cell in the rail or a declared single-action run. A hand-written list
of producers is a claim about the code that ages the moment someone adds a
stage, and this project has now shipped that same claim wrong three times. One
more test asserts the scan found something, because a regex that matches
nothing makes every assertion built on it pass forever.

## D39: A link into the control room only when the control room is up

`fix` returned `watch: http://127.0.0.1:8977` on every call and `check` and
`audit_all_clients` returned a `report` URL the same way. The room is a separate
process, deliberately, so that it outlives the MCP server the coding agent kills
on every reconnect. Nobody starts it for you. Most of those links went nowhere.

A link that fails teaches people not to click the one that works, and it costs
more than the missing link saves. The links are absent rather than empty, since
a caller checks for the key. `report_file` is a local path, is always written,
and is always true.

One place knows where the room is, which is what makes `--port` and
`$MUNIM_ROOM_PORT` mean anything: the three inline URLs could not follow a port
that moved. A test asserts no tool builds that URL by hand again.

## D40: Every run is reachable, and so is its report

The room could only ever show the newest run. `GET /api/runs` has returned all
of them since the first day and nothing called it: the page subscribed to
`/api/runs/latest/events` and that was the whole of its navigation. 493 runs,
492 of them unreachable.

The reports had the same fault from the other end. They are written to disk,
they are served at `/reports/{run_id}`, and nothing linked to one, because
nothing knew which existed. `/api/runs` now says which do, so the link is hidden
rather than offered and broken.

A picker of the fifty newest runs, and a report link when there is a report.
This is navigation, not a dashboard: it is for finding the run you just did.

---

## D41: The session is the credential *(closes the seam D33 measured)*

Connecting a client filed an OAuth session. Repairing that client asked for a
pasted API key for the same two accounts. Both statements were true and together
they undo the claim this project is built on: one connection per client.

D33 measured why. `mailplan` reaches Cloudflare and Resend through their REST
APIs, and those APIs refuse the token their own MCP servers issue: 400 from
Cloudflare, 403 from Resend, 200 from Vercel, which is why
`RemoteServer.rest_takes_session` is set for Vercel alone. The answer at the
time was a clearer error message naming both stores. `RESULTS.md` went further
and wrote down that everything reaching a provider's own MCP server writes
happily on the session, and that the split is not read against write but which
server is being talked to. It priced routing the repair that way and declined
it.

**Asked live on 2026-09-12, both servers can carry it.** Cloudflare publishes
three tools and `execute` is a general one: it runs a JavaScript arrow function
calling `cloudflare.request({method, path, query, body})` and returns the
Cloudflare API's own response object, `success`/`errors`/`result`, unchanged.
Resend publishes 104 tools including `list-domains`, `get-domain`,
`create-domain` and `verify-domain`, which is exactly the four endpoints
`mailplan` uses.

**So it is a transport, not a rewrite.** `Container.http` hands the adapters an
httpx client whose requests leave as MCP tool calls, and
`adapters/cloudflare.py` and `adapters/resend.py` are unchanged. The
read-before-write on `(type, name)`, the refusal to append beside an existing
record, the SPF merge and every test over them go on being true. That is the
only reason this was worth doing two days from a deadline: the part that writes
to somebody's DNS is the part that did not change.

**The model is not in this path.** The JavaScript is fixed and written here,
with the request serialised into it as ASCII JSON, so a record value is data
inside a string and never program text. The repairing agent still sees two tools
that take no arguments (D35).

**Resend answers in prose, and that is the risk.** A DKIM key arrives as an
indented line under a heading, and a third party's presentation layer can change
without notice. The failure that matters is not a crash: it is a value that
parses into something plausible and wrong and then gets published into a
client's zone. So `remote/resendtext.py` refuses rather than guesses. A records
section that parses to nothing is an error rather than an empty list, because an
empty list means "nothing to publish" and that reads as success. A value whose
shape contradicts its own heading, a DKIM key not starting `p=`, a policy not
starting `v=spf1`, stops the run with the text that failed.

**Two things this found in code that was already there.** `Resend.find` returned
a domain from `GET /domains`, which carries no `records` array, so a client
whose sending domain already existed produced a plan with nothing in it. Only
the second run was affected, and only a fixture that included records where the
real API omits them let that pass. And the repair edge asked `container.has`,
which reads the pasted-key store alone, so it would have refused the very
clients this now serves. It asks `container.can_reach` now: a key, a session the
REST API accepts, or a session with a route.

**Measured after building it**, against a live client with an empty key store:
the plan came back with two records `unchanged` and one to create, which means
the DKIM key parsed out of prose matched the one published in the zone byte for
byte. See `RESULTS.md`.

**What is not claimed.** The four Resend endpoints are the four `mailplan` uses;
anything else returns 501 naming `--token`, because pretending otherwise would
fail deeper in. And this has proved a *plan*. Nothing has yet been written to a
zone through it.

---

## D42: A provider that will not ask gets asked

`munim connect <client> gmail` never worked. It printed "Opening your browser",
opened none, stored no token, and reported success. Three separate fixes went in
before the cause was found, and each was real: the config file was not read by
every command, a tool listing was being taken as proof of a session, and the
refusal explained how to register an application to somebody who had.

The cause is one line of someone else's behaviour. The MCP SDK begins an OAuth
flow when a request comes back `401` with a `WWW-Authenticate` challenge, and
connecting only ever listed tools. Measured against Gmail on 2026-09-15:

```
tools/list                     200  no challenge
tools/call list_labels         401  www-authenticate: Bearer ...
tools/call <no such tool>      200  JSON-RPC error
resources/list                 404
```

**The third line is the one that decided the design.** Authorisation is checked
after the tool is dispatched, so a made-up name provokes nothing. There is no
harmless synthetic probe. Connecting has to call a real tool or Gmail will never
ask who you are.

**Declared, not guessed.** `RemoteServer.probe_tool` names one tool, set on
Gmail alone, following `rest_takes_session`: a measured fact with its
measurement written beside it. Empty everywhere else, so every other provider
calls nothing and behaves exactly as before.

**A first draft had a fallback** that would pick any tool the provider marked
read-only when none was declared. It was dropped for two reasons. It contradicts
saying which tool will be called before calling it, because connect would
announce `list_labels` and then call something else. And it would call an
unnamed tool on an unmeasured provider on the strength of that provider's own
hint. If Google renames the tool, refusing with "gmail no longer has
list_labels" is a better outcome than quietly calling `search_threads` instead.

**Silence is not permission.** `_read_only` is three-valued and `None` means the
provider said nothing, so the check is `is True` rather than truthiness. A
provider that annotates nothing gets no call.

**The result is discarded, and an error result is not a failure.** The token is
the artifact. A future reader will otherwise "fix" this by checking what came
back.

### Two things found while building it

**Presence of a token is not evidence that a login happened.** The guard added
the day before asked whether a token was stored. `SessionNeedingLogin` hides the
token from the SDK and deletes nothing, so on a reconnect the real store still
holds the old one: cancel the consent screen and the check passed on a token
from last week. It compares the stored token before and after now. Changed, not
present.

**Cancelling a login was already not a clean cancel.** The browser wait happens
inside an anyio task group, and `session_for` surfaced only `WrongAccount` and
`NeedsLogin`, so Ctrl+C came back wrapped and fell past the CLI's
`except KeyboardInterrupt` into a traceback. It had been true for Cloudflare all
along. The test that covers cancelling patched `connect_and_identify` to raise
directly, which never passes through a task group and so could not see it, the
same blind spot `passthrough.call_tool` already carries a comment about: a fake
session is not a task group.

## D43: A per-installation address and a login are two facts

Zoho could not be connected at all. Adding a client and pointing it at a Zoho
MCP endpoint left a registered client holding nothing, and the clients screen
reported "nothing connected", correctly.

The cause was one field carrying two meanings. `auth="url"` meant both **"each
installation has its own address"** and **"the address is the credential, so
there is no login"**. Those arrived together in the first provider that had
either, and nothing since had pulled them apart.

Zoho is both halves of the first and neither of the second. Measured
2026-09-15 against a live installation:

```
POST https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message   tools/list, no auth
-> 401  www-authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource"

that metadata names an authorization server under mcp.zoho.in/baas/…
which advertises  registration_endpoint  and  token_endpoint_auth_method: none
```

So it is per installation **and** it registers a client on demand. Under the old
model there was no route in: `munim connect --url` refused anything the probe
did not call `url`, and `munim connect` without `--url` read the address out of
the provider table, which is empty for a provider that has no one address.

**The fix is a second field, `per_client_url`, not a second kind.** The
alternative considered was recording the auth kind per client beside the stored
endpoint, on the reasoning that two installations might authenticate
differently. That was an assertion. Measurement says the kind is a property of
Zoho, because every installation's authorization server is reached the same way,
while the *address* is already per client and always was. One flag on the row
left every existing `server.auth` branch correct with no change; the per-client
version would have rewritten nine of them and added a keychain record shape that
has to stay readable as a bare string forever.

### The part that was nearly missed

`toolset_for` built an agent's client against `server.url`, which is the obvious
place to look. `auth_for` did the same thing one layer down, and that one is
worse: the SDK discovers protected-resource and authorization-server metadata
from the URL the OAuth client was built with, so the transport reached the right
address while the OAuth client reached the empty string. Fixing only the visible
one would have produced a connect that appeared to work and an agent that never
did.

It is also what makes two regions work. Zoho's authorization server is itself
per installation, so there is nothing shared to fall back on: a `.in`
installation and a `.com` one each authenticate against their own, discovered
from the address the client supplied.

### An earlier measurement that was wrong

The provider table used to say the path was the credential, "confirmed". It was
confirmed from one tool call that answered without credentials. That is a fact
about that tool, not about the server, and `discover.probe` still says so in the
note it writes: *"either the server needs none, the URL carries the credential,
or that one tool is public while the rest are not: only using it will say
which."* The note was right and the conclusion drawn from it was not. A
challenge is a positive answer; silence is not.

### What it cost next door

Four places decided whether a client was connected by asking whether it had
tokens. A client whose whole session is an address has none, so it read as
empty. `munim clients forget` removed the registry row and left the address in
the keychain filed under an id nothing could name again, which is the one of the
four that lost something rather than merely failing to carry it. The predicate
is now a single method on the store, so there is one place to be wrong about it.

## D44: A rubric that can be satisfied by vocabulary agrees with the answer

`tests/test_evals.py` opens with "the rubric has to score the action, not the
vocabulary", written because the obvious version of that file scores the
vocabulary and looks fine doing it. The fault it warns about was sitting in one
of the fixtures the whole time.

`dkim_missing` scored on `["resend", "provider", "dashboard"]`. Three sampled
answers passed. All three passed on a clause like:

> "...which helps email **providers** confirm your emails are real"

That is diagnosis. The fixture's own `why` says there is no correct value to
write here, that it comes from the mail provider, and that "the only right
answer is to fetch it". None of the three answers said to fetch anything. The
rubric was measuring whether a word appeared near a description of the problem.

It now scores the source of the value, the way `two_spf` scores the operation
rather than a keyword: any of the ways a model says "get it from Resend" or
"from your provider". Checked both directions on real samples before it landed,
because the first tightening was too narrow and rejected "Copy the DKIM record
Resend shows in the dashboard", which is a correct answer. A rubric that rejects
good answers is the same failure wearing the other sign.

The row went from `unreliable 2/3` to `fail 0/3`. Nothing about the agent
changed. The measurement stopped agreeing with it.

**The general shape, which is why this is written down rather than just fixed:**
a `must` list built from words that would appear in a good answer will also
match a bad one, because bad answers discuss the same subject. A `must` list has
to name the action, and the only way to know it does is to run both a good
answer and a real failing one through it. There is now a test that does exactly
that for this fixture.

## D45: A provider is a row, so contributing one is a pull request and not a plugin

The proposal on the table was a plugin API: a `Provider` base class, a
`[project.entry-points."munim.providers"]` group, and third parties publishing
`munim-provider-*` packages. The reasoning was that an ecosystem needs an
extension point.

It already has one, and the plugin would have been a worse version of it.
`munim servers add <name> <url>` calls the server with no credentials, reads
the `WWW-Authenticate` challenge, follows protected-resource and
authorization-server metadata, and works out which of the four auth kinds it
is. Eleven providers ship and only the first needed any Python. A provider here
is a frozen dataclass row, which is the design D11 and D25 arrived at.

So the plugin API would have moved the cost of adding a provider **up**, from
writing no code to publishing a package, and added a public API to keep stable
beside a probe that already does the job. It was aimed at a problem that is not
the one in the way.

The problem in the way is that discovery works and **sharing does not exist**.
`remember()` writes the derived row to `~/.munim/servers.json` and there it
stays. The next person to want that server repeats the probe, and the table
never learns. A design whose whole point is that providers are data had no way
to hand the data to anyone.

`munim servers export <name>` is the missing half. It prints the row as source,
in the quoting and wrapping `servers.py` uses, so the block pastes in without
being reformatted. `shareable()` is `remember()`'s own format rather than a
second one invented for export, so what leaves goes back in without
translation and `tests/test_server_export.py` proves the round trip against
all eleven rows rather than against one hand-written example.

**It refuses to print a credential.** `auth="url"` means the address *is* the
login, and the destination is a public pull request. `per_client_url` rows hold
no address at all, so those export fine, which matters: a per-installation
provider is exactly the kind somebody needs to contribute a row for. The one
refused combination is `per_client_url` with a non-empty url, which the
built-in rows never are and a hand-edited `servers.json` can be. Redacting
silently was the option rejected: it produces a row that looks complete, passes
review, and connects to nothing.

**What this buys that the plugin would not.** A contribution lands in this
repository rather than in somebody else's package, the contributor needs no
Python, and `tests/test_provider_docs.py` already fails when a row arrives
without a page, so the check was written before the lane existed.

## D46: A hint goes beside the answer, and only where something was measured

An operator deployed to Vercel, listed the projects, saw the new one, asked for
it by id and got 404. By name: 404. With the team slug: 404. Through Vercel's
own MCP tools: 404. Six calls hunting a wrong project id, a wrong team and a
wrong slug, for a project that was there the whole time (#46).

Nothing refused and nothing broke. Vercel returns 404 for a resource that is
out of a token's reach rather than 403, so "not permitted" arrives spelled
"you typed the wrong thing", and the caller goes looking for a mistake they did
not make.

Measured 2026-09-17 against a live session, and the answer was not the one in
the issue or the one on this project's own Vercel page:

```
GET /v9/projects                            200, 18 projects
GET /v9/projects?teamId=team_...            200, projects: []
GET /v9/projects/prj_...?teamId=team_...    404
GET /v9/projects/<name>                     200, the whole project
GET /v2/teams                               200, role OWNER of that team
```

Not scope. The credential reads the user, the team it owns and any project in
full. Every failing call carried `teamId` or `slug`, and every project in the
listing has `accountId` equal to the team that reports none of them.

**Three decisions came out of it.**

**The hint goes beside the answer, never instead of it.** `hints.about` returns
a sentence and the provider's own status, body and error are returned exactly
as they arrived. A helper that rewrote a result would be a second thing to
distrust at the moment somebody is already confused, and the whole failure here
was a layer being confidently wrong about what a response meant.

**It fires only on a measurement, never on a category.** A 404 from Cloudflare
gets nothing, because Cloudflare was never measured this way. A 403 from Vercel
gets nothing either: that is Vercel saying no, which is a different problem with
a different fix, and covering it with a sentence about `teamId` would be the
same fault this exists to remove. The module holds one provider's measured
table with its date, the way `servers.py` does, and a hint guessed from
documentation is worse than no hint because it sends somebody confidently in
one direction.

**The dead default was deleted rather than left alone.** `Vercel.__init__` took
a `team_id` that nothing supplied. It read as a feature waiting to be wired up
and was the opposite: wiring it up would have put `teamId` on every call in
`checks/hosting.py` and silently emptied every Vercel check, with a 200 each
time. A default argument is an invitation, and this one invited the bug.

**What this does not do.** `call_provider_tool` still forwards arguments
untouched, so Vercel's two project tools still fail. Stripping `teamId` behind
the caller's back would make Munim lie about what it sent, and the tools mark it
required, so there is no honest call to make. The hint names the REST route that
works instead. That is the ceiling set by whoever wrote the provider's MCP
server, which `rawcall.py` exists to get under, and it is the right place for
this to stop.

## D47: The plan was shaped by whichever provider supplied a row of it

`dmarc_policy` had failed on a real client's domain since the check catalogue
was written, and `fix` could not repair it. Not for that client, and not for any
client connected to anything.

`mailplan.plan` built the whole record set from one call:

```python
    sending, _ = await resend.ensure_domain(domain)
    wanted = Resend.cloudflare_records(sending)
```

So the plan was whatever Resend says a sending domain needs: DKIM, SPF, MX.
Resend has no opinion about DMARC, because DMARC is not a mail provider's
record. It is the domain owner's statement about what receivers should do, and
it is published in the same zone as everything else in that list.

**The shape of a repair was being decided by which provider happened to supply
one of its rows.** Nothing chose that. It fell out of building the plan from the
one adapter that had the values, and it left the catalogue able to diagnose a
fault that nothing downstream could act on, which is the specific gap `fix`
exists to close (D34).

It also made the two halves all-or-nothing on one credential. A client with
Cloudflare and no Resend got no plan, including for the record Resend has
nothing to do with, so a domain whose only fixable fault was its DMARC policy
had no route at all. That is why `~/.munim/decisions` stayed empty: across the
real clients, one had the fault and no Resend session, the other had Resend and
nothing to repair.

**Two rules now, and both come from what the record is.**

**Raise, never invent.** A DMARC record needs an `rua` for the failure reports
and nobody has told Munim which mailbox that is. Publishing `p=quarantine` with
nowhere to send failures moves a domain from "not protected" to "protected and
nobody is watching", which is worse and looks better. `dmarc_present` keeps
reporting an absent record as a fault, correctly, and it stays one a person
resolves.

**Keep every other tag, in order.** `rua`, `ruf`, `pct`, `sp`, `adkim`, `aspf`
were chosen by somebody. Rewriting the record from a template would drop the
reporting address, which is exactly the tag that tells them whether quarantining
was safe. The policy is replaced tag by tag rather than by a substitution over
the whole string, because `p=` is a prefix of `pct=` and a pattern loose enough
to find one finds the other.

The change is an `update` to a record somebody published, so it waits for a
person. That is the existing gate and it is the right one: mail that was failing
authentication silently starts being quarantined, and that is a decision with a
consequence rather than a missing record being filled in.

**What this does not fix.** The DKIM selector is still assumed to be `resend`
(`fix(dkim_selector="resend")`), which is the same coupling one level down, and
a domain sending through anything else is checked against a key that was never
going to be there. Recorded in `docs/ROADMAP.md` rather than fixed here.


## D48: The repair had the right change and the wrong order

D47 made a monitoring-only DMARC policy repairable. Run against the real client
it was written for, it proposed raising that policy to `p=quarantine`. That
client's other failing check is `dkim_present`.

Those two together are the common pair, and the order between them is the whole
of DMARC deployment advice. DMARC passes when SPF **or** DKIM aligns. With no
signing key, every message rests on SPF alignment alone, and the mail that fails
SPF alignment is ordinary rather than hostile: forwarded messages, mailing
lists, anything sent by a sender who is not in the record. At `p=none` those are
counted in a report. At `p=quarantine` they go to spam.

So the change was correct in isolation and wrong in sequence. Applied, it would
not have hardened that domain. It would have broken delivery for mail that is
genuinely theirs, silently, in somebody else's business, and the run log would
have recorded a successful repair.

**What this says about the design, which is why it is written down rather than
just fixed.** Every check in the catalogue is independent, deliberately: a fact
about a domain is decided by code and never by a model (D34), and each one
stands alone. Repairs are not independent in the same way. Two faults that are
each individually repairable can have an order between them, and `fix` had no
way to express that. The guard here is specific to this pair rather than a
general mechanism, and a second instance of the same shape is the point at which
one is worth building rather than now.

It also says something about where this was caught. Every test passed. Eighteen
of them, three mutation-checked, all agreeing with a change that would have
damaged a live domain, because they all encoded the same missing assumption as
the code. What caught it was running the thing against a real account and
reading what it proposed, which is the fourth entry in CONTRIBUTING's list of
what a good change looks like and the one easiest to skip when the tests are
green.

The key is matched on `_domainkey` rather than on the selector, because the
selector is the provider's choice and Munim only knows the one it assumes. A
domain signing through something else still signs, and refusing a safe change
because the key is not where we expected is the same fault wearing the other
sign.