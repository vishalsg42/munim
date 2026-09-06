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
export const CHECKS = [
  "spf_single", "spf_lookups", "dkim_present", "dkim_chunking",
  "dmarc_present", "dmarc_policy", "mx_present", "return_path",
  "ns_delegated", "cert_valid", "cert_www", "caa_allows",
  "apex_resolves", "www_redirect", "https_enforced", "ssl_mode",
  "deploy_current", "env_scoped", "env_redeployed", "site_responds",
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
  env_redeployed: "Env applied", site_responds: "Site responds",
};

// `diagnose` is where the agent works out what a failure means. It was missing
// once, so the one step that makes this an agent rather than a DNS script never
// appeared in the rail: its events reached the log and nothing else.
export const STAGES = ["deploy", "domain", "dns", "mail", "verify", "diagnose"];

// A check run emits `verify`, and `diagnose` too once something fails and the
// agent is asked to explain it. Neither is deploying anything, so calling
// either a launch would claim work the run never did.
export const CHECK_ONLY = ["verify", "diagnose"];

export const initialState = {
  client: null, stage: null, stagesDone: [], stagesSeen: [], stagesOff: [],
  checks: {},
  finding: null, awaitingConfirm: null, escalated: null,
  // A cross-client answer has one finding per client, so one slot cannot hold
  // it: five clients used to render as one heading and one card, whichever
  // arrived last. Keyed by client, and `across` is the stage that fills it.
  byClient: {}, question: null,
  events: [], done: false, connected: false,
};

/** A reducer over EventSource messages. Deliberately not a data-fetching
 *  library: this is push, not pull-with-cache-invalidation. */
export function reduce(state, action) {
  if (action.type === "reset") return initialState;
  if (action.type === "connected") return { ...state, connected: action.value };

  const e = action.event;
  const next = {
    ...state,
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
      break;
    case "escalated":
      next.escalated = e;
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
      break;
  }
  return next;
}
