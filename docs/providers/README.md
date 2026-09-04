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
| [Stitch](stitch.md) | An API key in a header. No Google Cloud project needed |
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

---

## Anything not listed here

Eleven providers are built in, and only the first needed any code. Point Munim at
any other MCP server and it works out how that server authenticates:

```bash
munim add-server acme https://mcp.acme.com/mcp
munim connect "Acme Ltd" acme
munim servers                       # what Munim knows about, and what each needs
```

Built in: Cloudflare, Vercel, Resend, Netlify, Linear, Notion, Sentry, Supabase
(all zero setup, via dynamic client registration), Gmail (needs an application registered
by hand), Stitch (an API key in a header), Zoho (the endpoint URL is the
credential).

### Setting one up

Eight of the eleven need no setup at all. Three do, and each has a page with the
steps and what connecting grants:

| | |
|---|---|
| [Gmail](docs/providers/gmail.md) | An application registered by hand, once. About ten minutes, then `munim config set gmail --client-id ...` |
| [Stitch](docs/providers/stitch.md) | An API key in a header, pasted with `--token` |
| [Zoho](docs/providers/zoho.md) | No registration: the endpoint URL is the credential |

**[docs/providers/](docs/providers/README.md) has a page for every provider**,
including which have been connected live and which are only probed.

### What you are actually granting

**The provider decides, not Munim.** The MCP specification defines a scope
selection strategy, and it takes the scope from the server's own advertised
list. A client cannot ask for less: setting one is overwritten before the
authorize request is built. So connecting a provider grants what that provider
publishes, and it is worth reading the consent screen rather than clicking it.

Two that are worth knowing before you connect them:

| | |
|---|---|
| **[Gmail](docs/providers/gmail.md)** | Grants `https://mail.google.com/` among others: read, send and delete across the whole mailbox. Munim reads mail *configuration* and never sends, but the grant does not know that. |
| **[Supabase](docs/providers/supabase.md)** | Grants `database:write`, `storage:write`, `edge_functions:write`, `environment:write` and `secrets:read`. |

For a project whose subject is credential isolation this is the least
comfortable thing in it, and pretending otherwise would be worse. It is a
property of the specification rather than of this implementation, and it is
recorded in [`docs/ROADMAP.md`](docs/ROADMAP.md) with what would have to change.

The one exception is `offline_access`, which SEP-2207 explicitly permits a
client to add and which Munim adds, so a Vercel session refreshes for 30 days
instead of expiring in an hour.

---
