# Registering the Vercel integration

Everything the Create Integration form asks for, filled in. Copy-paste.

**Where:** Vercel dashboard → your team → **Integrations** (sidebar) →
**Integrations Console** → **Create**.

**Note on time:** this is not five minutes. The form requires a logo, feature
media, a EULA URL and a privacy policy URL, all mandatory. Those are written and
committed under `brand/` — the values below point at them.

**Good news:** a connectable-account integration is usable the moment it is
created. It gets a *Community* badge and does not need approval. Only listing on
the public marketplace requires review, and 500 installs.

---

## The form

| Field | Value |
|---|---|
| **Name** | `Munim` |
| **URL Slug** | `munim` |
| **Developer** | Your name or registered company |
| **Contact Email** | Yours — not shown publicly |
| **Support Contact Email** | Yours — **is** shown publicly |
| **Short Description** | Look after several clients' web and email setup from inside your coding agent, without logging out of anything. |
| **Logo** | `brand/logo.svg` |
| **Category** | Developer Tools *(or the nearest available)* |
| **Website** | `https://github.com/vishalsg42/munim` |
| **Documentation URL** | `https://github.com/vishalsg42/munim#readme` |
| **EULA URL** | `https://github.com/vishalsg42/munim/blob/main/brand/EULA.md` |
| **Privacy Policy URL** | `https://github.com/vishalsg42/munim/blob/main/brand/PRIVACY.md` |
| **Redirect URL** | `http://localhost:8976/oauth/callback` |
| **Accent colour** | optional, skip |
| **Webhook URL** | leave blank — Munim consumes no webhooks |
| **Configuration URL** | leave blank |

### Overview

> Munim is an MCP server for people who look after other people's
> infrastructure. One person maintains the websites and email for a dozen small
> businesses; the clients own the accounts, and every provider allows one login
> at a time.
>
> Munim gives each client an isolated container holding only that client's
> credentials, so the operator can read across all of them at once and write
> only inside one they have named. It checks the things that fail silently —
> a second sender policy added beside an existing one, a DKIM record published
> behind a proxy, an environment variable changed after the last build — and
> fixes them with the operator's approval.
>
> It is free and open source under the MIT licence.

### API Scopes

Request only what is used, and nothing that can spend money or change billing:

| Scope | Why |
|---|---|
| **Projects: Read** | List projects; find the one a client's site is on |
| **Deployments: Read** | Tell whether the live site is the last successful build |
| **Project Environment Variables: Read/Write** | Vercel offers **no read-only option** for this scope. Munim only ever reads, and only names and scopes, never values. Say so plainly in Instructions rather than letting the permission speak for itself |
| **Domains: Read** | Check a custom domain is attached and its certificate is valid |

Add **Domains: Read/Write** and **Deployments: Read/Write** only when the write
path ships. Asking for less than you need is easy to widen; asking for more than
you need is what makes people decline an install.

### Feature Media (1–8 images, 16:9, **minimum 1920x1080**)

`docs/stills/feature-01-the-finding.png` is ready and correctly sized. Reuse the
rest of the gallery stills — see `docs/stills/README.md`:

1. The launch mid-flight, check grid lighting up
2. The SPF finding, with raw resolver output and timestamp
3. The launch report, written for the business owner

---

## Afterwards

The **Client ID** and **Client Secret** appear at the bottom of the integration's
settings page, under **Credentials**. Put them in `.env`:

```
VERCEL_OAUTH_CLIENT_ID=...
VERCEL_OAUTH_CLIENT_SECRET=...
```

Then:

```bash
munim doctor                                  # should show the app registered
munim connect "Balaji Roofings" vercel        # browser opens; log in as that client
```

It prints which account was authorised. Check it — that is the one moment where
the wrong client can still be connected, and only a person can catch it.
