# Supabase

confirmed: registers clients at https://api.supabase.com/platform/oauth/apps/register, and issues a secret, so the session authenticates with client_secret_post rather than as a public client

- Endpoint: `https://mcp.supabase.com/mcp`
- Registers a client on demand: **yes**

## Setup

None. Supabase issues Munim a client on demand, so connecting is a browser login
and nothing else.

```bash
munim connect supabase                 # pick a client, or let the account name one
munim connect "<client>" supabase      # or name the client yourself
```

## What you are granting

Thirteen scopes, including `database:write`, `storage:write`,
`edge_functions:write`, `environment:write` and `secrets:read`.

Munim cannot ask for less. The MCP specification hands scope selection to the
server, and Supabase's resource advertises all of them. Read the consent screen
before accepting it.

## Gotchas

**Supabase is a confidential client that forgets to say so.** Its registration
response carries a `client_secret` and leaves `token_endpoint_auth_method`
null. Stored as-is, the next token exchange reads that null, decides it is a
public client, sends no secret, and Supabase answers `Required parameter:
client_secret`. Munim fills the field in on the way to the keychain.

RFC 7591 says an omitted method means `client_secret_basic`, and that is also
wrong here: basic auth moves the secret into an Authorization header and out of
the body, which is the parameter Supabase wants. `client_secret_post`, which is
what the registration asked for, is the right answer.

**It was nearly deleted from this project.** The server table did not list it,
and absence from our own table was mistaken for evidence about Supabase. It runs
a hosted MCP server with dynamic client registration. Documents describe;
behaviour decides.

## Verified

29 tools, live.

## Check it

```bash
munim clients      # should list supabase for that client
munim doctor       # says what is missing, and the fix
```
