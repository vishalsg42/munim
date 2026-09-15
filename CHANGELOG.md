# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org).

Entries describe what changed for somebody using munim. The reasoning behind
each decision lives in [docs/DECISIONS.md](docs/DECISIONS.md), and the numbered
references below point at it.

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
