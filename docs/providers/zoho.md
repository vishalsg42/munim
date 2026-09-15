# Zoho

Confirmed 2026-09-15: a per-installation endpoint of the shape
`https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message` answers `tools/list`
with 401 and a `Bearer` challenge. Its protected resource metadata names a
per-installation authorization server under `mcp.zoho.in/baas/`, which
advertises a registration endpoint and accepts `token_endpoint_auth_method`
`none`.

- Endpoint: **per installation**, so you supply it
- Registers a client on demand: **yes**, at that installation's own
  authorization server

## Setup

Nothing to register and no application to create. Zoho gives each installation
its own address, so the only thing munim cannot work out for itself is which
address is yours.

```bash
munim connect "<client>" zoho --url https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message
```

Get that URL from your own Zoho MCP installation. Munim records it in your
keychain, then opens the browser for the login that address asks for.

Two clients can hold two different installations, including in different
regions: the authorization server is discovered from the address, so a `.in`
installation and a `.com` one authenticate against their own.

## What you are granting

Whatever the consent screen names when the browser opens. Munim requests no
scopes of its own here: the installation's authorization server decides what
the token carries.

## Gotchas

**The address is worth protecting even though it is not the whole credential.**
An earlier reading of this provider concluded the path *was* the credential,
because one tool call answered without one. It was a measurement of a single
tool rather than of the server. Munim still keeps the URL in the keychain and
still redacts it in `munim clients` and in error messages, and that is the right
default for an address nobody else needs to see.

**Connecting needs the address first.** `munim connect "<client>" zoho` without
`--url` has nothing to connect to and says so, naming the flag. There is no
shared address to fall back on.

**There is no account check.** Every provider munim can ask is asked which
account a session belongs to, so connecting the wrong one is caught. Zoho is not
asked, so the client you name is the client it is filed under.

## Check it

```bash
munim clients      # should list zoho for that client
munim doctor       # says what is missing, and the fix
```
