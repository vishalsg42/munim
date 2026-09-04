# Decision log

Why this project is shaped the way it is. Each entry records the decision, what drove it, and
what it costs, including the ones that were wrong first time. Reversals are kept rather than
tidied away, because the reasoning is the useful part.

Contest facts and the competitive scan live in `docs/HACKATHON.md`. The design lives in
`docs/superpowers/specs/2026-09-03-multi-client-mcp-design.md`.

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
diagram, and a repo skim. `docs/HACKATHON.md` treated the video as one criterion worth 20%.
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
Balaji Roofings: 2 projects   (balajiroofings-quote, balajiroofings-fe-webapp)
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
- Resend publishes no MCP server and Vercel's story is the integration flow
  already built, so any wrapper design is a hybrid rather than a replacement.

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
