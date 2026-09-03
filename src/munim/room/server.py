"""The control room's server. A separate process, on purpose.

The MCP server speaks JSON-RPC over stdout and is a subprocess the coding agent
kills on every reconnect, config reload and session exit. An HTTP listener living
inside it would go dark mid-demo and then fail to rebind on respawn.

So the room is its own process. It tails the run log the agent writes and serves
it as Server-Sent Events. Nothing here talks to a provider, holds a credential,
or mutates anything: the room is a window, not an interface (D18).
"""

import asyncio
import json
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from munim.runlog import RUNS_DIR, RunLog, all_runs, latest_run

POLL_SECONDS = 0.25
BUILD_DIR = Path(__file__).parent / "static"


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
    if run_id == "latest":
        run_id = latest_run(directory)
        if run_id is None:
            return JSONResponse({"error": "no runs yet"}, status_code=404)

    resume_from = int(request.headers.get("last-event-id") or request.query_params.get("from") or 0)

    async def stream():
        log = RunLog(run_id, directory)
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

    return Response(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def index(request: Request) -> Response:
    page = BUILD_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse(
        {"error": "control room is not built", "hint": "cd room && npm install && npm run build"},
        status_code=503,
    )


def build_app(runs_dir: Path | None = None) -> Starlette:
    routes = [
        Route("/api/runs", list_runs),
        Route("/api/runs/{run_id}/events", run_events),
    ]
    assets = BUILD_DIR / "assets"
    if assets.exists():
        routes.append(Mount("/assets", StaticFiles(directory=assets)))
    routes.append(Route("/{path:path}", index))

    app = Starlette(routes=routes)
    app.state.runs_dir = Path(runs_dir or RUNS_DIR)
    return app


def main() -> None:
    import os

    port = int(os.environ.get("MUNIM_ROOM_PORT", "8977"))
    print(f"control room → http://127.0.0.1:{port}", flush=True)
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
