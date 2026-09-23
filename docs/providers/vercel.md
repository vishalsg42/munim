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

## Reads come back empty, and the scope is not why

This section used to say the `openid offline_access` token was too narrow to
read anything, on the evidence that `list_projects` returned an empty list and
`get_deployment` answered "Deployment not found" for a deployment it had just
created. The evidence was real. The explanation was wrong.

Measured 2026-09-17 against a live session on a hobby team:

```
GET /v9/projects                                200, 18 projects
GET /v9/projects?teamId=team_...                200, projects: []
GET /v9/projects/prj_...?teamId=team_...        404  not_found
GET /v9/projects/prj_...?slug=<the team slug>   404  not_found
GET /v9/projects/<name>                         200, the whole project
GET /v2/user                                    200
GET /v2/teams                                   200, role OWNER of that team
```

The credential reads the user, reads the team it owns, and reads any project in
full. Nothing is out of scope. **Every call that fails has one thing in common:
a `teamId` or a `slug` in it.** Drop it and the same request returns 200.

The tell is the second line. Asking for the projects of a team returns none,
and every project in the first line has `accountId` equal to that same team. A
permission problem does not look like this. A lookup landing somewhere else
does.

Why, as far as it has been established: the token an MCP session issues is
already bound to one account context, so naming a team asks it to resolve
somewhere it does not map into, and Vercel answers 404 rather than 403. That
last part is inference. The table above is not.

### What it costs you

**Two of Vercel's own MCP tools cannot be called successfully at all.**
`get_project_deployment_protection` and `update_project_deployment_protection`
both mark `teamId` **required** in their schemas, so they always send the one
argument that breaks this credential. Neither the team id nor the team slug
works. Use the REST route instead, with no `teamId`:

```
call_provider_api <client> vercel GET   /v9/projects/<name>
call_provider_api <client> vercel PATCH /v9/projects/<name>  {"ssoProtection": null}
```

**A new project is created with Vercel Authentication on.** Every deployment URL
then redirects to a login, so the site you just deployed is unreachable by
anyone you send it to. The `PATCH` above is how to turn it off.

Since 0.7.0 Munim says both of these beside the provider's own answer rather
than leaving you to work them out. The answer itself is never altered.

## Verified

37 tools, live. Also settles a question this entry used to leave open: Vercel
does not reject a dynamically registered client at token exchange.

## Check it

```bash
munim clients      # should list vercel for that client
munim doctor       # says what is missing, and the fix
```
