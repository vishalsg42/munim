# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org).

Entries describe what changed for somebody using munim. The reasoning behind
each decision lives in [docs/DECISIONS.md](docs/DECISIONS.md), and the numbered
references below point at it.

## 0.8.0

### Fixed

- **A DMARC policy set to monitoring can now be repaired.** `dmarc_policy`
  reports it as a fault and nothing could act on it, for any client, connected
  to anything. The plan was built entirely from `Resend.cloudflare_records`,
  Resend publishes DKIM, SPF and MX, and no mail provider has an opinion about
  DMARC, so no DMARC record ever entered a plan. The policy is now raised from
  the record that is published, keeping every other tag including the `rua`
  address the reports go to. It is an update to something somebody published,
  so it waits for a person: mail that was failing authentication silently
  starts being quarantined (#56).
- **A client with no Resend session gets the half of the plan that does not
  need one.** Planning refused outright on a missing Resend credential, which
  meant a client whose only fixable fault was their DMARC policy had no route
  at all. The Resend half is now reported as skipped, with the command to
  connect it, and the rest of the plan stands.
- **That skipped message named the client by id.** `munim connect "c_0123..."
  resend --token` is Munim's own bookkeeping appearing in an instruction
  somebody is meant to type. Third time in this codebase.

### Added

- **A DMARC record is never invented, only raised.** Publishing enforcement
  needs an `rua` address for the failure reports, and nobody has told Munim
  which mailbox that is. A domain with no DMARC at all stays a fault a person
  resolves rather than one Munim guesses at.

## 0.7.2

### Added

- **Munim is published to the official [MCP Registry](https://registry.modelcontextprotocol.io/).**
  The list of third-party servers in `modelcontextprotocol/servers` has been
  retired in favour of the registry, so that is where a client looking for MCP
  servers now looks. `server.json` carries the listing and a job in
  `publish.yml` publishes it on every tag, authenticating with
  `mcp-publisher login github-oidc`: a token minted for the occasion, no secret
  to leak and none to rotate, the same shape as the PyPI trusted publishing
  beside it. The registry verifies ownership by finding `mcp-name:` in the PyPI
  long description, which is `README.md`, so the marker lives there with a
  comment saying why.

## 0.7.1

### Added

- **A fourth builder post**, `docs/posts/04-the-quoted-record.md`, on the SPF
  quoting bug. The third post printed the line that had it, so this one is a
  correction as much as a write-up: Cloudflare returns a TXT value quoted or
  bare depending on how the record was created, a resolver reports neither the
  quotes nor the split, and a published sender policy was therefore invisible to
  the check built to count it. The planner then offered to publish a second one,
  which is the duplicate-SPF fault the tool exists to detect.

## 0.7.0

### Added

- **A Vercel 404 now says to drop the `teamId`.** Vercel returns 404 for a
  project the same credential reads fine without a team named, and a 200 with
  an empty list for a team that owns eighteen projects, so "not permitted"
  arrives spelled "you typed the wrong thing". Six calls went into hunting a
  wrong project id, a wrong team and a wrong slug for a project that was there
  the whole time. Results from `call_provider_api` and `call_provider_tool` now
  carry a `hint` beside the provider's own answer, which is returned exactly as
  it arrived. It fires only where something was measured: a 404 from another
  provider, or a 403 from Vercel, gets nothing (D46).
- **A successful `deploy_to_vercel` now warns that the site is not reachable.**
  A new project is created with Vercel Authentication on, so every deployment
  URL redirects to a login. The hint names the call that turns it off, because
  Vercel's own two tools for it mark `teamId` required and therefore cannot
  succeed on this credential.
- **`llms-install.md`, for a coding agent installing Munim on somebody's
  behalf.** Says what the README does not need to: that `munim connect` opens a
  browser the agent cannot complete and is the point to stop and hand back, that
  eight of eleven providers need no setup so there is no key to hunt for, and
  that `munim doctor` reporting almost nothing is the success case rather than a
  check that did not run. Written against the measured output of a fresh
  install, not from the README.

### Fixed

- **The Vercel provider page blamed the wrong thing.** It said the narrow
  `openid offline_access` scope was why reads came back empty. Measured against
  a live session, the credential reads the user, the team it owns and any
  project in full, and every failing call carried a `teamId` or a `slug`. The
  observation was right and the explanation was not (D46).
- **`Vercel.__init__` no longer takes a `team_id` nothing supplies.** It read as
  a feature waiting to be wired up and was the opposite: supplying it would have
  put `teamId` on every call in the hosting checks and emptied all of them,
  returning 200 each time.
- **`brand/EULA.md` said credentials are stored "in your operating system's
  machine".** The sentence had lost the word keychain at some point and read as
  nonsense in the one paragraph about where credentials go.

## 0.6.0

### Added

- **`munim servers export <name>`, so a provider you worked out can be handed
  to somebody else.** `munim servers add` probes any MCP server and derives how
  it authenticates, then writes the answer to `~/.munim/servers.json`, where it
  stayed. Export prints that row as source, quoted and wrapped the way
  `servers.py` is, ready to paste into a pull request. It refuses any provider
  whose URL is itself the credential, because the destination is public. The
  provider lane in CONTRIBUTING.md has the three files it takes, and
  `docs/providers/TEMPLATE.md` is the page to copy (D45).

### Fixed

- **`munim connect <client> zoho --url <endpoint>` now connects.** It was
  refused outright. Zoho gives each installation its own address *and* asks for
  a login, and munim's provider table could only record one of those two facts:
  `auth="url"` meant both "the address is per installation" and "the address is
  the credential, so there is no login". So `--url` refused an endpoint that
  wanted a login, and connecting without `--url` had no address to use. Those
  are two fields now, the probe decides, and `--url` records the address and
  then opens the browser if the address asks for one. Two clients can hold two
  installations in different regions (D43).
- **`munim connect <client> gmail` now actually connects.** It opens Google's
  consent screen and stores a token. Gmail answers a tool listing without asking
  who you are, and the OAuth flow only starts when a request comes back 401, so
  connecting never reached a login. It now calls one tool Gmail itself marks
  read-only, `list_labels`, purely to make it ask; connect says which tool
  before it runs and throws the result away. No other provider calls anything
  (D42).
- **The Gmail setup never enabled the API munim talks to.**
  `gmailmcp.googleapis.com` is a separate product from `gmail.googleapis.com`
  with its own switch, and `scripts/setup_google_oauth.py` only ever enabled the
  second. Anyone following the setup page had to find the first for themselves.
  It enables both now, and the provider page says why there are two.
- **A provider that refuses now says why instead of raising a traceback.** The
  transport calls `raise_for_status`, so a 4xx came back wrapped in an anyio
  group and printed sixty frames. Google puts its reason in the response body,
  which was the one thing those frames did not contain.
- **A cancelled reconnect no longer reports success.** Reconnecting hides the
  stored token rather than deleting it, so a check for "is there a token"
  passed on the previous one after somebody closed the consent screen. Connect
  compares the token before and after.
- **Ctrl+C during a browser login is a clean cancel again.** The wait happens
  inside a task group that wraps everything, so a cancel arrived as a group and
  ended in a traceback rather than "Cancelled. Your existing session is
  untouched." This had been true for every provider with a browser login.
- **A server you defined yourself keeps all of its settings.** Saving one wrote
  five fields by hand and silently dropped `rest_takes_session`, `scopes` and
  `header`.
- **`munim evals` scored a DKIM answer on the word "provider".** The
  `dkim_missing` rubric accepted any of "resend", "provider" or "dashboard",
  and three sampled answers passed it on the phrase "helps email providers
  confirm your emails are real", which is diagnosis rather than instruction.
  None of the three said to go and get the record from Resend, which that
  fixture calls the only right answer. It now scores where the value comes
  from, and the row reads `fail 0/3` rather than `unreliable 2/3`. The verdict
  changed because the rubric did; the advice was always this (D44).
- **A client holding only an endpoint is no longer treated as holding nothing.**
  Four places asked whether a session had tokens rather than whether it had
  tokens *or* an address. `munim clients forget` was the expensive one: it
  removed the registry row and left the address in the keychain under an id no
  command could name again. `merge` neither refused two clients holding two
  installations nor carried one that held only an address, and
  `ask_across_clients` could not see such a client at all (D43).
- **The Zoho provider page said the path was the credential.** It is not: the
  endpoint answers a tool listing with a 401 and a Bearer challenge. The
  original note was measured from a single tool call that answered without
  credentials, which says something about that tool and not about the server.

## 0.5.1

### Fixed

- **The refusal for a missing OAuth application explained how to register one,
  whatever the cause.** Run from the repository it worked; run from the home
  directory the same command said the provider "needs an application registered
  by hand", to somebody who had registered one. The client id was in a `.env`,
  the search walks up from the current directory, and from `~` it never reached
  it. The message now names the file that was read and the keychain that was
  checked, and says which of the two situations you are in. It also named a
  command that does not exist: the verb is `munim config app set`.

- **`munim connect <client> gmail` reported success without connecting
  anything.** It printed "Connected gmail for personal: 23 tools" while
  `munim clients` said nothing was connected, and `munim clients` was right.
  Gmail's MCP server answers a tool listing with HTTP 200 and no
  authentication, so a connect whose browser flow never completed still got
  twenty-three tools back and took that as proof of a session. The token is the
  only artifact that says a login happened, and now nothing claims success
  without one.

- **`munim connect <client> gmail` refused an application that was already
  registered.** `munim config` listed the Gmail client id on one line while
  `connect` told you to go and register one, in the same minute. Both were
  reading the truth: the values live in `~/.munim/.env`, `connect` loaded that
  file and `connect_via_mcp`, which is the path Gmail actually takes, did not.
  The file is now read once at the entry point, so every command sees the same
  configuration. This is the third time two commands disagreed about the same
  fact for this reason; the previous pair was `doctor` against `config list`.

## 0.5.0

The release where the agent stopped explaining and started repairing, and where
connecting a client became the only credential there is.

### Added

- **`fix`, a sixteenth tool.** Checks a client's domain and repairs what can be
  repaired safely. Built as a Strands `Graph` of three nodes, triage, repair and
  recheck, where the edge into repair is a predicate over the deterministic check
  results rather than over anything a model said. A swarm was rejected because
  model-chosen handoff is the one property this must not have (D34).
- **The two tools that write take no arguments.** The model chooses whether to
  act, never on what, and never whether it was allowed to. A test asserts the
  generated schema is empty, because the schema is what the model is shown (D35).
- **The control room's approve button works**, and a run can be answered from the
  browser or headlessly with `munim approve <run-id>` (D36).
- **Checks beyond DNS.** Three about Vercel hosting, and one per connected
  provider asking whether that account is still reachable. Sixteen in the grid,
  where thirteen were DNS-only by accident rather than by design (D37).
- **Every run is reachable.** The room has a run picker and links to the report
  for any run that has one; both the run list and the reports were served from
  the first week and linked from nowhere (D40).
- **`scripts/check_client.py` and `scripts/fix_client.py`**, which run the same
  code paths as the `check` and `fix` tools with no agent in front of them.

### Changed

- **A pasted API key is no longer needed to repair.** Cloudflare and Resend both
  refuse the token their own MCP servers issue when it is sent to their REST
  APIs, so repairing a client used to need a second credential for an account you
  had already connected. Requests now leave as that provider's own MCP tool
  calls, over the session you made in the browser (D41).
- **The room describes the run it is watching.** A disconnect or a single
  provider call no longer draws a six-step pipeline and sixteen check chips for
  work that was never going to happen, and the stage list is read out of the
  source so it cannot drift again (D38).
- **A link into the control room appears only when it is running.** `report_file`
  is a local path and is always written (D39).
- **Tool descriptions rewritten** for the model that reads them: what each tool
  returns, and which sibling to use instead.

### Fixed

- **A published sender policy was invisible when it was quoted.** Cloudflare
  returns a TXT value quoted or bare depending on how the record was created, and
  nothing normalised it, so `startswith("v=spf1")` was false for a real policy.
  The planner offered to create a second one, which is the duplicate-SPF fault
  this tool exists to detect; `merge_spf` could not see the record it exists to
  remove; and its read-back guard counted with the same blind spot.
- **A check that did not apply read as one that had not run.** Skipped results
  were dropped before logging, so four of sixteen chips sat grey through a
  healthy run. They are dashed now, with the reason on hover, and the report no
  longer ticks them green.
- **`munim reconnect` no longer removes a session before the new login
  completes.** Backing out, including with Ctrl+C, now costs nothing.
- **A re-run knows what to publish.** `Resend.find` read the list endpoint, which
  carries no records, so a client whose sending domain already existed produced a
  plan with nothing in it.
- **`project_for` no longer reports "Vercel is down" as "no project serves this
  domain".** Both skip; only one is true, and an operator acts differently on each.

## 0.4.0 and earlier

Released before this file existed. See the
[commit history](https://github.com/vishalsg42/munim/commits/main) and
[docs/DECISIONS.md](docs/DECISIONS.md), which covers every release.
