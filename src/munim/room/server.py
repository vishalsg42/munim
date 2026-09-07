"""The control room's server. A separate process, on purpose.

The MCP server speaks JSON-RPC over stdout and is a subprocess the coding agent
kills on every reconnect, config reload and session exit. An HTTP listener living
inside it would go dark mid-demo and then fail to rebind on respawn.

So the room is its own process. It tails the run log the agent writes and serves
it as Server-Sent Events.

It has exactly one thing it can do back: record a person's answer when the agent
has stopped and is waiting to be told whether to replace a record somebody
already published. That is the affordance D18 specified and nothing ever wired
up, and it writes one small local file. Nothing here talks to a provider, holds
a credential, or can start a run. The room is a window with one button (D34).
"""

import argparse
import asyncio
import errno
import json
import os
import socket
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from munim import approval
from munim.report import REPORTS_DIR
from munim.runlog import RUNS_DIR, RunLog, all_runs, latest_run

POLL_SECONDS = 0.25
BUILD_DIR = Path(__file__).parent / "static"


# How long to hold out for a run that is still going before showing the newest
# finished one. Long enough to open the room and then start something; short
# enough that opening it after the fact still shows the last answer.
WAIT_FOR_FRESH = 20.0


def _finished(directory: Path, run: str) -> bool:
    """Whether this run already ended. A finished run has nothing left to
    stream, so following it would show a replay and then close."""
    try:
        return any(e.kind == "run_done" for e in RunLog(run, directory).read())
    except Exception:
        return False


def _runs_dir(request: Request) -> Path:
    return request.app.state.runs_dir


async def list_runs(request: Request) -> JSONResponse:
    directory = _runs_dir(request)
    return JSONResponse({"runs": all_runs(directory), "latest": latest_run(directory)})


async def run_events(request: Request) -> Response:
    """Replay then follow.

    `Last-Event-ID` is why the room can be opened mid-launch, or refreshed, and
    still show the whole run - SSE itself keeps no history, the file does.
    """
    directory = _runs_dir(request)
    run_id = request.path_params["run_id"]
    follow_latest = run_id == "latest"

    resume_from = int(request.headers.get("last-event-id") or request.query_params.get("from") or 0)

    async def stream():
        # Wait for a run rather than 404ing. The room is normally opened before
        # the launch starts, and an EventSource that gets a 404 does not recover
        # when a run appears - which would mean opening the window, starting a
        # launch, and watching nothing happen.
        resolved = run_id
        if follow_latest:
            # Wait for a run that is still going, not merely for a run to
            # exist. Resolving the newest finished one meant that opening the
            # room on a machine with any history replayed yesterday, sent
            # `done`, closed the stream, and never saw the run that started
            # afterwards. Which is every rehearsal of the demo.
            started = time.time()
            while True:
                candidate = latest_run(directory)
                if candidate is not None and (
                        run_id is not None
                        or not _finished(directory, candidate)
                        or time.time() - started >= WAIT_FOR_FRESH):
                    resolved = candidate
                    break
                if await request.is_disconnected():
                    return
                yield ": waiting-for-run\n\n"
                await asyncio.sleep(POLL_SECONDS)

        log = RunLog(resolved, directory)
        seen = resume_from
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            fresh = list(log.read(after_seq=seen))
            for event in fresh:
                seen = event.seq
                yield f"id: {event.seq}\nevent: launch\ndata: {event.model_dump_json()}\n\n"
            if fresh:
                idle = 0
                if fresh[-1].kind == "run_done":
                    yield "event: done\ndata: {}\n\n"
                    return
            else:
                idle += POLL_SECONDS
                if idle >= 15:  # keep proxies and browsers from timing the stream out
                    yield ": keep-alive\n\n"
                    idle = 0
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _same_site(request: Request) -> bool:
    """Whether this POST came from the room's own page.

    Binding to loopback stops another machine. It does not stop another page:
    any site the operator's browser visits while the room is open can POST to
    127.0.0.1 and, without this, approve somebody's DNS change. The room is
    unauthenticated because it is single-user and local, and that reasoning only
    holds with an origin check in front of it.

    `Sec-Fetch-Site` is sent by every browser that can run this page and is the
    direct answer. `Origin` is the fallback, and an absent Origin is refused
    rather than trusted, because a request with no origin is not one the room's
    own page made.
    """
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site in ("same-origin", "none")
    origin = request.headers.get("origin")
    if not origin:
        return False
    host = request.headers.get("host", "")
    return origin in (f"http://{host}", f"https://{host}")


async def decide(request: Request) -> JSONResponse:
    """The one thing the room can do.

    D18 said the room "has exactly one interactive element in the whole
    application, the confirmation button, and it appears only when the agent has
    stopped and needs a person". This is that button finally reaching something.
    It writes one small local file. It holds no credential, reaches no provider,
    and cannot start a run, so the room is still a window with one button rather
    than a place you go to do work.
    """
    if not _same_site(request):
        return JSONResponse({"error": "cross-site requests are refused"},
                            status_code=403)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return JSONResponse({"error": "expected a JSON body"}, status_code=400)

    answer = body.get("decision")
    if answer not in ("approve", "reject"):
        return JSONResponse(
            {"error": "decision must be 'approve' or 'reject'"}, status_code=400)

    made = approval.record(request.path_params["run_id"],
                           request.path_params["plan_id"],
                           approved=answer == "approve", by="room")
    return JSONResponse({"approved": made.approved, "by": made.by,
                         "at": made.at})


async def report(request: Request) -> Response:
    """Serve a launch report. The owner-facing page lives next to the run it
    came from, so a link in an email and a link in the room are the same page."""
    run_id = request.path_params["run_id"]
    page = request.app.state.reports_dir / f"{run_id}.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse({"error": "no report for that run"}, status_code=404)


async def index(request: Request) -> Response:
    """A real file if the path names one, the page otherwise.

    The page is a module and imports `./reduce.mjs`, so that path has to come
    back as JavaScript. Falling straight through to index.html answered it with
    HTML, and a browser refuses a module served as text/html: the room rendered
    blank with the failure only visible in the console.

    The containment check is not decoration. Without it `/../../.ssh/id_rsa`
    resolves out of the build directory, and this server is reachable from the
    machine it runs on.
    """
    wanted = (BUILD_DIR / request.path_params.get("path", "")).resolve()
    if wanted.is_file() and wanted.is_relative_to(BUILD_DIR.resolve()):
        return FileResponse(wanted)

    page = BUILD_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse(
        {"error": "control room is missing", "hint": "reinstall munim"},
        status_code=503,
    )


def build_app(runs_dir: Path | None = None,
              reports_dir: Path | None = None) -> Starlette:
    routes = [
        Route("/api/runs", list_runs),
        Route("/api/runs/{run_id}/events", run_events),
        # In the initial list, not appended. `/{path:path}` below swallows
        # everything that reaches it, so a route added after it never runs.
        Route("/api/decisions/{run_id}/{plan_id}", decide, methods=["POST"]),
        Route("/reports/{run_id}", report),
    ]
    assets = BUILD_DIR / "assets"
    if assets.exists():
        routes.append(Mount("/assets", StaticFiles(directory=assets)))
    routes.append(Route("/{path:path}", index))

    app = Starlette(routes=routes)
    app.state.runs_dir = Path(runs_dir or RUNS_DIR)
    # Reports follow the runs. A room pointed at one set of runs that served
    # reports from another would answer /reports/<id> with someone else's page,
    # or with a 404 for a run it is displaying.
    app.state.reports_dir = Path(reports_dir or REPORTS_DIR)
    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Flags, not just environment variables.

    Someone whose 8977 is already taken reaches for `--port` before they reach
    for the source. Without a parser argparse never sees it, unknown arguments
    are silently dropped, and the room binds 8977 anyway and dies on
    EADDRINUSE - having been told exactly how to avoid that.
    """
    parser = argparse.ArgumentParser(
        prog="munim-room",
        description="Watch a launch as it happens.")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MUNIM_ROOM_PORT", "8977")),
        help="port to serve on (default: 8977, or $MUNIM_ROOM_PORT)")
    parser.add_argument(
        "--runs", type=Path, default=None, metavar="DIR",
        help=f"directory of run logs (default: {RUNS_DIR})")
    parser.add_argument(
        "--reports", type=Path, default=None, metavar="DIR",
        help=f"directory of launch reports (default: {REPORTS_DIR})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    # Takes argv so `munim room` can forward its own arguments. Calling this
    # with none left argparse reading `sys.argv`, which still holds the `room`
    # token the dispatcher already consumed, and the parser rejects it.
    args = parse_args(argv)

    # Bind the socket here rather than letting uvicorn do it. uvicorn catches
    # EADDRINUSE itself, logs `[errno 48] address already in use` and exits, so
    # a try/except around uvicorn.run() never fires - it just looks like it
    # would. Owning the socket also removes the race a pre-flight check leaves.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", args.port))
    except OSError as exc:
        sock.close()
        if exc.errno != errno.EADDRINUSE:
            raise
        raise SystemExit(
            f"Port {args.port} is already in use, most likely by a control room "
            f"you already have open.\n"
            f"Either use that one, or start this on another port:\n"
            f"    munim-room --port {args.port + 1}"
        ) from exc
    sock.listen()

    print(f"control room → http://127.0.0.1:{args.port}", flush=True)
    config = uvicorn.Config(build_app(args.runs, args.reports),
                            log_level="warning")
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()
