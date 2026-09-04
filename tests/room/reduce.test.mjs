// Run with: node --test tests/room/ - no install, no build, no dependencies.
import assert from "node:assert";
import { test } from "node:test";
import { initialState, reduce } from "../../src/munim/room/static/reduce.mjs";


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
