# Stitch

Google's design tool. Despite sharing an authorization server with
[Gmail](gmail.md), **none of Gmail's setup applies here.** Stitch takes an API
key in a header.

- Endpoint: `https://stitch.googleapis.com/mcp`
- Registers a client on demand: **no** (it does not use OAuth at all)
- Authenticates with: `X-Goog-Api-Key`
- 15 tools, 5 of them marked read-only

## Setup

Get a key from [Google AI Studio](https://aistudio.google.com/apikey), then:

```bash
munim connect "<client>" stitch --token
```

It is stored in your keychain, per client, like any other credential. No Google
Cloud project, no consent screen, no OAuth application, no test user list, and
none of the seven day token expiry that makes Gmail awkward.

## How this was nearly got wrong

Munim recorded Stitch as needing an application registered by hand, on the
reasoning that it shares an authorization server with Gmail and therefore shares
Gmail's consequences. That was wrong, and it would have sent people through ten
minutes of Google Cloud for a server that wants a header.

The correction came from looking at how a coding agent connects to the same
server:

```
stitch: https://stitch.googleapis.com/mcp
Headers: X-Goog-Api-Key: AQ.Ab8RN6...
```

No OAuth anywhere. **Sharing an authorization server says nothing about whether
one is used.** This is the third time on this project that a conclusion drawn
from metadata rather than from behaviour turned out to be wrong, after
[Supabase](supabase.md) and [Vercel](vercel.md).

It also exposed a gap: Munim knew three ways to authenticate and this was a
fourth, so it could not have connected Stitch by any route. `header` is an auth
kind now, and any MCP server that takes a key in a header works the same way:

```bash
munim add-server acme https://mcp.acme.com/mcp
```

## What you are granting

Whatever the key grants. There is no scope parameter and no consent screen,
because there is no authorization flow: the key is the credential, the way
[Zoho's](zoho.md) URL is.

Treat it accordingly. `munim disconnect "<client>" stitch` removes it.

## Status

**Not yet connected through Munim.** The header route is implemented and
tested, and the endpoint and header name are taken from a working connection,
but nobody has completed `munim connect ... stitch --token` yet.

## Check it

```bash
munim clients      # should list stitch for that client
munim doctor       # says what is missing, and the fix
```
