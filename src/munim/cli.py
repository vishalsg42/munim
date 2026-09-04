"""`munim connect`: log in to a provider as one client.

Kept out of the MCP server on purpose. OAuth needs a browser and a callback
listener, which a stdio subprocess spawned by a coding agent has no business
opening. Running it as its own command also means the secret never passes
through the agent's context: the browser talks to the provider, the provider
talks to the callback, and the token goes straight to the keychain.
"""

import argparse
import os
import sys

from munim.connect.oauth import (PROVIDERS, SHIPPED_CLIENT_IDS,
                                 OAuthConnector)
from munim.connect.token import TokenConnector
from munim.container import KeychainBackend
from munim.env import load as load_env
from munim.registry import ClientRecord, Registry, UnknownClient

REGISTRY = None  # resolved at call time so tests can point it elsewhere


def _registry() -> Registry:
    from pathlib import Path
    return REGISTRY or Registry(Path.home() / ".munim" / "registry.json")


def _client_id(provider: str) -> tuple[str, str]:
    """OAuth app credentials for a provider.

    These identify *this tool* to the provider, not the client: one
    registration serves every client the operator connects. Where the provider
    supports public PKCE clients, Munim ships an id so nobody has to register
    anything, and the environment overrides it for anyone who would rather use
    their own.
    """
    prefix = provider.upper()
    client_id = (os.environ.get(f"{prefix}_OAUTH_CLIENT_ID")
                 or SHIPPED_CLIENT_IDS.get(provider, ""))
    return client_id, os.environ.get(f"{prefix}_OAUTH_CLIENT_SECRET", "")


def connect(client: str, provider: str) -> int:
    load_env()
    registry = _registry()
    try:
        registry.get(client)
    except UnknownClient:
        print(f"{client!r} is not registered yet. Adding it.", file=sys.stderr)
        registry.add(ClientRecord(name=client))

    backend = KeychainBackend()

    if provider not in PROVIDERS:
        print(f"{provider} publishes no OAuth endpoint, so it uses an API key.",
              file=sys.stderr)
        print(f"Paste one for {client}: ", end="", file=sys.stderr, flush=True)
        try:
            secret = input().strip()
        except EOFError:
            print("\nNothing pasted; not storing anything.", file=sys.stderr)
            return 2
        if not secret:
            print("Nothing pasted; not storing anything.", file=sys.stderr)
            return 2
        TokenConnector(backend).connect(client, provider, secret)
        print(f"Stored {provider} for {client}.", file=sys.stderr)
        return 0

    client_id, client_secret = _client_id(provider)
    if not client_id:
        print(
            f"No OAuth app registered for {provider}.\n"
            f"Create one, set its redirect URL to "
            f"http://localhost:8976/oauth/callback, then put the client id in "
            f".env as {provider.upper()}_OAUTH_CLIENT_ID.\n"
            f"Until then: munim connect {client} {provider} --token",
            file=sys.stderr)
        return 2

    print(f"Opening your browser to log in to {provider} as {client}…",
          file=sys.stderr)
    account = OAuthConnector(backend).connect(client, provider, client_id,
                                              client_secret or None)
    # Show which account was authorised: this is the one moment where the wrong
    # client can still be connected, and only a person can catch it.
    where = f" ({account})" if account else ""
    print(f"Connected {provider}{where} for {client}.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="munim", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("connect", help="log in to a provider as one client")
    c.add_argument("client")
    c.add_argument("provider", choices=sorted({*PROVIDERS, "resend"}))
    c.add_argument("--token", action="store_true",
                   help="paste an API key instead of logging in")

    ls = sub.add_parser("clients", help="list registered clients")
    ls.add_argument("--verbose", action="store_true")

    sub.add_parser("doctor", help="what is set up, what is not, and the next step")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from munim.doctor import run as doctor_run
        return doctor_run(_registry())

    if args.command == "clients":
        backend = KeychainBackend()
        for record in _registry().clients():
            from munim.container import Container
            container = Container(record.name, backend)
            connected = [p for p in ("cloudflare", "vercel", "resend")
                         if container.has(p)]
            print(f"{record.name:32} {record.domain or '-':32} "
                  f"{', '.join(connected) or 'nothing connected'}")
        return 0

    if args.token:
        backend = KeychainBackend()
        print(f"Paste the {args.provider} key for {args.client}: ",
              end="", file=sys.stderr, flush=True)
        try:
            secret = input().strip()
        except EOFError:
            secret = ""
        if not secret:
            print("\nNothing pasted; not storing anything.", file=sys.stderr)
            return 2
        TokenConnector(backend).connect(args.client, args.provider, secret)
        print("Stored.", file=sys.stderr)
        return 0

    return connect(args.client, args.provider)


if __name__ == "__main__":
    raise SystemExit(main())
