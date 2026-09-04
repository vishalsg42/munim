# Notion

confirmed: registers clients at https://mcp.notion.com/register

- Endpoint: `https://mcp.notion.com/mcp`
- Registers a client on demand: **yes**

## Setup

None. Notion issues Munim a client on demand, so connecting is a browser login
and nothing else.

```bash
munim connect notion                 # pick a client, or let the account name one
munim connect "<client>" notion      # or name the client yourself
```

## What you are granting

Whatever this provider's resource metadata advertises. Munim cannot narrow it:
the MCP specification hands scope selection to the server. Read the consent
screen.

## Status

Registration confirmed by probing. **Not yet connected live**, so the tools it
offers and anything provider-specific in its flow are unverified. If you connect
it and something is surprising, that is worth an issue.

## Check it

```bash
munim clients      # should list notion for that client
munim doctor       # says what is missing, and the fix
```
