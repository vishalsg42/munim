# Providers

One page each. Start here if you are connecting something for the first time.

## No setup at all

A browser login and nothing else. These run their own MCP server and issue
Munim a client on demand, so there is no application to register and no secret
anywhere in this repository.

| | | |
|---|---|---|
| [Cloudflare](cloudflare.md) | ✅ connected live | two accounts at once, verified |
| [Vercel](vercel.md) | ✅ connected live | 37 tools |
| [Supabase](supabase.md) | ✅ connected live | 29 tools |
| [Resend](resend.md) | probed | |
| [Netlify](netlify.md) | probed | |
| [Linear](linear.md) | probed | |
| [Notion](notion.md) | probed | |
| [Sentry](sentry.md) | probed | |

"Probed" means registration was confirmed against the live endpoint but nobody
has completed a login through Munim yet. It is expected to work, and that is not
the same as knowing.

## Setup required

| | |
|---|---|
| [Gmail](gmail.md) | An application registered by hand, once. About ten minutes |
| [Stitch](stitch.md) | The same, and unverified |
| [Zoho](zoho.md) | No registration: the endpoint URL is the credential |

## Anything else

Munim is not limited to this list. Point it at any MCP server and it works out
how that server authenticates:

```bash
munim add-server acme https://mcp.acme.com/mcp
munim connect "Acme Ltd" acme
```

## What connecting grants

**The provider decides, not Munim.** The MCP specification defines a scope
selection strategy and it takes the scope from the server's own advertised list.
A client cannot ask for less. So read the consent screen, and see each provider's
page for what it will ask for.

The two worth knowing before you click: [Gmail](gmail.md) grants read, send and
delete across the whole mailbox, and [Supabase](supabase.md) grants five write
scopes.
