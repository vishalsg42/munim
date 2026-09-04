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

Copy the two values into `.env`:

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
