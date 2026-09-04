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
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field

import httpx

from munim.connect.callback import serve_until_callback
from munim.container import KeychainBackend

CALLBACK_PORT = 8976
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/oauth/callback"

# Vercel names the integration by its URL slug rather than by client id.
VERCEL_SLUG = "munim"

# Client ids Munim ships with, so a browser login needs no registration errand
# first. These identify *the tool* to a provider, never a client, and they are
# only ever set for providers whose flow is a public PKCE client: such an id is
# public by design, which is what makes committing one correct rather than a
# leaked credential. A provider needing a secret cannot appear here, because a
# secret in a public repository is not a shipped default, it is a mistake.
#
# Overridable with <PROVIDER>_OAUTH_CLIENT_ID for anyone who would rather see
# their own application name on the consent screen.
SHIPPED_CLIENT_IDS: dict[str, str] = {
    # Registered once, at Manage Account > OAuth clients. Empty until then, and
    # `munim doctor` says so rather than failing at the browser.
    "cloudflare": "",
}


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...] = ()
    # Some providers reject PKCE-only public clients and require the secret too.
    needs_client_secret: bool = False
    extra_authorize: dict = field(default_factory=dict)
    # The issuer, exactly as the provider's discovery document spells it. RFC
    # 9207 comparison is a simple string match with no normalisation, so this is
    # copied rather than derived from the authorize URL.
    issuer: str = ""
    # Vercel's integration install flow is not an OAuth authorization endpoint.
    # The app is named by the slug in the path rather than a client_id
    # parameter, the scopes live in the Integrations Console rather than the
    # URL, and it rejects PKCE. Only `state` travels.
    install_flow: bool = False


PROVIDERS: dict[str, Provider] = {
    # Registered at vercel.com/dashboard/integrations - self-serve.
    #
    # This is the "external installation flow" for an Integration, NOT
    # https://vercel.com/oauth/authorize. That endpoint belongs to "Sign in
    # with Vercel" OAuth apps, whose client ids are prefixed `cl_`; handed an
    # Integration's `oac_` id it answers "The app ID is invalid", and even on
    # success it returns identity claims rather than access to a team's
    # projects, domains and environment variables - which is the whole point.
    # https://vercel.com/docs/integrations/create-integration/submit-integration
    "vercel": Provider(
        name="vercel",
        authorize_url=f"https://vercel.com/integrations/{VERCEL_SLUG}/new",
        token_url="https://api.vercel.com/v2/oauth/access_token",
        needs_client_secret=True,
        install_flow=True,
    ),
    # A public client: PKCE, no secret. Confirmed from Cloudflare's own
    # discovery document at dash.cloudflare.com/.well-known/openid-configuration,
    # which advertises `none` among token_endpoint_auth_methods_supported and
    # S256 among code_challenge_methods_supported. Both endpoints below come
    # from that document rather than from a blog post.
    #
    # There is no registration_endpoint, so Cloudflare does not support Dynamic
    # Client Registration. The MCP authorization spec names the two options
    # left, and this takes the first: a client id shipped with the tool. That is
    # what keeps `munim connect` a browser login for everyone rather than an
    # errand. A public client's id is not a secret, which is what makes shipping
    # it in a public repository correct rather than careless.
    "cloudflare": Provider(
        name="cloudflare",
        authorize_url="https://dash.cloudflare.com/oauth2/auth",
        token_url="https://dash.cloudflare.com/oauth2/token",
        issuer="https://dash.cloudflare.com",
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


class OAuthConnector:
    name = "oauth"

    def __init__(self, backend: KeychainBackend | None = None) -> None:
        self._backend = backend or KeychainBackend()

    def authorize_url(self, provider: str, client_id: str, state: str,
                      challenge: str) -> str:
        spec = PROVIDERS[provider]
        if spec.install_flow:
            # Everything else is configured in the console, so sending it here
            # is at best ignored and at worst rejected.
            return f"{spec.authorize_url}?{urllib.parse.urlencode({'state': state})}"
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

        # The listener runs in a thread so the browser can be opened while it
        # is already accepting: opening first and listening after loses a
        # callback from a provider that redirects immediately.
        answer: dict = {}

        def listen() -> None:
            try:
                answer.update(serve_until_callback(CALLBACK_PORT, timeout))
            except (TimeoutError, RuntimeError):
                pass

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

        url = self.authorize_url(provider, client_id, state, challenge)
        if open_browser:
            webbrowser.open(url)
        thread.join(timeout + 1)

        result = answer
        if not result:
            raise TimeoutError(
                f"no callback on {REDIRECT_URI} within {timeout:.0f}s; "
                "the browser flow did not complete"
            )
        if result.get("state") != state:
            # Mismatched state means the response is not ours. Never exchange it.
            raise ValueError("state mismatch; discarding the authorization response")

        # RFC 9207. State proves the response answers our request; the issuer
        # proves it came from the authorization server we sent the user to. In a
        # tool holding a dozen clients' grants across four providers, a response
        # from the wrong issuer is the mix-up attack this exists to stop, and it
        # is checked before the code is transmitted anywhere. Comparison is a
        # plain string match: RFC 3986 normalisation is explicitly forbidden.
        returned_issuer = result.get("iss")
        if returned_issuer is not None and spec.issuer:
            if returned_issuer != spec.issuer:
                raise ValueError(
                    f"issuer mismatch: the response came back from "
                    f"{returned_issuer!r}, not {spec.issuer!r}. Discarding it "
                    "without exchanging the code."
                )
        if "error" in result:
            raise RuntimeError(f"{provider} refused: {result.get('error_description', result['error'])}")

        data = {
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
        }
        if not spec.install_flow:
            data["code_verifier"] = verifier
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
