"""One HTTP call to a provider's own API, with one client's credential.

**Why this exists.** An operator put it exactly right: *the ceiling on what
munim can do for a provider is set by whoever wrote that provider's MCP server.*
Cloudflare publishes `execute`, so anything its API allows is reachable. Vercel
publishes a curated 37 tools, and the moment you need an environment variable, a
project setting or a domain attached there is nothing, and no way down a layer.
Munim is already holding the credential. This is the way down.

**It is the most powerful tool here, and the guard is small.** Every other tool
is bounded by a schema somebody else wrote. This one is bounded by a host check
and a run-log entry. Three decisions follow from that, and each is a decision
rather than an oversight:

**The host is asserted, not assumed.** `Container.http` sets `base_url`, and it
would be natural to think that pins the request. It does not. Measured against
the installed httpx:

    '/v9/projects'          -> https://api.vercel.com/v9/projects
    'https://evil.test/x'   -> https://evil.test/x        <- escapes entirely
    '//evil.test/x'         -> https://api.vercel.com/x   absorbed
    '/v9/../../x'           -> https://api.vercel.com/x   normalised

An absolute URL wins over `base_url`, and the client's `Authorization: Bearer`
goes with it, in cleartext if the scheme is `http`. So without a refusal here
this is a credential-exfiltration primitive: name any host, receive the token.
The path is validated before the request is built and the built request's host
is compared with the provider's before anything is sent. Belt and braces,
because the failure is not a broken call, it is a leaked credential.

**Every call is a mutation in the log, whatever the method.** "Read-only by
default" would really mean "GET by default", and an HTTP verb is a convention,
not an annotation. `passthrough` only records `observation` when the provider
itself said `readOnlyHint`; claiming it from a verb is the guess this codebase
refuses everywhere else.

**Response bodies are not logged.** A raw environment endpoint returns the
secret values `adapters/vercel.py` deliberately drops on the floor (D6). The log
records what was asked and what status came back, and never the answer.

**And it is not the universal escape hatch the request asked for.** It works for
the three providers with an auth profile, because those are the three whose REST
base URL and header shape are known. Inventing the others would be guessing.
"""

import httpx

from munim.container import UnsupportedProvider, _AUTH

# What a body is truncated to in the log. The body is what was *sent*, which the
# caller wrote and already has; it is recorded so a change can be traced back.
LOGGED_BODY = 1000

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
METHODS = SAFE_METHODS + ("POST", "PUT", "PATCH", "DELETE")


class UnsafePath(ValueError):
    """The path would have left the provider, taking the credential with it."""


def providers() -> list[str]:
    return sorted(_AUTH)


def check_path(provider: str, path: str) -> str:
    """The path to request, or `UnsafePath` naming why not.

    Separated from the call so it can be tested exhaustively without a
    container, a credential or a network.
    """
    if provider not in _AUTH:
        raise UnsupportedProvider(
            f"no API profile for provider {provider!r}. This works for: "
            f"{', '.join(providers())}")

    if not isinstance(path, str) or not path.strip():
        raise UnsafePath("path is required, and starts with '/'")
    path = path.strip()

    # `httpx.URL(...).is_absolute_url` rather than a string test: a string test
    # misses `HTTPS://evil.test` on case and wrongly rejects `https:/x`, which
    # parses relative and merges safely.
    if httpx.URL(path).is_absolute_url:
        raise UnsafePath(
            f"{path!r} is an absolute URL. This sends {provider}'s credential, "
            f"so it only ever goes to {_AUTH[provider][0]}. Pass a path.")

    if path.startswith("//"):
        # httpx absorbs this one, but only because of how it merges. Refuse it
        # rather than depend on that staying true.
        raise UnsafePath(f"{path!r} looks like a host, not a path.")

    if not path.startswith("/"):
        raise UnsafePath(f"{path!r} must start with '/'.")
    return path


def _host_of(url: str) -> str:
    return httpx.URL(url).host


async def call(container, provider: str, path: str, *, method: str = "GET",
               query: dict | None = None, body=None, log=None,
               stage: str = "api") -> dict:
    """Make the call. `container` is bound to one client and cannot widen."""
    path = check_path(provider, path)
    method = (method or "GET").upper()
    if method not in METHODS:
        raise ValueError(f"{method!r} is not an HTTP method this will send. "
                         f"One of: {', '.join(METHODS)}")

    expected = _host_of(_AUTH[provider][0])
    async with container.http(provider) as http:
        request = http.build_request(method, path, params=query or None,
                                     json=body if body is not None else None)
        # The second half of the belt and braces. If httpx ever merges
        # differently, this is what still stops the credential leaving.
        if request.url.host != expected:
            raise UnsafePath(
                f"that path would have gone to {request.url.host}, and this "
                f"credential is {provider}'s. Refused.")
        response = await http.send(request)

    out = {
        "provider": provider,
        "method": method,
        "path": path,
        "status": response.status_code,
        "failed": response.status_code >= 400,
    }
    try:
        out["result"] = response.json()
    except ValueError:
        out["result"] = response.text[:4000]

    if log is not None:
        # `mutation` whatever the method, and no response body. See the module
        # docstring: a verb is not an annotation, and the answer can be secret.
        sent = None
        if body is not None:
            import json as _json
            sent = _json.dumps(body)[:LOGGED_BODY]
        log.append(
            client=container.label, stage=stage, kind="mutation",
            human_text=f"{method} {path} on {provider} returned "
                       f"{response.status_code}",
            detail={"provider": provider, "method": method, "path": path,
                    "query": query or {}, "body": sent,
                    "status": response.status_code,
                    "failed": out["failed"]},
        )
    return out
