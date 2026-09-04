# Vercel

confirmed by registering, not by reading: both api.vercel.com/login/oauth/register and vercel.com/api/login/oauth/register answer HTTP 201 with token_endpoint_auth_method 'none' and no client_secret. The two authorization server documents disagree, and the one RFC 9728 selects is the one that understates what registration does. Connected live: 37 tools, which also answers the question this entry used to leave open, whether Vercel rejects a dynamically registered client at token exchange. It does not. Its session refreshes: the resource advertises only openid, so SEP-2207 applies and offline_access is added from the authorization server's list, which Vercel documents as issuing a refresh token good for 30 days with rotation

- Endpoint: `https://mcp.vercel.com`
- Registers a client on demand: **yes**

## Setup

None. Vercel issues Munim a client on demand, so connecting is a browser login
and nothing else.

```bash
munim connect vercel                 # pick a client, or let the account name one
munim connect "<client>" vercel      # or name the client yourself
```

## What you are granting

`openid offline_access`. Narrow, and the narrowest of any provider here.

## Gotchas

**Vercel publishes two authorization server documents that disagree.**

| Document | `token_endpoint_auth_methods_supported` |
|---|---|
| `mcp.vercel.com/.well-known/oauth-authorization-server` | `['none']` |
| `vercel.com/.well-known/oauth-authorization-server` | `['client_secret_basic', 'client_secret_post', ...]` |

RFC 9728 says the resource picks its authorization server, and it picks
`vercel.com`, so reading the specification correctly gives the answer that is
wrong in practice. Registering against either endpoint returns HTTP 201 with
`token_endpoint_auth_method: 'none'` and no secret. Vercel is a public client.

This entry was changed to confidential once on the strength of the metadata,
and the test suite caught it. Behaviour decides, not documents.

**Its session would expire in an hour without a workaround.** Vercel's resource
advertises only `openid`, so MCP's scope selection never asks for
`offline_access` even though Vercel's authorization server offers it and
documents it as issuing a refresh token good for 30 days. MCP SEP-2207 covers
exactly this and permits a client to add the scope. `munim/remote/offline.py`
does. Delete that module when `strands-agents` allows `mcp>=2.0.0`, which ships
the same rule.

## Verified

37 tools, live. Also settles a question this entry used to leave open: Vercel
does not reject a dynamically registered client at token exchange.

## Check it

```bash
munim clients      # should list vercel for that client
munim doctor       # says what is missing, and the fix
```
