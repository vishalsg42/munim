"""The local listener that catches an OAuth redirect.

One implementation, because there are now two flows that need it and this is
where the interesting bug was: serving exactly one request meant the first
thing to touch the port consumed it. A browser prefetching a favicon, a port
scanner, or a health probe, and the login failed with "no callback received"
having received one.
"""

import errno
import http.server
import socket
import threading
import time
import urllib.parse

DEFAULT_PORT = 8976
CALLBACK_PATH = "/oauth/callback"

_PAGE = (
    b"<!doctype html><meta charset=utf-8>"
    b"<body style='font:16px -apple-system,sans-serif;color:#17191c;"
    b"background:#fbfaf8;display:grid;place-items:center;height:100vh;margin:0'>"
    b"<div style='text-align:center'><p style='font-size:20px'>Connected.</p>"
    b"<p style='color:#5f6368'>You can close this tab.</p></div>"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        _Handler.result = dict(urllib.parse.parse_qsl(parsed.query))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_PAGE)))
        self.end_headers()
        self.wfile.write(_PAGE)

    def log_message(self, *args):
        pass


def redirect_uri(port: int = DEFAULT_PORT) -> str:
    return f"http://localhost:{port}{CALLBACK_PATH}"


def serve_until_callback(port: int = DEFAULT_PORT, timeout: float = 180.0) -> dict:
    """Block until the redirect lands, ignoring everything that is not it.

    Returns the query parameters. Raises TimeoutError naming the URL it waited
    on, because "no callback received" tells whoever reads it nothing.
    """
    _Handler.result = {}
    try:
        server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        raise RuntimeError(
            f"Port {port} is already in use, so the login has nowhere to come "
            f"back to. Close whatever is holding it and try again."
        ) from exc

    server.timeout = 0.5
    deadline = time.monotonic() + timeout

    def serve():
        while not _Handler.result and time.monotonic() < deadline:
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    thread.join(timeout)
    server.server_close()

    if not _Handler.result:
        raise TimeoutError(
            f"no callback on {redirect_uri(port)} within {timeout:.0f}s; "
            "the browser flow did not complete"
        )
    return dict(_Handler.result)
