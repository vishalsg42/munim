# Cloudflare

registration confirmed working, token_endpoint_auth_method none

- Endpoint: `https://mcp.cloudflare.com/mcp`
- Registers a client on demand: **yes**

## Setup

None. Cloudflare issues Munim a client on demand, so connecting is a browser login
and nothing else.

```bash
munim connect cloudflare                 # pick a client, or let the account name one
munim connect "<client>" cloudflare      # or name the client yourself
```

## What you are granting

The consent screen names the client: **Munim (Your Client Name)**. That is the
check that catches authorising the wrong account, and it works here because
Munim registers a separate client per connection.

Scope includes `offline_access`, so the session refreshes rather than expiring.

## Verified

Two real accounts held concurrently in one process, returning disjoint results,
with no logout between them. That is the claim this whole project rests on, and
`scripts/cross_account_probe.py` reproduces it against your own accounts.

Three tools: `docs`, `search`, `execute`. Only `execute` reads live account
data, and it is also the only one that can write, so it carries no
`readOnlyHint` and is correctly excluded from cross-client tools. That is why
`ask_across_clients` can tell you which Cloudflare API would answer a question
but cannot answer it. See the README on what a connect grants.

## Gotchas

**Sign out of Cloudflare in your browser before connecting a second client.**
Otherwise the consent screen hands you the same account again and both clients
bind to it. This is the single most likely way to get a wrong result on day one.

## Check it

```bash
munim clients      # should list cloudflare for that client
munim doctor       # says what is missing, and the fix
```
