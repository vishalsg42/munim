# Devpost submission

Paste-ready text for each field. Deadline 2026-09-14 17:00 PDT.

**Track:** Professional Agents
**Repo:** https://github.com/vishalsg42/munim

---

## Tagline

Look after a dozen small businesses' web and email setup from inside your coding
agent — without logging out of anything.

---

## Description

### The problem

One person maintains the websites and email for a dozen small businesses. The
clients own the Vercel, Cloudflare and Resend accounts and pay the bills; the
operator holds delegated access and does the work.

Every provider allows one login at a time. So the workaround is a separate coding
agent session per client — isolation built out of browser tabs and discipline.

That costs three things. Switching, on every action. No vantage point, so
*"which clients have a domain expiring this quarter?"* cannot be asked from
anywhere. And silent failure.

The third one is why this exists. Standing up a client means carrying values
between companies: Resend emits DKIM and SPF records that must be written into
Cloudflare. Get the A record wrong and the site does not load — you know in
minutes. **Get the SPF record wrong and nothing breaks.** The client's invoices
quietly stop arriving, and nobody finds out for weeks.

### Who it is for

The person who looks after other people's infrastructure — a freelancer, a small
agency, an IT contractor. And, through them, the businesses themselves: the
bakery whose invoices reach customers, the dentist whose appointment reminders
land in an inbox instead of a spam folder.

### Why it matters

The checks that catch this are not hard. There are just too many to run by hand
on every launch for every client, so nobody runs them, and the failures that
break nothing visible are the ones that survive longest.

### What it does

One MCP server, added once to whatever coding agent you already use. Each client
becomes a **container** holding only that client's credentials.

- **Read across every client.** One question, answered over all of them at once.
- **Write only inside one you have named.** A change loads one client's
  credentials; the others are not in the room.
- **Find what fails silently, then fix it properly.** When a domain carries two
  sender policies, the agent does not add a third. It combines them, keeping
  every sender, taking the strictest qualifier, and refusing if the merged policy
  would exceed the ten-lookup limit and therefore fail too. Then it stops and
  asks, because it is someone else's live DNS.

### How Strands is used

The division of labour is the design.

**The checks are deterministic.** Whether a domain has two SPF records is decided
by code reading a DNS answer. The model cannot contradict it, so it cannot invent
a record that is not there or argue a failing check into passing.

**The agent does what a rule engine is bad at.** Diagnosing *why* something
failed when the evidence is ambiguous — is the certificate missing because DNS
has not propagated, or because a CAA record blocks the issuer? Deciding whether a
person must be involved. And saying it to a business owner in words they can act
on, rather than in record syntax.

It also has to survive its own duration. A launch that polls DNS outlives a
single tool call, so every event is appended to a run log, progress is read from
that file, and an interrupted run resumes from what it already did — which is
what stops a re-run adding a second SPF record and causing the exact fault the
tool exists to catch.

### What is real

Every DNS result comes from a live lookup with the resolver named and timestamped
on screen. The demonstration runs against a domain the author owns, deliberately
broken the way this actually breaks — a leftover policy from a previous mail
provider with a second added beside it. Real client accounts appear nowhere: they
did not consent to a public repository or video.

**Not implemented:** Vercel and Resend write operations. They are absent from the
tool list rather than present and inert.

**Not deployed to AgentCore**, and the reason is worth stating: Bedrock is
unreachable on this account because AWS Marketplace cannot bill AISPL customers
for a model subscription, and AgentCore Runtime quota defaults to zero with a
multi-day approval. Strands is model-portable, so the agent runs on a different
host with one environment variable changed and no code change — which is the
property AWS advertises, exercised under duress rather than described.

---

## Built with

`strands-agents` · `mcp` · Python · React · Tailwind · Server-Sent Events ·
Cloudflare API · Resend · dnspython · Amazon Bedrock *(model host, when reachable)*

---

## Try it out

- **Repository:** https://github.com/vishalsg42/munim
- **Install:** three commands in the README; no account needed to run the tests
  or the check catalogue against any domain you like

---

## What is left

Vercel and Resend write operations. They are absent from the tool list rather
than present and inert.

The check catalogue is complete at thirteen, all of which need no provider
account: they read public DNS and make a public HTTPS request. Anyone can run
them against any domain, including yours, without an account or a key.
