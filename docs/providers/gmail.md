# Gmail

Gmail is the one provider that needs setting up before you can connect it, and
it takes about ten minutes the first time. Everything else in Munim is a browser
login and nothing else.

**You may not need this.** Nothing in Munim reads mail today. Gmail is here
because managing a small business's mail is adjacent to managing its DNS, and
because the tools exist. If you are here to check SPF and DKIM records, the
check catalogue does that with no credentials at all and you can skip this page.

- Endpoint: `https://gmailmcp.googleapis.com/mcp/v1`
- Registers a client on demand: **no**
- 23 tools, 6 of them marked read-only

## Why this one is different

Every other provider runs an authorization server that will issue Munim a client
the moment it asks. Google's will not. `accounts.google.com` publishes no
registration endpoint, so somebody has to register an application by hand, once.

Your coding agent's own Gmail connector works without setup only because the
agent itself is a registered Google application. Munim is a client too, so it
needs its own, and **shipping one with the package is not an option**: it would
put a shared secret in an open source project, and Google would require
verification and a security assessment before it worked for anyone but us.

So you register your own. It is yours, it stays in your `.env`, and it serves
every client you connect.

## Setup

### 1. Have a Google Cloud project

If you already have one, use it. If you have never made one:

```bash
gcloud projects create my-munim-project --name="Munim"
gcloud config set project my-munim-project
```

Project ids are globally unique, so you may need a suffix. No billing account is
required for what follows.

### 2. Run the helper

```bash
uv run python scripts/setup_google_oauth.py --provider gmail
```

It enables the Gmail API on the project you already have selected and prints the
remaining steps with your project id filled in. It **never creates a project**,
because project ids are global and a script that makes one per run leaves a
trail behind. Rerunning it is safe: a client id already in `.env` means there is
nothing to do.

If you do not have `gcloud`, enable the Gmail API here instead:
`https://console.cloud.google.com/apis/library/gmail.googleapis.com`

### 3. Configure the consent screen, once per project

**Do this before trying to create a client.** A project that has never had a
consent screen answers the create-client page with *"To create an OAuth client
ID, you must first configure your consent screen"*, which is where most people
get stuck.

`https://console.cloud.google.com/auth/overview/create?project=YOUR_PROJECT`

| Field | What to put |
|---|---|
| App name | Anything. It appears on the consent screen |
| User support email | Your own |
| Audience | **External**, unless you have a Google Workspace organisation |
| Contact information | Your own |

Then agree to the user data policy and **Create**.

"External" sounds alarming and is not: it means the app is not restricted to a
Workspace domain. It starts in testing mode and works only for accounts you list
as test users, which is the next step.

### 4. Create the OAuth client

`https://console.cloud.google.com/auth/clients/create?project=YOUR_PROJECT`

Application type: **Desktop app**. Name it anything. Create.

Copy the two values into `~/.munim/.env`, which is the location that works
regardless of where you run from:

```
GMAIL_OAUTH_CLIENT_ID=...apps.googleusercontent.com
GMAIL_OAUTH_CLIENT_SECRET=...
```

If you choose "Web application" instead, add
`http://localhost:8976/oauth/callback` as an authorised redirect URI.

### 5. Add yourself as a test user

`https://console.cloud.google.com/auth/audience?project=YOUR_PROJECT`

**This is not optional.** Gmail uses Google *restricted* scopes, so an
unverified application only works for accounts on that list. Add every Google
account whose mail you intend to connect.

There is no API for this. Google's own guidance describes the Console flow and
nothing else, the IAP brand resource has no test-user field, and the IAP OAuth
Admin API that once managed brands was shut down in March 2026. So this step is
by hand, per account, capped at 100 for the lifetime of the app, and removals
still count against the cap.

### 6. Connect

```bash
munim connect "<client>" gmail
munim doctor
```

## What you are granting

Read the consent screen. It will ask for, among others,
`https://mail.google.com/`, which is **read, send and delete across the whole
mailbox**.

Munim reads mail *configuration* and never sends, but the grant does not know
that, and **Munim cannot ask for less**. The MCP specification hands scope
selection to the server and Google's resource advertises the full set. This is
the least comfortable thing in this project and it is a property of the
specification rather than of this implementation.

## The seven day expiry, and the button that removes it

**In Testing, a Gmail session dies after seven days.** Google: *"A Google Cloud
Platform project with an OAuth consent screen configured for an external user
type and a publishing status of 'Testing' is issued a refresh token expiring in
7 days, unless the only OAuth scopes requested are a subset of name, email
address, and user profile."*

Gmail's scopes are far beyond that subset. Every other provider here holds a
session that refreshes, so this is Gmail's alone.

**Publishing the app removes it, and this project has done that.** The seven
days are a property of Testing status, not of verification, and Google's own
documentation never conditions the expiry on being verified. Press **Publish
app** on the Audience page and the limit lifts. Publishing is reversible: the
button becomes "Back to testing".

Publishing needs three things filled in on the Branding page first, and the
button stays disabled until they are: an application home page, a privacy policy
link and a terms of service link, plus the domain listed under Authorized
domains. Those pages have to be publicly reachable, so a host that puts a login
in front of them does not count. `site/` in this repository is the three pages
Munim uses, ready to deploy anywhere static.

`https://console.cloud.google.com/auth/audience?project=YOUR_PROJECT`

What you accept in exchange, and the third one is permanent:

- An **unverified app** warning screen before consent, which users click through.
- Your **app name and logo are not shown** on the consent screen, because brand
  verification has not been done.
- A **hard cap of 100 users over the lifetime of the project**. Google: it
  "applies over the entire lifetime of the project, and it cannot be reset or
  changed." Worth reading precisely: the cap "limits the number of users that
  can grant permission to your app when requesting **unapproved** sensitive or
  restricted scopes", and "does not apply if you are requesting only approved
  sensitive or restricted scopes". So verification lifts the cap rather than
  merely removing the warning.

Google explicitly sanctions running this way: *"If the app is for your personal
use (fewer than 100 users), you and your limited number of users can continue
using the app without going through verification."*

So publishing is the right move for a self-hosted tool, and the 100 is the real
ceiling rather than the warning screen.

Note one revocation rule that still applies in production: a refresh token
holding Gmail scopes is revoked when the user changes their Google password.
Also after six months of non-use.

## If you ever need more than 100 users

Full verification. Restricted scopes make it the heaviest tier:

- A **homepage on a domain you own**, publicly accessible, ownership verified in
  Google Search Console.
- A **privacy policy on that same domain**, linked from both the homepage and
  the consent screen.
- A **demo video** showing the whole OAuth flow, the consent screen with the
  exact scopes, and each restricted scope in use.
- Probably a **CASA security assessment** by a third-party assessor, **$500 to
  $4,500**, taking two to six weeks, renewed every twelve months. Google charges
  nothing itself. The free self-scan route is deprecated.

Whether CASA applies to a purely local client that stores tokens on the device
and talks only to Google is **not clearly documented**. Google's trigger is
having "the ability to access data from or through a third-party server". Munim
is local, so it arguably does not, and Google does not say.

Narrowing the scopes does not avoid any of this: `gmail.readonly` is classified
restricted exactly like `https://mail.google.com/`. It may affect the assurance
level, whose weights Google does not publish.

## Gotchas

**The consent screen cannot name the client.** For Cloudflare and Vercel it
reads "Munim (Kloudfirst)", because Munim registers a separate client per
connection, and that is the check that catches authorising the wrong account.
Google's app name is fixed per project, so every Gmail connection shows the same
name. You lose that safety net here. Check which Google account you are signed
in as before accepting.

**A leaked client id does not expose a mailbox.** It identifies the application,
not a user. Google's own guidance is that installed apps "cannot keep secrets"
and that the secret is optional for desktop clients, which is why every CLI
ships one. What someone could do with it is show a consent screen bearing your
app's name. Reading mail still needs a person to consent, and on an unverified
application only a test user you added can.

**Cost: none.** Google states that all standard use of the Gmail API is
available at no additional cost, under a daily threshold of 80,000,000 quota
units. Munim's usage is a handful of reads. Google has said charges above the
quota limits are planned later in 2026, with at least 90 days' notice.

## Check it

```bash
munim clients      # should list gmail for that client
munim doctor       # says what is missing, and the fix
```
