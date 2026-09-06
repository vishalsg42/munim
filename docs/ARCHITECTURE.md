# How Munim is built

The README says what it does. This says how, and why it is shaped this way.
The reasoning behind individual calls, including the ones that were wrong the
first time, is in [`DECISIONS.md`](DECISIONS.md).

```mermaid
flowchart TD
    A["<b>Coding agent</b><br/>Claude Code · Codex · Cursor · Windsurf"]
    A -->|"stdio, JSON-RPC"| B["<b>Munim MCP server</b>"]

    B --> C["<b>Checks</b><br/>13, deterministic<br/>public DNS and HTTPS<br/>no credentials"]
    B --> D["<b>Passthrough</b><br/>list_provider_tools<br/>call_provider_tool<br/><i>no model on this path</i>"]
    B --> R["<b>Repair</b><br/>plan_mail_setup<br/>apply_mail_setup"]
    B --> E["<b>Judgement</b><br/>Strands agent<br/>ask_across_clients<br/>work_on_client · launch"]

    D --> W
    R --> W
    E --> W
    W{{"read across every client<br/><b>every write names one</b>"}}

    W --> K1
    W --> K2

    subgraph ACME ["one client"]
        direction TB
        K1[["<b>Container: Acme Ltd</b><br/>bound at construction, cannot widen"]]
        K1 --> T1[("Acme's own registration<br/>and token")]
    end

    subgraph IVY ["another, on the same provider"]
        direction TB
        K2[["<b>Container: Ivy &amp; Fern</b><br/>bound at construction, cannot widen"]]
        K2 --> T2[("Ivy &amp; Fern's own registration<br/>and token")]
    end

    T1 --> P
    T2 --> P
    P["<b>The providers' own MCP servers</b><br/>cloudflare · vercel · netlify · supabase · resend<br/>sentry · linear · notion · gmail · stitch · zoho"]

    P --> H
    C --> H

    subgraph OBS ["what outlives the process"]
        direction LR
        H[("~/.munim/runs/&lt;id&gt;.jsonl<br/><b>the one source</b>")]
        H --> I["Control room<br/>separate process, SSE"]
        H --> J["Launch report<br/>for the business owner"]
    end

    classDef store fill:#eef2ff,stroke:#6366f1,color:#1e1b4b
    classDef gate fill:#fff7ed,stroke:#ea580c,color:#7c2d12
    classDef out fill:#f0fdf4,stroke:#16a34a,color:#14532d
    class T1,T2,H store
    class W gate
    class P out
```

Rendered for anywhere that does not run mermaid:
[`diagrams/architecture.png`](diagrams/architecture.png) and
[`diagrams/architecture.svg`](diagrams/architecture.svg). Regenerate both
from the block above with `mmdc`, rather than editing them by hand.

Two clients, one provider, one process. That is the whole thing, and it is not
engineered: each client registers separately with the provider, so as far as the
provider is concerned they are two applications and there is nothing shared to
clobber. A coding agent holds one account per provider because one client id
shares one token store.

The passthrough is the path most work takes, and there is no model on it. Munim
asks the provider which tools it publishes and forwards the one that was named,
with the named client's credentials. The agent that decides which tool to call is
the one already on the other end of the stdio pipe.

Two clients, one provider, one process. That is the whole thing, and it is not
engineered: each client registers separately with the provider, so as far as the
provider is concerned they are two applications and there is nothing shared to
clobber. A coding agent holds one account per provider because one client id
shares one token store.

## Five decisions carry the design

**Enumeration is deterministic; only judgement is model work.** The checks decide
pass or fail from a DNS answer. The agent cannot contradict them, so it cannot
invent a record or argue a failing check into passing. What it does is the part a
rule engine is bad at: working out *why* something failed, and saying it to
someone non-technical.

**Policy and construction are separate, and the gate is where data leaves.**
`settings.py` decides whether Munim may think, on which host, with which model
and key. `agent/model.py` does the construction and refuses when policy says no.
Deciding should not require the ability to build, and `doctor` and the CLI both
need the answer without importing Strands. The refusal lives in `build_model`
because that is the only place in `src/` a model is constructed, so one check
covers every caller including ones written later. Agents are off by default:
having a key is not the same as deciding to use one (D27).

That switch controls Munim's own model host and nothing else. Munim is an MCP
server, so every tool result also reaches whichever model the coding agent runs
on. That is a property of the transport rather than a setting, and the privacy
policy says so.

**The run log is the one source of truth.** The MCP server speaks JSON-RPC over
stdout, so it cannot print progress there without corrupting the protocol, and
the subprocess dies whenever the coding agent reconnects. Writing events to a
file instead means the control room survives a restart, can be opened mid-run
with full replay, and an interrupted launch leaves a record to resume from.

**A container is bound to one client at construction and cannot widen.** `"acme"`
versus `"acme-uk"` would otherwise be a *successful* mutation on the wrong
account. Container construction fails on an unregistered name, and the raw
credential is never returned to calling code: a session carries its own
registration and its own token, filed under `(client, provider)`, so two clients
cannot borrow each other's. Where an adapter is used instead it receives an
authenticated HTTP client, so no log line or stack trace can leak a token.

**Read across, write within is a property of which tools exist.** A tool that
spans clients is built from only those the provider marks `readOnlyHint`, default
deny, so one that changes something is not present to be called. It used to be a
line in a system prompt, and an instruction is not a boundary.

## Identity is an id, not a name

Credentials are filed under a client id (`c_<hex>`) that never changes. The name
is a label for display, and renaming a client cannot orphan a session.

This was not free. Three separate bugs came from conflating the two: a registry
that minted a fresh id on every read and scattered 36 copies of one live
credential; a connect path that stored tokens under the label while storing the
account marker under the id; and a consent screen that named the application
after the id, removing the one check a person can actually perform. All three are
fixed and tested, and the tests exist because the bugs did.

## Why there is no AgentCore deployment

Worth stating rather than leaving as a gap. Bedrock is unreachable on the
development account: AWS Marketplace cannot complete a model subscription for
AISPL (India) customers, because RBI rules prevent it storing card details, and
Bedrock model access is provisioned as a Marketplace subscription. Separately,
AgentCore Runtime quota defaults to zero and increases take several days.

Strands is model-portable, so the agent runs on a different host with one
environment variable changed and no code change. That is the property AWS
advertises; this exercised it under duress. Restoring Bedrock is
`MUNIM_BEDROCK_MODEL` and nothing else.

## Nothing is stubbed

A capability that is not implemented is absent from the tool list rather than
present and inert. Resend, for example, has no OAuth flow anywhere in this
codebase because Resend publishes no authorization endpoint, not because it was
skipped.
