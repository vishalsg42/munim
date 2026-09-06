# The tools your agent gets

Fourteen, and this is the whole surface. Anything not listed here is not
reachable, whatever else is in the repository.

| Tool | |
|## The passthrough: `list_provider_tools` and `call_provider_tool`

The two that make Munim able to change something without a model of its own.

Every provider here runs its own MCP server with its own tools. Cloudflare's has
three, one of which takes JavaScript; Vercel's has thirty-seven. Munim does not
wrap them. `list_provider_tools` asks a client's live session what it exposes,
and `call_provider_tool` invokes one of those tools with that client's
credentials.

```
list_provider_tools(client="Acme Ltd", provider="cloudflare")
call_provider_tool(client="Acme Ltd", provider="cloudflare",
                   tool="execute", arguments={"code": "..."})
```

**No model host is involved**, so this works with agents off. That is the point:
the model was doing a job nobody needed it to do. You are already an agent with a
model; Munim was starting a second one to decide which Cloudflare tool to call.

**Any provider Munim knows**, not only the three the mail tools use. Supabase,
Linear, Notion, Sentry, Netlify, Zoho, Gmail and Stitch are all reachable through
these two tools with no per-provider work.

**`read_only` is reported, not enforced.** `list_provider_tools` passes on what
the provider says about each of its own tools, including that it said nothing
(`null`). Filtering writes out here would defeat the purpose: naming a client is
what unlocks writing, and that is the D5 rule, not a rule about which tools exist.

**Every call is recorded.** `call_provider_tool` writes the tool, the client and
the arguments to the run log before returning, and gives you the `run_id`.
`launch_status` reads it back. A tool the provider marks read-only is logged as an
observation; everything else, including anything unannotated, is logged as a
mutation. That log is the compensating control for a guarantee that changed shape:
see D31.

**It never opens a browser.** A client whose session has expired gets a refusal
naming the `munim connect` command that fixes it. A tool call that pops a consent
screen in a session nobody is watching is not a tool call.

The same two are CLI verbs, and they are the first operational verbs Munim has
had:

```
munim tools "Acme Ltd" cloudflare
munim call  "Acme Ltd" cloudflare execute --args '{"code": "..."}'
```

Omit any argument and you get the picker, and `munim clients` navigates the
whole lot: clients, providers, tools, and one tool in full. `munim call` prints
the result to stdout and everything else to stderr, so piping it into `jq`
needs no flag, and `--args-file` or `--args -` feed it from a file or a pipe.

---|---|
| `list_clients` | every client and what each is connected to |
| `client_status` | what is known about one client |
| `add_client` | register one |
| `connect_provider` | store a pasted key, for providers with nothing better |
| `find_across_clients` | one deterministic question over all of them at once |
| `ask_across_clients` | one open question over all of them, read-only (needs agents on) |
| `audit_all_clients` | the whole catalogue against every client, silent when they all pass |
| `check` | the 13-check catalogue against a client or a bare domain (agents on adds the explanation) |
| `work_on_client` | do something inside one client's accounts, using their own provider tools (needs agents on) |
| `plan_mail_setup` | what setting up email would change, touching no DNS |
| `apply_mail_setup` | carry out a plan, with approval required to replace a record |
| `list_provider_tools` | what one client's provider account can be asked to do |
| `call_provider_tool` | call one of those tools with that client's credentials |
| `launch_status` | read a run back |

**Two of these need agents turned on, and they are off by default.**
`ask_across_clients` and `work_on_client` are agent loops end to end: with agents
off they answer with the command to turn them on rather than doing anything.
`check` is different, because its thirteen checks are deterministic and are the
half that matters: it runs them all either way and skips only the plain-English
explanation, saying so in its result and in the report.

They stay listed rather than disappearing when agents are off. A tool that has
been switched off is not the same as one that was never built, and a coding agent
that cannot see a tool cannot tell you the feature exists or how to enable it.
The guarantee that nothing reaches a model host lives one layer down, in the
function that builds the model, where it covers every caller.

Everything else here is deterministic and never touches a model at all.

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
Cloudflare that leaves **nothing at all**. Asked live on 2026-09-06, its server
answers:

```
docs      readOnlyHint=False  destructiveHint=False
search    readOnlyHint=False  destructiveHint=False
execute   readOnlyHint=False  destructiveHint=True
```

So all three are refused, not just `execute`. An earlier version of this page
said `docs` and `search` survived the filter, which was a guess about what a
documentation search ought to be annotated as rather than a reading of what
Cloudflare publishes. Asked to count DNS zones across clients, the agent has no
Cloudflare tool to reach for and will tell you which API would answer instead.

Claude Code's own `/mcp` lists those two as read-only, so it is not reading the
same field or is being more generous with it. Munim reports what the provider
says.

This is the boundary working, not failing. The cost is real and worth stating:
the open-ended cross-client question is limited by what each provider chooses to
annotate. `find_across_clients` and `audit_all_clients` are unaffected, because
they read DNS directly rather than through a provider's tools, and they are what
the domain-expiry and mail-health questions actually run on.

---
