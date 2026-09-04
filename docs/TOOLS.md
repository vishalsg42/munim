# The tools your agent gets

Twelve, and this is the whole surface. Anything not listed here is not reachable,
whatever else is in the repository.

| Tool | |
|---|---|
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
| `launch_status` | read a run back |

**Three of these need agents turned on, and they are off by default.**
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
