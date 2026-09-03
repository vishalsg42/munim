import type { LaunchEvent } from "./types";

export type CheckState = "idle" | "running" | "pass" | "fail";

export interface RoomState {
  client: string | null;
  stage: string | null;
  stagesDone: string[];
  checks: Record<string, CheckState>;
  finding: LaunchEvent | null;
  awaitingConfirm: LaunchEvent | null;
  escalated: LaunchEvent | null;
  events: LaunchEvent[];
  done: boolean;
  connected: boolean;
}

export const initialState: RoomState = {
  client: null, stage: null, stagesDone: [], checks: {},
  finding: null, awaitingConfirm: null, escalated: null,
  events: [], done: false, connected: false,
};

export type Action =
  | { type: "event"; event: LaunchEvent }
  | { type: "connected"; value: boolean }
  | { type: "reset" };

/** A reducer over EventSource messages. Deliberately not a data-fetching
 *  library: this is push, not pull-with-cache-invalidation. */
export function reduce(state: RoomState, action: Action): RoomState {
  if (action.type === "reset") return initialState;
  if (action.type === "connected") return { ...state, connected: action.value };

  const e = action.event;
  const next: RoomState = {
    ...state,
    client: e.client || state.client,
    events: [...state.events, e].slice(-200),
  };
  const check = e.detail?.check as string | undefined;

  switch (e.kind) {
    case "stage_start":
      next.stage = e.stage;
      break;
    case "stage_done":
      next.stagesDone = [...new Set([...state.stagesDone, e.stage])];
      break;
    case "observation":
      if (check) next.checks = { ...state.checks, [check]: "pass" };
      break;
    case "finding":
      if (check) next.checks = { ...state.checks, [check]: "fail" };
      next.finding = e;
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
      break;
    case "run_done":
      next.done = true;
      next.awaitingConfirm = null;
      break;
  }
  return next;
}
