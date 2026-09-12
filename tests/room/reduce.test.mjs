// Run with: node --test tests/room/ - no install, no build, no dependencies.
import assert from "node:assert";
import { test } from "node:test";
import {
  CHECKS, CHECK_LABELS, STAGES, ERRANDS, initialState, reduce, shape,
} from "../../src/munim/room/static/reduce.mjs";


const ev = (seq, kind, detail = {}, stage = "mail") => ({
  run_id: "r", seq, ts: 0, client: "Ivy", stage, kind,
  human_text: "x", detail,
});

test("a confirmed mutation clears the prompt", () => {
  let s = reduce(initialState, { type: "event", event: ev(1, "awaiting_confirm") });
  assert.ok(s.awaitingConfirm);
  s = reduce(s, { type: "event", event: ev(2, "mutation") });
  assert.equal(s.awaitingConfirm, null);
});

test("a finding clears when it is resolved", () => {
  let s = reduce(initialState, { type: "event", event: ev(1, "finding", { check: "spf_single" }) });
  assert.equal(s.checks.spf_single, "fail");
  s = reduce(s, { type: "event", event: ev(2, "resolved", { check: "spf_single" }) });
  assert.equal(s.checks.spf_single, "pass");
  assert.equal(s.finding, null);
});

test("run_done leaves nothing pending", () => {
  let s = reduce(initialState, { type: "event", event: ev(1, "awaiting_confirm") });
  s = reduce(s, { type: "event", event: ev(2, "run_done") });
  assert.equal(s.awaitingConfirm, null);
  assert.ok(s.done);
});

test("a verify-only run is a check, not a launch", () => {
  let s = reduce(initialState, { type: "event", event: ev(1, "stage_start", {}, "verify") });
  s = reduce(s, { type: "event", event: ev(2, "observation", { check: "mx_present" }, "verify") });
  assert.deepEqual(s.stagesSeen, ["verify"]);
});

test("a launch touches more than verify", () => {
  let s = reduce(initialState, { type: "event", event: ev(1, "stage_start", {}, "deploy") });
  s = reduce(s, { type: "event", event: ev(2, "stage_start", {}, "verify") });
  assert.deepEqual(s.stagesSeen, ["deploy", "verify"]);
});

test("a run that diagnoses a failure is still a check, not a launch", () => {
  let s = reduce(initialState, { type: "event", event: ev(1, "stage_start", {}, "verify") });
  s = reduce(s, { type: "event", event: ev(2, "finding", { check: "dmarc_policy" }, "verify") });
  s = reduce(s, { type: "event", event: ev(3, "stage_start", {}, "diagnose") });
  s = reduce(s, { type: "event", event: ev(4, "stage_done", {}, "diagnose") });
  assert.deepEqual(s.stagesSeen, ["verify", "diagnose"]);
});

test("a stage nobody asked for is off, not pending", () => {
  // The diagnose chip renders grey while a stage has not happened yet. Agents
  // are off by default now, so without a separate state that chip sits grey for
  // every run a fresh install makes and reads as a step that hung.
  let s = reduce(initialState, { type: "event", event: ev(1, "stage_start", {}, "verify") });
  s = reduce(s, {
    type: "event",
    event: ev(2, "observation", { agents: "off" }, "diagnose"),
  });
  assert.deepEqual(s.stagesOff, ["diagnose"]);
  assert.ok(!s.stagesDone.includes("diagnose"), "off is not done");
});

test("an ordinary observation does not mark a stage off", () => {
  const s = reduce(initialState, {
    type: "event",
    event: ev(1, "observation", { check: "mx_present" }, "verify"),
  });
  assert.deepEqual(s.stagesOff, []);
  assert.equal(s.checks.mx_present, "pass");
});

// ---- a cross-client answer is many clients, not one ----------------------
//
// `ask_across_clients` emits one finding per client. The reducer held a single
// `client` and a single `finding`, so five clients rendered as one heading and
// one card: whichever arrived last. Every test above is a launch, which really
// is about one client, which is why nothing caught it.

const across = (client, says, extra = {}) => ({
  run_id: "r", seq: 1, ts: 0, client, stage: "across", kind: "finding",
  human_text: says, detail: { provider: "resend", question: "who?", ...extra },
});

test("findings from several clients are all kept", () => {
  let state = initialState;
  for (const e of [across("Acme", "verified"),
                   across("Ivy & Fern", "not verified"),
                   across("Thistle", "verified")]) {
    state = reduce(state, { type: "event", event: e });
  }
  assert.deepEqual(Object.keys(state.byClient).sort(),
                   ["Acme", "Ivy & Fern", "Thistle"]);
  assert.equal(state.byClient["Ivy & Fern"][0].human_text, "not verified");
});

test("two findings about one client both survive", () => {
  let state = initialState;
  state = reduce(state, { type: "event", event: across("Acme", "one") });
  state = reduce(state, { type: "event", event: across("Acme", "two") });
  assert.equal(state.byClient.Acme.length, 2);
});

test("the question being answered is carried alongside", () => {
  const state = reduce(initialState,
                       { type: "event", event: across("Acme", "verified") });
  assert.equal(state.question, "who?");
});

test("an account the agent never read is grouped, not lost", () => {
  const e = { ...across("Ghost", "named but never read"), kind: "escalated" };
  const state = reduce(initialState, { type: "event", event: e });
  assert.equal(state.byClient.Ghost[0].kind, "escalated");
});

test("a launch's own finding does not land in the cross-client grouping", () => {
  const launch = {
    run_id: "r", seq: 1, ts: 0, client: "Acme", stage: "verify",
    kind: "finding", human_text: "two spf records", detail: { check: "spf_single" },
  };
  const state = reduce(initialState, { type: "event", event: launch });
  assert.deepEqual(state.byClient, {});
  assert.equal(state.finding.human_text, "two spf records");
});

// ---- the chip grid must match what something actually emits --------------
//
// It listed twenty checks; the catalogue emits thirteen. Seven cells sat grey
// through every run, on camera, and a permanently grey chip reads as a step
// that hung rather than one that does not exist. The producers are the source
// of truth, so this pins the list against them rather than against itself.

const EMITTED = [
  // munim/checks/dns.py, the 13 the catalogue produces
  "spf_single", "spf_lookups", "dkim_present", "dkim_chunking",
  "dmarc_present", "dmarc_policy", "mx_present", "ns_delegated",
  "cert_valid", "caa_allows", "apex_resolves", "www_redirect",
  "https_enforced",
  // munim/checks/hosting.py, which is what finally calls the three checks in
  // munim/adapters/vercel.py. They were written, tested, and reachable from
  // nothing in src/ for the life of the project, while this list already
  // claimed two of them were "produced on a launch with Vercel connected".
  "deploy_current", "env_applied", "env_scoped",
];

test("every chip has something that can light it", () => {
  const ghosts = CHECKS.filter((c) => !EMITTED.includes(c));
  assert.deepEqual(ghosts, [],
    `no producer emits: ${ghosts.join(", ")}`);
});

test("every check that is emitted has a chip", () => {
  const missing = EMITTED.filter((c) => !CHECKS.includes(c));
  assert.deepEqual(missing, [],
    `emitted but never shown: ${missing.join(", ")}`);
});

test("every chip has a label", () => {
  const unlabelled = CHECKS.filter((c) => !CHECK_LABELS[c]);
  assert.deepEqual(unlabelled, []);
});

// ---- the rail, pinned against the source rather than against a list ------
//
// The chip list was pinned against its producers after seven ghost cells shipped
// and sat grey on camera. The stage rail had exactly the same bug: it declared
// `deploy` and `domain` and nothing in src/ emitted either. That was fixed by
// writing the producers down here by hand, which fixed the instance and left
// the class alone, and the hand-written list then quietly went wrong in the
// other direction: it named six stages, src/ emits eleven, and the five it
// omitted are the ones most runs are made of. A run of any of them drew six
// grey cells and sixteen grey chips for work that was never going to happen.
//
// So the list is read out of the source now. A stage that anything emits has to
// be somewhere the page can show it: a cell in the rail, or an errand, which is
// a run with no pipeline to draw. Adding a stage and forgetting the room fails
// here rather than on camera.

import fs from "node:fs";
import path from "node:path";

function pythonFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "__pycache__" ? [] : pythonFiles(full);
    }
    return entry.name.endsWith(".py") ? [full] : [];
  });
}

/** Every stage name src/ can write into a run log.
 *
 *  Three ways one gets set, all of them literal at the call site:
 *  `stage="mail"`, a default `stage: str = "api"`, and the node-to-stage map in
 *  agent/watch.py, which is how the graph's nodes are named in the log.
 */
function stagesInSource() {
  const found = new Set();
  for (const file of pythonFiles(path.join("src", "munim"))) {
    const source = fs.readFileSync(file, "utf8");
    for (const m of source.matchAll(/\bstage(?::\s*str)?\s*=\s*"([a-z_]+)"/g)) {
      found.add(m[1]);
    }
    for (const map of source.matchAll(/STAGE\s*=\s*\{([^}]*)\}/g)) {
      for (const m of map[1].matchAll(/:\s*"([a-z_]+)"/g)) found.add(m[1]);
    }
  }
  return [...found].sort();
}

const STAGES_EMITTED = stagesInSource();

test("the scan finds the stages, so the two tests below mean something", () => {
  // A regex that matched nothing would make both of them pass forever.
  assert.ok(STAGES_EMITTED.length >= 8,
    `only found ${STAGES_EMITTED.join(", ")}, the scan is broken`);
  for (const stage of ["verify", "diagnose", "repair", "mail", "disconnect"]) {
    assert.ok(STAGES_EMITTED.includes(stage), `scan missed ${stage}`);
  }
});

test("every stage in the rail has something that emits it", () => {
  const ghosts = STAGES.filter((s) => !STAGES_EMITTED.includes(s));
  assert.deepEqual(ghosts, [],
    `nothing writes these stages, so their cells can only ever be grey: ${ghosts.join(", ")}`);
});

test("every stage that is emitted is either a cell or an errand", () => {
  const homeless = STAGES_EMITTED.filter(
    (s) => !STAGES.includes(s) && !(s in ERRANDS));
  assert.deepEqual(homeless, [],
    `emitted and the room has nowhere to put it: ${homeless.join(", ")}`);
});

test("nothing is both a step in the rail and a run of its own", () => {
  const both = STAGES.filter((s) => s in ERRANDS);
  assert.deepEqual(both, [], `both a cell and an errand: ${both.join(", ")}`);
});

// ---- what the page draws for a run ---------------------------------------

const seeing = (...stages) => stages.reduce(
  (s, stage) => reduce(s, {
    type: "event",
    event: { run_id: "r", seq: 1, ts: 0, client: "Acme", stage,
             kind: "stage_start", human_text: "x", detail: {} },
  }), initialState);

test("a run that only checks says so", () => {
  const look = shape(seeing("verify", "diagnose"));
  assert.equal(look.eyebrow, "Checking");
  assert.ok(look.rail && look.chips);
});

test("a run that repairs says so", () => {
  assert.equal(shape(seeing("verify", "diagnose", "repair")).eyebrow, "Repairing");
});

test("a disconnect is not a launch and has no rail to draw", () => {
  const look = shape(seeing("disconnect"));
  assert.equal(look.eyebrow, "Removing credentials");
  assert.equal(look.rail, false);
  assert.equal(look.chips, false);
});

test("one provider tool call is not a launch either", () => {
  assert.equal(shape(seeing("passthrough")).eyebrow, "Running a provider tool");
});

test("a repair that was switched off does not get to call itself one", () => {
  let s = seeing("verify", "diagnose", "repair");
  s = reduce(s, {
    type: "event",
    event: { run_id: "r", seq: 9, ts: 0, client: "Acme", stage: "repair",
             kind: "observation", human_text: "agents are off",
             detail: { agents: "off" } },
  });
  assert.equal(shape(s).eyebrow, "Checking");
  assert.ok(shape(s).rail, "the rail still shows why it stopped");
});

test("a run that has emitted nothing yet still gets the rail", () => {
  const look = shape(initialState);
  assert.equal(look.eyebrow, "Checking");
  assert.ok(look.rail);
});

test("an errand followed by real work stops being an errand", () => {
  // `across` is an errand on its own. A run that then checks something has a
  // pipeline again, and hiding it would be the same lie the other way round.
  assert.ok(shape(seeing("across", "verify")).rail);
});

test("the run being watched is remembered, so the report can be linked", () => {
  const s = seeing("verify");
  assert.equal(s.runId, "r");
});

// ---- the one interactive element -----------------------------------------

const CONFIRM = {
  run_id: "r1", seq: 4, ts: 0, client: "Acme Ltd", stage: "mail",
  kind: "awaiting_confirm", human_text: "2 records already exist.",
  detail: {
    plan_id: "p1",
    changes: [{ purpose: "SPF", name: "acme.example", action: "merge",
                current: ["v=spf1 include:a ~all"],
                content: "v=spf1 include:a include:b ~all" }],
  },
};

const feed = (...events) =>
  events.reduce((s, e) => reduce(s, e.type ? e : { type: "event", event: e }),
                initialState);

test("the change waiting for approval arrives with what it would replace", () => {
  const state = feed(CONFIRM);
  const change = state.awaitingConfirm.detail.changes[0];

  assert.equal(state.awaitingConfirm.detail.plan_id, "p1");
  assert.deepEqual(change.current, ["v=spf1 include:a ~all"]);
  assert.match(change.content, /include:b/);
});

test("pressing a button marks the answer as in flight", () => {
  const state = feed(CONFIRM, { type: "decide", value: "approve" });

  assert.equal(state.deciding, "approve");
  assert.ok(state.awaitingConfirm, "the card stays up until the answer lands");
});

test("a second click cannot ask twice", () => {
  // The buttons render disabled off `deciding`, so this is the state that
  // makes a double-click impossible rather than merely refused server-side.
  const state = feed(CONFIRM, { type: "decide", value: "approve" });

  assert.equal(state.deciding, "approve");
  assert.notEqual(state.deciding, null);
});

test("a mutation clears the prompt and the pending click", () => {
  const state = feed(CONFIRM, { type: "decide", value: "approve" },
    { run_id: "r1", seq: 5, ts: 0, client: "Acme Ltd", stage: "mail",
      kind: "mutation", human_text: "Published SPF", detail: {} });

  assert.equal(state.awaitingConfirm, null);
  assert.equal(state.deciding, null);
  assert.equal(state.decided, "approve");
});

test("a change nobody approved in time stops waiting", () => {
  // The failure this prevents: a timed-out card sitting on screen forever,
  // asking for something that can no longer be given.
  const state = feed(CONFIRM, { type: "decide", value: "approve" },
    { run_id: "r1", seq: 5, ts: 0, client: "Acme Ltd", stage: "mail",
      kind: "escalated", human_text: "Nobody approved this in time.",
      detail: { plan_id: "p1", decision: "timed out" } });

  assert.equal(state.awaitingConfirm, null);
  assert.equal(state.deciding, null);
  assert.equal(state.decided, "timed out");
});

test("an escalation that is not about a decision leaves the prompt alone", () => {
  // `escalated` carries more than refusals. A cross-client escalation must not
  // silently dismiss a pending approval for something else entirely.
  const state = feed(CONFIRM,
    { run_id: "r1", seq: 5, ts: 0, client: "Acme Ltd", stage: "across",
      kind: "escalated", human_text: "Named an account it never read.",
      detail: {} });

  assert.ok(state.awaitingConfirm, "an unrelated escalation dismissed the card");
});

test("a finished run leaves nothing waiting", () => {
  const state = feed(CONFIRM, { type: "decide", value: "approve" },
    { run_id: "r1", seq: 9, ts: 0, client: "Acme Ltd", stage: "mail",
      kind: "run_done", human_text: "Finished.", detail: {} });

  assert.equal(state.awaitingConfirm, null);
  assert.equal(state.deciding, null);
  assert.equal(state.done, true);
});
