# Roadmap

Written down because the gaps are known, not because they are planned away. A
gap stated plainly is worth more than a gap discovered by whoever installs this.

## Not yet done

**A store write can still stall the server's event loop, for up to ten
seconds.** Reported by an operator as every tool vanishing mid-session after
they re-authenticated, and reproduced: another process holding the credential
store stalled a live MCP server for exactly as long as it held it, 8.07s of
dead server for 8s of contention. `vault._Lock` took `flock(LOCK_EX)` with no
timeout, and every store write takes it, including the ones the server makes
from inside its loop when a probe refreshes a token.

That wait is now bounded and explains itself instead of running forever, which
is the difference between a slow tool and a server that looks dead. It is not
the whole fix. The loop still blocks for as long as the other writer takes, up
to the bound, because the write path is synchronous and the SDK calls it from
async code. Doing it properly means the async callers acquiring without blocking
the way `vault.Single` already does for the refresh lock, and that is a change
to the `TokenStorage` write path rather than a flag.


**Linux and Windows.** Developed on macOS and the platform assumptions have been
found rather than guessed at. `doctor` now reports whether a keychain backend
exists instead of raising, credential reads degrade to "nothing connected" rather
than a stack trace, and the `claude` executable is resolved through
`shutil.which` because on Windows it is `claude.cmd`. What remains untested is a
real run on either: a headless Linux box needs `keyrings.alt` or a secret
service, and nobody has yet confirmed the browser callback and the keychain
behave there. CI runs the suite on Linux, which is a start and not the same
thing.

**Local stdio servers.** Munim holds sessions with remote MCP servers over HTTP.
A stdio server is a process, not an endpoint, so holding one per client means
spawning N processes with N environments, which is a different design. On one
real machine, 20 of 26 configured servers were remote and 4 were stdio, so this
is a real gap rather than a theoretical one.

**Providers whose authorization server will not register a client.** Every Google
MCP server, which is Gmail, Stitch, Drive and Calendar, authenticates against
`accounts.google.com`. It advertises no registration endpoint and requires
`client_secret_post`, so somebody has to be a registered application. In a coding
agent that somebody is the agent itself: a Gmail connector works without setup
because the client, not the operator, holds the Google registration. Munim is a
client too, so it needs its own, and that is a decision about carrying a Google
credential rather than a thing to slip in.

**Watch mode.** `audit_all_clients` is the shape of it and runs on demand.
Running on a schedule and telling somebody only when the answer changes is the
version an operator would actually leave on.

**Vercel and Resend sessions.** Registration is confirmed against all three
providers, and only Cloudflare has been connected and used against two live
accounts. The other two are expected to work and that is not the same as
knowing.

**Resuming an interrupted launch.** The run log records enough to do it and
nothing reads it back for that purpose.

Re-running a launch after a partial failure does not duplicate anything, which is
the property people usually mean by resume: every write reads what is there first
and updates in place, and the SPF merge removes the leftovers before writing, so
a failure part-way leaves one working policy rather than two that receivers
ignore. Picking a launch up from where it stopped is a different thing, and it is
not built.

**Cloudflare DNS writes against a live zone.** The idempotent upsert and the SPF
merge are tested, including partial-failure behaviour, but have not been run
against a real zone. That is the last claim in this project still resting on
tests alone.

**Open-ended cross-client reads on providers that do not annotate.** A
cross-client toolset is default-deny on `readOnlyHint`, and a provider that
annotates nothing contributes nothing. Counted against the live tool listings:

    cloudflare    3 tools,   1 read-only   (documentation search)
    vercel       37 tools,  23 read-only
    resend      103 tools,  43 read-only

So Cloudflare cannot take part in an open cross-client question at all, which
matters because it is the provider most clients here are connected to. An
earlier version of this entry said the filter left documentation search, which
was optimistic in the wrong direction: `docs` is unannotated too, and `search`
is the one that survives. The filter is right; the gap is that a provider
offering read-and-write tools cannot participate. Fixing it properly means a way
to prove a call is a read before making it, which is a per-provider judgement
and not a flag.

The practical consequence, worth knowing before writing a demo: a cross-client
question has to be one the annotated providers can answer. "Which clients have
an unverified sending domain?" is answerable through Resend. "Which domain
expires this quarter?" is not answerable by any tool at any provider here,
because registration expiry is not something their MCP servers publish.

**Scopes on the MCP route are the provider's choice, not ours.** Same cause.
Connecting Supabase grants `database:write`, `storage:write`,
`edge_functions:write`, `environment:write` and `secrets:read`, because that is
what its resource advertises, and nothing in a client can ask for less.
`RemoteServer.scopes` records what Munim would ask for and is honoured on the
application route, which builds its own authorize URL. The one exception is
`offline_access`, which SEP-2207 explicitly permits a client to add and which
`munim/remote/offline.py` does. For a tool whose subject
is credential isolation this is the least comfortable thing in the project, and
it is a property of the spec rather than of this implementation.

**Gmail is capped at 100 users until the app is verified.** The seven day
session expiry that Testing imposes has been removed: the app is published, and
that needed no verification. What remains is a cap of 100 users granting
permission while the scopes are unapproved, which Google says "cannot be reset
or changed", and an unverified app warning screen. The cap does not apply once
the scopes are approved, so verification lifts it rather than merely softening
the warning. Getting there needs a homepage and privacy policy on a Search
Console verified domain, a demo video, and probably a CASA assessment costing
$500 to $4,500 renewed annually. Whether CASA applies to a local client that
talks only to Google is not documented either way.

**Adding Gmail test users is manual, and there is no API.** Every mailbox to be
connected must be listed in the Cloud Console by hand, capped at 100 for the
lifetime of the app with removals still counted. No Google API manages the
consent screen audience: the IAP brand resource has no test-user field, and the
IAP OAuth Admin API that once managed brands was shut down in March 2026. For an
operator with a dozen clients this is a real ceiling on Gmail specifically.

**A wrong-account guard that survives a token refresh.** Every session verifies
which account it belongs to before use. What is not proven is the behaviour when
a refresh token silently returns a session for a different account, which should
be impossible and is the kind of thing that is impossible until it happens.

**Shell completion, and machine-readable output beyond `clients`.** Client names
and provider names are exactly what an operator cannot recall, which makes
completion the highest-value missing affordance here, and there is none.
`munim clients --json` exists; `servers` and `doctor` both produce structured
data that is currently prose only, and `doctor` is what a script would want to
gate on.

**`--yes` is a convention on one command, not the surface.** `disconnect --all`
lists what it will remove and asks. `clients forget` destroys and `clients merge`
moves credentials between identities, and neither confirms nor takes `--yes`.
Either they should, or the flag is a patch rather than a rule.

