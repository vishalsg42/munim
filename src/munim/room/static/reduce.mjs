/* The control room's state machine, and the only part of it worth testing.
 *
 * A plain ES module so the page can `import` it with no build step and
 * `node --test` can import the same file with no install. One source of truth
 * for the reducer, which is what the React version had and what a rewrite
 * would otherwise quietly lose.
 */

// Fixed order. Chips render greyed at these positions from the first frame and
// light up in place - nothing is inserted, so nothing moves and the eye can
// track one cell changing.
// Only checks something actually emits. This listed twenty and the catalogue
// emits thirteen, so seven cells sat grey through every run: five had no
// producer anywhere in the codebase, and a permanently grey chip reads as a
// step that hung rather than one that does not exist. `cert_www`,
// `env_redeployed`, `return_path`, `site_responds` and `ssl_mode` are gone.
//
// The three Vercel ones now have a producer. For most of this project's life
// they did not: the checks existed in the adapter, were tested, and nothing in
// src/ called them, while this comment claimed they were "real on a launch with
// Vercel connected". `munim/checks/hosting.py` is what made that true, and it
// resolves the project from the domain, which is the line that was missing.
// `tests/room/reduce.test.mjs` pins this list against the producers.
export const CHECKS = [
  "spf_single", "spf_lookups", "dkim_present", "dkim_chunking",
  "dmarc_present", "dmarc_policy", "mx_present",
  "ns_delegated", "cert_valid", "caa_allows",
  "apex_resolves", "www_redirect", "https_enforced",
  "deploy_current", "env_applied", "env_scoped",
];

export const CHECK_LABELS = {
  spf_single: "One SPF record", spf_lookups: "SPF lookups ≤ 10",
  dkim_present: "DKIM published", dkim_chunking: "DKIM chunking",
  dmarc_present: "DMARC present", dmarc_policy: "DMARC policy",
  mx_present: "MX present", return_path: "Return-path",
  ns_delegated: "Nameservers", cert_valid: "Certificate",
  cert_www: "Certificate (www)", caa_allows: "CAA allows issuer",
  apex_resolves: "Apex resolves", www_redirect: "www → apex",
  https_enforced: "HTTPS enforced", ssl_mode: "SSL mode",
  deploy_current: "Deploy current", env_scoped: "Env scope",
  env_applied: "Env applied", site_responds: "Site responds",
};

// `diagnose` is where the agent works out what a failure means. It was missing
// once, so the one step that makes this an agent rather than a DNS script never
// appeared in the rail: its events reached the log and nothing else.
// Same rule the chip list above already follows, applied to the rail: only
// stages something actually emits. `deploy` and `domain` were listed here and
// **nothing in src/ has ever written either**, across every run ever recorded.
// Two cells that can only ever be grey, and a grey cell reads as a step that
// hung rather than one that does not exist - which is the exact confusion the
// seven ghost chips were removed for. `dns` stays: `adapters/cloudflare.py`
// emits it. `tests/room/reduce.test.mjs` pins this against the producers now,
// so the next one cannot be added by hand and left unwired.
// In the order a `fix` run touches them. `dns` and `mail` are **nested inside**
// `repair`: mailplan hardcodes stage="mail" in a dozen places and the
// Cloudflare adapter emits "dns", and threading a stage-override through tested
// code to make a rail look tidier is the wrong trade. So the rail can light 4
// and 5 while 3 is still current. That is honest about what is happening.
//
// A `check` run touches only `verify` and `diagnose`, which is what CHECK_ONLY
// below is for: it is a check, not a launch, and the room says so rather than
// leaving four cells looking like steps that hung.
export const STAGES = ["verify", "diagnose", "repair", "dns", "mail", "recheck"];

// A check run emits `verify`, and `diagnose` too once something fails and the
// agent is asked to explain it. Neither repairs anything, so calling either a
// repair would claim work the run never did.
export const CHECK_ONLY = ["verify", "diagnose"];

// Runs that are one action rather than a pipeline.
//
// The rail above is the `check` and `fix` path and nothing else, but it was
// drawn for every run, and most runs are not that path: of the 493 recorded so
// far, 344 are a disconnect and 105 are a single provider tool call. Those runs
// drew six grey cells and sixteen grey chips describing work that was never
// going to happen, under the word "Launching", which was not what they were
// doing either.
//
// So a run whose stages are all in here has no rail and no chips. There is no
// sequence to draw and nothing to check, and drawing them anyway is the same
// lie as a permanently grey cell, told about a whole run instead of one step.
// The value is what the run is, in the words an owner would use.
export const ERRANDS = {
  disconnect: "Removing credentials",
  passthrough: "Running a provider tool",
  api: "Calling a provider API",
  across: "Asking every client",
  work: "Working on one client",
};

/** What the page should draw for this run: the heading, and whether the rail
 *  and the chips belong on screen at all.
 *
 *  Derived from the stages the run has actually emitted, so a run is described
 *  by what it did rather than by which tool was called. A run that has emitted
 *  nothing yet gets the rail, because the common case is a check about to
 *  start and an empty screen reads worse than one waiting.
 */
export function shape(state) {
  const seen = state.stagesSeen;
  if (seen.length > 0 && seen.every((s) => s in ERRANDS)) {
    return { eyebrow: ERRANDS[seen[0]], rail: false, chips: false };
  }
  // A stage that was reached and deliberately not run does not get to name the
  // run. A `fix` on a domain with nothing repairable reaches `repair`, is
  // refused by the edge, and renders the cell dashed with a reason: calling
  // that run "Repairing" over a rail that says the repair did not happen is the
  // rail and the heading disagreeing in public.
  const ran = seen.filter((s) => !state.stagesOff.includes(s));
  const worked = ran.some((s) => !CHECK_ONLY.includes(s));
  return { eyebrow: worked ? "Repairing" : "Checking", rail: true, chips: true };
}

export const initialState = {
  // The run being watched. The page follows `latest` by default and can be
  // pointed at any run in the log, so "which run is this" stops being
  // something only the server knows.
  runId: null,
  client: null, stage: null, stagesDone: [], stagesSeen: [], stagesOff: [],
  checks: {},
  finding: null, awaitingConfirm: null, escalated: null,
  // A cross-client answer has one finding per client, so one slot cannot hold
  // it: five clients used to render as one heading and one card, whichever
  // arrived last. Keyed by client, and `across` is the stage that fills it.
  byClient: {}, question: null,
  // `deciding` is set the moment a button is pressed and before the POST comes
  // back, so both buttons disable and a second click cannot ask again. The
  // server refuses a second answer anyway, but a button that looks live after
  // being pressed reads as a button that did nothing.
  // `decided` is what actually happened, once an event confirms it.
  deciding: null, decided: null,
  events: [], done: false, connected: false,
};

/** A reducer over EventSource messages. Deliberately not a data-fetching
 *  library: this is push, not pull-with-cache-invalidation. */
export function reduce(state, action) {
  if (action.type === "reset") return initialState;
  if (action.type === "connected") return { ...state, connected: action.value };
  // Pressed, not yet answered. Local: the answer itself arrives as an event
  // like everything else, so this is only about the moment in between.
  if (action.type === "decide") return { ...state, deciding: action.value };

  const e = action.event;
  const next = {
    ...state,
    runId: e.run_id || state.runId,
    client: e.client || state.client,
    // Every stage the run has touched, not just the completed ones. A run that
    // only ever touches `verify` is a check, not a launch, and the room says so.
    stagesSeen: e.stage && !state.stagesSeen.includes(e.stage)
      ? [...state.stagesSeen, e.stage]
      : state.stagesSeen,
    events: [...state.events, e].slice(-200),
  };
  const check = e.detail && e.detail.check;

  switch (e.kind) {
    case "stage_start":
      next.stage = e.stage;
      break;
    case "stage_done":
      next.stagesDone = [...new Set([...state.stagesDone, e.stage])];
      break;
    case "observation":
      if (check) next.checks = { ...state.checks, [check]: "pass" };
      // A stage that was deliberately not run, rather than one still pending.
      // Agents are off by default now, so `diagnose` would otherwise sit grey
      // for the whole run and read as a step that hung: exactly the confusion
      // the comment above STAGES was written about.
      else if (e.detail && e.detail.agents === "off" && e.stage)
        next.stagesOff = [...new Set([...state.stagesOff, e.stage])];
      break;
    case "finding":
      if (check) next.checks = { ...state.checks, [check]: "fail" };
      next.finding = e;
      if (e.stage === "across" && e.client) {
        next.byClient = {
          ...state.byClient,
          [e.client]: [...(state.byClient[e.client] || []), e],
        };
        if (e.detail && e.detail.question) next.question = e.detail.question;
      }
      break;
    case "resolved":
      if (check) next.checks = { ...state.checks, [check]: "pass" };
      next.finding = null;
      break;
    case "awaiting_confirm":
      next.awaitingConfirm = e;
      break;
    case "mutation":
      // A mutation is the answer to the question that preceded it, so the
      // prompt clears when the change lands rather than lingering as a stale
      // card asking for something already approved.
      next.awaitingConfirm = null;
      next.deciding = null;
      next.decided = "approve";
      break;
    case "escalated":
      next.escalated = e;
      // A refusal and a run that nobody answered in time both arrive here, and
      // both have to stop the card waiting. Without this a timed-out prompt
      // sits on screen forever asking for something that can no longer be
      // given, which is the same lie as a permanently grey stage cell.
      if (e.detail && e.detail.decision) {
        next.awaitingConfirm = null;
        next.deciding = null;
        next.decided = e.detail.decision;
      }
      // A cross-client escalation is "the agent named an account it never
      // read". It belongs beside that client rather than replacing the single
      // escalation slot, which a launch uses for something else entirely.
      if (e.stage === "across" && e.client) {
        next.byClient = {
          ...state.byClient,
          [e.client]: [...(state.byClient[e.client] || []), e],
        };
      }
      break;
    case "run_done":
      next.done = true;
      next.awaitingConfirm = null;
      next.deciding = null;
      break;
  }
  return next;
}
