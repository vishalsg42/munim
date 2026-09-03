"""Browser login, one client at a time.

Why this exists rather than pasted keys: the operator connects a client once and
never again, which is the difference between a tool people install and a tool
people close. `mcpwarden` solves the same credential problem and asks you to
paste a token per account; it has had no adopters.

Standard OAuth 2.0 authorization code flow with PKCE (RFC 7636), because this is
a public client - there is no server that can keep a secret. The verifier never
leaves the process; only its SHA-256 hash goes to the provider.

The resulting token goes straight into the keychain under (client, provider), so
one operator can hold a dozen clients' grants for the same provider at once -
which no provider's own login can do.
"""

import base64
import hashlib
import http.server
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field

import httpx

from munim.container import KeychainBackend

CALLBACK_PORT = 8976
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/oauth/callback"


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...] = ()
    # Some providers reject PKCE-only public clients and require the secret too.
    needs_client_secret: bool = False
    extra_authorize: dict = field(default_factory=dict)


PROVIDERS: dict[str, Provider] = {
    # Registered at vercel.com/dashboard/integrations - self-serve.
    "vercel": Provider(
        name="vercel",
        authorize_url="https://vercel.com/oauth/authorize",
        token_url="https://api.vercel.com/v2/oauth/access_token",
        needs_client_secret=True,
    ),
    # Cloudflare's own MCP server reads a CLOUDFLARE_CLIENT_ID it was issued;
    # whether registration is self-serve is unconfirmed, so this is here and
    # unused until a client id exists rather than guessed at.
    "cloudflare": Provider(
        name="cloudflare",
        authorize_url="https://dash.cloudflare.com/oauth2/auth",
        token_url="https://dash.cloudflare.com/oauth2/token",
        scopes=("account:read", "zone:read", "dns_records:edit", "offline_access"),
    ),
    # Registered via the Supabase Management API.
    "supabase": Provider(
        name="supabase",
        authorize_url="https://api.supabase.com/v1/oauth/authorize",
        token_url="https://api.supabase.com/v1/oauth/token",
    ),
}

# Resend is deliberately absent: it publishes no authorization endpoint, so
# there is nothing to implement. An unsupported flow is absent, not faked (D11).


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


class _Callback(http.server.BaseHTTPRequestHandler):
    """Receives the redirect once, then the server is torn down."""

    result: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth/callback":
            self.send_response(404)
            self.end_headers()
            return
        _Callback.result = dict(urllib.parse.parse_qsl(parsed.query))
        body = (
            b"<!doctype html><meta charset=utf-8>"
            b"<body style='font:16px -apple-system,sans-serif;color:#17191c;"
            b"background:#fbfaf8;display:grid;place-items:center;height:100vh;margin:0'>"
            b"<div style='text-align:center'><p style='font-size:20px'>Connected.</p>"
            b"<p style='color:#5f6368'>You can close this tab.</p></div>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the terminal clean
        pass


class OAuthConnector:
    name = "oauth"

    def __init__(self, backend: KeychainBackend | None = None) -> None:
        self._backend = backend or KeychainBackend()

    def authorize_url(self, provider: str, client_id: str, state: str,
                      challenge: str) -> str:
        spec = PROVIDERS[provider]
        params = {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **spec.extra_authorize,
        }
        if spec.scopes:
            params["scope"] = " ".join(spec.scopes)
        return f"{spec.authorize_url}?{urllib.parse.urlencode(params)}"

    def connect(self, client: str, provider: str, client_id: str,
                client_secret: str | None = None, *, timeout: float = 180.0,
                open_browser: bool = True) -> str:
        """Run the flow and store the token for (client, provider).

        Returns the provider's account label where one is offered, so the
        operator can confirm they authorised the account they meant to - the
        one moment where connecting the wrong client is still possible.
        """
        if provider not in PROVIDERS:
            raise ValueError(
                f"{provider} publishes no OAuth authorization endpoint; "
                "use TokenConnector for it"
            )
        spec = PROVIDERS[provider]
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(24)

        _Callback.result = {}
        server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), _Callback)
        server.timeout = timeout
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        url = self.authorize_url(provider, client_id, state, challenge)
        if open_browser:
            webbrowser.open(url)
        thread.join(timeout)
        server.server_close()

        result = _Callback.result
        if not result:
            raise TimeoutError("no callback received; the browser flow did not complete")
        if result.get("state") != state:
            # Mismatched state means the response is not ours. Never exchange it.
            raise ValueError("state mismatch; discarding the authorization response")
        if "error" in result:
            raise RuntimeError(f"{provider} refused: {result.get('error_description', result['error'])}")

        data = {
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        }
        if spec.needs_client_secret and client_secret:
            data["client_secret"] = client_secret

        response = httpx.post(spec.token_url, data=data, timeout=30.0,
                              headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError(f"{provider} returned no access_token")

        self._backend.set(client, provider, token)
        return payload.get("team_id") or payload.get("account_id") or ""
