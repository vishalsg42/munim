# Zoho

confirmed: per-installation endpoint of the shape https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message, which answers a tool call with no credentials because the path is the credential

- Endpoint: `per installation, see below`
- Registers a client on demand: **no**

## Setup

Zoho gives each installation its own endpoint, and **the path is the
credential**. There is no OAuth and no browser step: the address is the secret,
so it goes to your keychain rather than into any file in this repository.

```bash
munim connect "<client>" zoho --url https://<service>-<org>.zohomcp.in/mcp/<32 hex>/message
```

Get that URL from your own Zoho MCP installation.

## What you are granting

Whatever the endpoint grants. Munim has no say: there is no scope parameter and
no consent screen, because there is no authorization flow.

## Gotchas

**Anyone holding the URL holds the access.** That is why `munim connect` puts it
in the keychain and why `munim clients` and error messages redact it. Treat the
URL the way you would treat a password.

**There is no account to verify.** Every other provider is asked which account a
session belongs to, so connecting the wrong one is caught. A URL cannot be
asked, so `munim connect --url` prompts for which client it belongs to instead.

## Check it

```bash
munim clients      # should list zoho for that client
munim doctor       # says what is missing, and the fix
```
