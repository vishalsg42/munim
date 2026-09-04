"""Where each provider's own MCP server lives, and what it can be asked for.

Every one of these was probed on 2026-09-04 by following the MCP discovery
chain from an unauthenticated request: 401 with `WWW-Authenticate`, then
protected resource metadata, then authorization server metadata. All three
advertise a registration endpoint, which is what makes a session per client
possible without anyone registering an application first (D25).
"""

import json
from dataclasses import dataclass
from pathlib import Path


# How a provider expects to be authenticated. Three of these turned up in one
# afternoon of probing, and the first version of this file could only express
# the first, which is why it is written down rather than assumed.
#
#   registers   the authorization server issues a client on demand (RFC 7591),
#               so nobody registers an application and no secret is shipped.
#               Cloudflare, Vercel and Resend, all confirmed by registering.
#   app         an application must be registered by hand and its secret
#               supplied. accounts.google.com advertises no registration
#               endpoint and requires client_secret_post, so every Google
#               server lands here.
#   url         the endpoint URL contains the credential. Zoho issues a
#               per-installation path, so there is no OAuth at all and the URL
#               is the thing to keep secret.
AUTH_KINDS = ("registers", "app", "url")


@dataclass(frozen=True)
class RemoteServer:
    provider: str
    url: str
    # Whether the authorization server will issue a client without a secret.
    # Where it will not, registration issues one at run time and it is stored
    # beside the tokens; it is never a value in this repository.
    public_client: bool
    note: str = ""
    auth: str = "registers"
    # Set for `app` providers: what has to be registered, and where.
    register_at: str = ""
    # What to ask this provider for, on the routes where the ask is ours to
    # make. That is the application route in connect/oauth.py, which builds its
    # own authorize URL.
    #
    # It is NOT the MCP route. The spec defines a Scope Selection Strategy and
    # the SDK implements it in mcp/client/auth/utils.py: the scope comes from
    # the WWW-Authenticate challenge, else the resource's scopes_supported,
    # else the authorization server's, and whatever the client set is
    # discarded. So on that route the provider decides, and connecting Supabase
    # asks for database:write and storage:write for a tool that has never
    # written to Supabase.
    #
    # Recorded here anyway, because it is where the intent belongs and because
    # the app route is exactly where the providers that most need narrowing end
    # up: Gmail cannot register a client on demand, so it goes that way.
    scopes: tuple[str, ...] = ()

    def __post_init__(self):
        if self.auth not in AUTH_KINDS:
            raise ValueError(f"{self.provider}: unknown auth kind {self.auth!r}")

    @property
    def ready(self) -> bool:
        """Whether connecting needs nothing set up first."""
        return self.auth == "registers"


SERVERS: dict[str, RemoteServer] = {
    "cloudflare": RemoteServer(
        provider="cloudflare",
        url="https://mcp.cloudflare.com/mcp",
        public_client=True,
        note="registration confirmed working, token_endpoint_auth_method none",
    ),
    "vercel": RemoteServer(
        provider="vercel",
        url="https://mcp.vercel.com",
        public_client=True,
        # Public, and the metadata says otherwise twice over. Vercel serves two
        # authorization server documents that disagree with each other:
        #
        #   mcp.vercel.com/.well-known/oauth-authorization-server -> ['none']
        #   vercel.com/.well-known/oauth-authorization-server
        #       -> ['client_secret_basic', 'client_secret_post', ...]
        #
        # RFC 9728 says the resource picks its authorization server and it
        # picks vercel.com, so reading the spec correctly gives the answer that
        # is wrong in practice. Registering against either endpoint returns
        # HTTP 201, token_endpoint_auth_method 'none' and no secret.
        #
        # Recorded here because the wrong answer is the well-reasoned one, and
        # this entry has already been changed to `False` once on the strength
        # of the metadata before a registration put it back.
        note="confirmed by registering, not by reading: both "
             "api.vercel.com/login/oauth/register and "
             "vercel.com/api/login/oauth/register answer HTTP 201 with "
             "token_endpoint_auth_method 'none' and no client_secret. The two "
             "authorization server documents disagree, and the one RFC 9728 "
             "selects is the one that understates what registration does. "
             "Connected live: 37 tools, which also answers the question this "
             "entry used to leave open, whether Vercel rejects a dynamically "
             "registered client at token exchange. It does not",
        # offline_access is not decoration. Narrowing to "openid" alone, which
        # is all the resource document advertises, produced a session with no
        # refresh token that died in an hour and needed a full browser login to
        # come back. The authorization server advertises offline_access even
        # though the resource does not, and a scope list that omits it turns a
        # long lived session into a one hour one without saying so.
        scopes=("openid", "offline_access"),
    ),
    # No single address: each installation gets its own, and the path carries
    # the credential. The URL is therefore per client and lives in the keychain,
    # not here. `munim connect "<client>" zoho --url <their URL>`.
    "zoho": RemoteServer(
        provider="zoho",
        url="",
        public_client=False,
        auth="url",
        note="confirmed: per-installation endpoint of the shape "
             "https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message, which "
             "answers a tool call with no credentials because the path is the "
             "credential",
    ),
    # These four needed no code. Cloudflare has an adapter because it came
    # first, before there was a way to ask a server how it wants to be
    # authenticated. Everything below is a table entry with the answer probing
    # gave, which is what the wrapper design is for: a provider stops being
    # work and becomes a row.
    # Cut during planning as "a fifth provider with zero video value", and the
    # cut left it half-present: `connect` offered it, `doctor` told everyone to
    # register an OAuth application for it, and nothing could use the result.
    # It turns out to run a hosted MCP server with dynamic client registration,
    # so the honest fix was to finish it rather than remove it. Probed, not read.
    "supabase": RemoteServer(
        provider="supabase", url="https://mcp.supabase.com/mcp",
        public_client=False, auth="registers",
        note="confirmed: registers clients at "
             "https://api.supabase.com/platform/oauth/apps/register, and issues "
             "a secret, so the session authenticates with client_secret_post "
             "rather than as a public client",
    ),
    "netlify": RemoteServer(
        provider="netlify", url="https://netlify-mcp.netlify.app/mcp",
        public_client=True, auth="registers",
        note="confirmed: registers clients at "
             "https://netlify-mcp.netlify.app/oauth-server/reg",
    ),
    "linear": RemoteServer(
        provider="linear", url="https://mcp.linear.app/mcp",
        public_client=True, auth="registers",
        note="confirmed: registers clients at https://mcp.linear.app/register",
    ),
    "notion": RemoteServer(
        provider="notion", url="https://mcp.notion.com/mcp",
        public_client=True, auth="registers",
        note="confirmed: registers clients at https://mcp.notion.com/register",
    ),
    "sentry": RemoteServer(
        provider="sentry", url="https://mcp.sentry.dev/mcp",
        public_client=True, auth="registers",
        note="confirmed: registers clients at https://mcp.sentry.dev/oauth/register",
    ),
    "resend": RemoteServer(
        provider="resend",
        url="https://mcp.resend.com/mcp",
        public_client=True,
        note="registration confirmed: HTTP 201, token_endpoint_auth_method none, "
             "no secret",
    ),
}


# Probed 2026-09-04 by following the discovery chain from an unauthenticated
# call. Recorded whether or not they are wired up, because "does this provider
# run an MCP server" is the question that decides the architecture, and
# answering it from memory is how two providers were wrongly recorded as having
# none (D25).
NOT_YET_WIRED: dict[str, RemoteServer] = {
    "_example": RemoteServer(
        provider="_example", url="https://mcp.example.test/mcp",
        public_client=True, auth="registers",
        note="confirmed: placeholder so this table is never empty"),
}

_GOOGLE = {
    "gmail": RemoteServer(
        provider="gmail", url="https://gmailmcp.googleapis.com/mcp/v1",
        public_client=False, auth="app",
        register_at="https://console.cloud.google.com/apis/credentials",
        note="confirmed by probing: 23 tools, 6 annotated readOnlyHint, which is better than "
             "Cloudflare manages. accounts.google.com advertises no "
             "registration_endpoint and only client_secret_post and "
             "client_secret_basic, so an application must be registered by "
             "hand. Google's installed-application client type treats the "
             "secret as not confidential, which is how every CLI ships one",
        # Not https://mail.google.com/, which Google also advertises here and
        # which grants read, send and delete on the entire mailbox. Munim reads
        # a domain's mail setup and, at most, changes records that serve it.
        # `modify` covers labelling and drafting without granting hard delete;
        # `readonly` covers everything the check catalogue needs.
        #
        # These are Google restricted scopes either way, so an application
        # using them stays limited to its own test users until it passes
        # Google verification. That is a reason to ask for less, not more.
        scopes=("https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.modify"),
    ),
    "stitch": RemoteServer(
        provider="stitch", url="https://stitch.googleapis.com/mcp",
        public_client=False, auth="app",
        register_at="https://console.cloud.google.com/apis/credentials",
        note="confirmed by probing: 15 tools, 5 annotated readOnlyHint. Same authorization server as "
             "gmail and the same consequence",
    ),
}

# Google's servers work for anyone who registers an application, which is what
# `app` means. They are in SERVERS rather than waiting, because "needs an
# application" is a state a provider can be in rather than a reason to be
# absent: `munim servers` says which, and connecting says how.
SERVERS.update(_GOOGLE)


# Servers the operator added themselves. The three above are not the product:
# the product is a session per client against something that speaks MCP, and
# there is no reason it has to be a server somebody else chose.
USER_SERVERS = Path.home() / ".munim" / "servers.json"


def _user_servers() -> dict[str, RemoteServer]:
    if not USER_SERVERS.exists():
        return {}
    try:
        raw = json.loads(USER_SERVERS.read_text())
    except (OSError, ValueError):
        # A malformed file must not take every provider down with it. The
        # built-ins keep working and `munim servers` says the file is unreadable.
        return {}
    out = {}
    for name, entry in raw.items():
        try:
            out[name] = RemoteServer(provider=name, **entry)
        except (TypeError, ValueError):
            continue
    return out


def all_servers() -> dict[str, RemoteServer]:
    """Built in, then whatever the operator added. Theirs wins: someone who
    points a name at their own server means it."""
    return {**SERVERS, **_user_servers()}


def remember(server: RemoteServer) -> None:
    USER_SERVERS.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if USER_SERVERS.exists():
        try:
            existing = json.loads(USER_SERVERS.read_text())
        except (OSError, ValueError):
            existing = {}
    existing[server.provider] = {
        "url": server.url, "public_client": server.public_client,
        "auth": server.auth, "note": server.note,
        "register_at": server.register_at,
    }
    USER_SERVERS.write_text(json.dumps(existing, indent=2, sort_keys=True))


def server_for(provider: str) -> RemoteServer | None:
    """None rather than a guess. A provider with no MCP server is absent from
    this table, not represented by a plausible-looking URL (D11)."""
    return all_servers().get(provider)
