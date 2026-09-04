import { useEffect, useReducer, useRef } from "react";
import { CHECKS, CHECK_LABELS, STAGES, type LaunchEvent } from "./types";
import { initialState, reduce, type CheckState } from "./state";

const CHIP: Record<CheckState, string> = {
  idle: "border-stone-200 bg-white text-stone-400",
  running: "border-amber-400 bg-amber-50 text-amber-800",
  pass: "border-emerald-300 bg-emerald-50 text-emerald-800",
  fail: "border-rose-400 bg-rose-50 text-rose-800 shadow-sm",
};

export default function App() {
  const [state, dispatch] = useReducer(reduce, initialState);

  useEffect(() => {
    // Replay then follow. The file holds the history; SSE has none, which is
    // why the room can be opened mid-launch or refreshed without losing a run.
    const source = new EventSource("/api/runs/latest/events");
    source.onopen = () => dispatch({ type: "connected", value: true });
    source.onerror = () => dispatch({ type: "connected", value: false });
    source.addEventListener("launch", (m) =>
      dispatch({ type: "event", event: JSON.parse((m as MessageEvent).data) as LaunchEvent }),
    );
    // The server closes the stream once the run is done. An EventSource treats
    // any close as a dropped connection and reconnects, which would flip the
    // badge back to "live" on a run that finished minutes ago. Close it here.
    source.addEventListener("done", () => source.close());
    return () => source.close();
  }, []);

  const live = state.client !== null;
  // A check run only ever emits `verify` events. Calling that a launch would
  // claim work the run never did.
  const eyebrow =
    state.stagesSeen.length > 0 && state.stagesSeen.every((s) => s === "verify")
      ? "Checking"
      : "Launching";

  return (
    <div className="min-h-full font-sans antialiased">
      <header className="flex items-center justify-between border-b border-stone-200 bg-white px-8 py-4">
        <div className="flex items-baseline gap-3">
          <span className="text-[15px] font-semibold tracking-tight">Munim</span>
          <span className="text-[12px] text-stone-400">
            multi-account MCP server
          </span>
        </div>
        <span className="flex items-center gap-2 text-[11px] uppercase tracking-widest text-stone-400">
          <i
            className={`h-1.5 w-1.5 rounded-full ${
              state.done || state.connected ? "bg-emerald-500" : "bg-stone-300"
            }`}
          />
          {state.done ? "done" : state.connected ? "live" : "waiting"}
        </span>
      </header>

      {!live ? (
        <Empty />
      ) : (
        <main className="mx-auto max-w-5xl px-8 py-10">
          <p className="text-[11px] uppercase tracking-[0.2em] text-stone-400">
            {eyebrow}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">{state.client}</h1>

          <ol className="mt-8 flex items-center gap-2">
            {STAGES.map((stage) => {
              const done = state.stagesDone.includes(stage);
              const now = state.stage === stage && !done;
              return (
                <li key={stage} className="flex flex-1 items-center gap-2">
                  <span
                    className={`w-full rounded-md border px-3 py-2 text-[12px] capitalize transition-colors duration-500 ${
                      now
                        ? "border-amber-400 bg-amber-50 text-amber-900"
                        : done
                          ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                          : "border-stone-200 bg-white text-stone-400"
                    }`}
                  >
                    {stage}
                  </span>
                </li>
              );
            })}
          </ol>

          {/* Every chip is present from the first frame. They light up in place;
              nothing is inserted, so nothing moves. */}
          <div className="mt-8 grid grid-cols-4 gap-2">
            {CHECKS.map((check) => (
              <div
                key={check}
                className={`rounded-md border px-3 py-2 text-[11px] transition-colors duration-300 ${CHIP[state.checks[check] ?? "idle"]}`}
              >
                {CHECK_LABELS[check] ?? check}
              </div>
            ))}
          </div>

          {state.finding && <Finding event={state.finding} />}
          {state.awaitingConfirm && <Confirm event={state.awaitingConfirm} />}

          <Log events={state.events} />
        </main>
      )}
    </div>
  );
}

function Empty() {
  return (
    <div className="grid place-items-center px-8 py-32 text-center">
      <div>
        <p className="text-stone-500">No launch running.</p>
        <p className="mt-2 text-[13px] text-stone-400">
          Ask your coding agent to launch a client. This window follows along.
        </p>
      </div>
    </div>
  );
}

/* A finding is a mode, not a row in a list. It takes the screen because it is
   the only thing on it that needs a person. */
function Finding({ event }: { event: LaunchEvent }) {
  const evidence = event.detail?.evidence as string | undefined;
  const resolver = event.detail?.resolver as string | undefined;
  return (
    <section className="mt-8 rounded-lg border border-rose-300 bg-rose-50 p-6 shadow-sm">
      <p className="text-[11px] uppercase tracking-[0.2em] text-rose-600">
        Needs attention
      </p>
      <p className="mt-2 text-lg leading-snug text-rose-950">{event.human_text}</p>
      {evidence && (
        <pre className="mt-4 overflow-x-auto rounded border border-rose-200 bg-white p-3 font-mono text-[11px] leading-relaxed text-stone-600">
{evidence}
        </pre>
      )}
      {resolver && (
        <p className="mt-2 font-mono text-[10px] text-stone-400">
          answered by {resolver} · {new Date(event.ts * 1000).toISOString()}
        </p>
      )}
    </section>
  );
}

/* The only interactive element in the whole application. */
function Confirm({ event }: { event: LaunchEvent }) {
  return (
    <section className="mt-6 rounded-lg border border-amber-300 bg-amber-50 p-6 shadow-sm">
      <p className="text-[11px] uppercase tracking-[0.2em] text-amber-700">
        Waiting for you
      </p>
      <p className="mt-2 text-[15px] text-amber-950">{event.human_text}</p>
      <p className="mt-3 text-[12px] text-stone-600">
        This changes <span className="font-medium text-stone-900">{event.client}</span>&rsquo;s
        live DNS. It is their account, not yours.
      </p>
      <button className="mt-4 rounded-md bg-stone-900 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-stone-700">
        Approve for {event.client}
      </button>
    </section>
  );
}

function Log({ events }: { events: LaunchEvent[] }) {
  const end = useRef<HTMLDivElement>(null);
  // The newest line is the one that matters; a log that has to be scrolled is
  // a log nobody reads, on camera or otherwise.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [events.length]);

  return (
    <section className="mt-10 border-t border-stone-200 pt-4">
      <div className="max-h-40 space-y-1 overflow-y-auto font-mono text-[11px] text-stone-500">
        {events.map((e) => (
          <p key={e.seq}>
            <span className="text-stone-300">{String(e.seq).padStart(3, "0")}</span>{" "}
            <span className="text-stone-400">{e.stage}</span> {e.human_text}
          </p>
        ))}
        <div ref={end} />
      </div>
    </section>
  );
}
