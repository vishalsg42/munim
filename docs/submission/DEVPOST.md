# The project, written out

Drafted as a hackathon entry for the 2026-09-14 deadline, which passed unfiled.
Kept because it is the clearest statement of what this is and why it is built
the way it is, and because the next time it needs describing, to a judge, a user
or an employer, the answers are already here.

The two that matter most are under **How we built it**: why this is a graph and
not a swarm, and why the tools that write take no arguments.

---

## Tagline (one line)

One MCP server holding a live session with every client's cloud account, so one
agent can read across a dozen businesses and write inside only the one you name.

---

## Inspiration

One person looks after the websites and email of a dozen small businesses. The
clients own the accounts; the operator holds delegated access and does the work.

Every provider allows one login at a time. Connect a second client's Cloudflare
and the first one goes away. So the work is log out, log in, log out, and the
things that break are the quiet ones: an invoice that lands in spam for six
weeks because one DNS record is wrong, while the website is fine and nothing
looks broken.

## What it does

Munim is a local MCP server that holds a separate authenticated session with
every client's account at once, in one process. A coding agent can then **read
across every client and write inside only the client you name.**

It ships sixteen deterministic checks over DNS, hosting and provider
reachability; a Strands Agents graph that explains what a failure means and can
repair the mail setup; a control room that follows a run live in the browser; and
a plain-English report for the client at the end.

## How we built it

**Strands Agents, as a graph rather than a swarm.** Three nodes: triage reads the
evidence, repair writes, recheck confirms. The edge between triage and repair is
a predicate over the deterministic check results, not over anything a model said.
In a swarm the diagnosing model decides to hand off to the repairing one, which
is precisely the property this product must not have.

**The model is not allowed to authorise its own writes.** The two tools that
write take no arguments at all, so the model chooses whether to act, never on
what, and never whether it was allowed to. A test asserts the generated schema is
empty, because the schema is what the model is actually shown.

**Deciding whether a check passed is not model work.** Whether a domain has two
SPF records is a fact you can count. Code decides it; the model explains it. That
is why the agent cannot tell you your domain is fine when it is not.

**One connection per client.** Connecting a client files an OAuth session in the
OS keychain. Repairing that client used to need a second, pasted API key for the
same account, because the providers' REST APIs refuse the token their own MCP
servers issue. Requests now leave as the provider's own MCP tool calls, so the
session you already made is the only credential there is.

## Challenges we ran into

**An MCP server over stdio cannot print.** stdout is the JSON-RPC channel, so a
live view has to live outside the subprocess. Events go to an append-only file;
a separate process tails it and serves the browser. That also gave us replay and
an audit record.

**The tool proposed the exact fault it exists to detect.** Cloudflare returns a
TXT value quoted or bare depending on how the record was created. Every piece of
code looking for a sender policy asked `startswith("v=spf1")`, which is false for
`"v=spf1 ..."`. A published policy was invisible, so the planner offered to
create a second one. Found by running it against a real zone and not believing
the answer, because the checks said healthy while the plan said a record was
missing. One of them had to be wrong.

**Grey means "not yet", so nothing may be left grey.** The control room drew a
six-step rail and sixteen check chips over every run, including runs that emit
neither. A quarter of the grid sat grey through healthy runs, which reads as
hung. Skipped checks are now dashed with a reason, and the stage list is read out
of the source so it cannot drift again.

## Accomplishments we are proud of

Two real Cloudflare accounts open at once in one process, with credential
isolation enforced at construction. 989 tests plus 40 in the browser reducer. A
check catalogue that has never reported a false failure, because every path that
cannot answer skips instead. And a repair path where the boundary is an edge
condition and a zero-argument tool rather than a sentence in a prompt.

## What we learned

Verify the artifact, not the intention. Almost every real bug here was found by
checking the output: the generated schema rather than the source, the live zone
rather than the plan, the rendered chip grid rather than the reducer. Tests that
check your reasoning agree with you, and are wrong with you.

## What's next

Resuming an interrupted run, which the log already records enough to do and
nothing yet reads back. Per-provider check families beyond DNS and hosting. And
the repair path exercised against more than one zone.

---

## Links

- Repository: https://github.com/vishalsg42/munim
- Package: https://pypi.org/project/munim/
- Listing: https://glama.ai/mcp/servers/vishalsg42/munim

Every link is public and needs no credentials.

## Built with

`python` `strands-agents` `model-context-protocol` `cloudflare` `resend`
`vercel` `starlette` `oauth2` `dnspython`

## Disclosure

Built with AI assistance, as the rules require disclosing. The repository states
the same. No pre-existing code was carried in; the repository was created inside
the submission window.
