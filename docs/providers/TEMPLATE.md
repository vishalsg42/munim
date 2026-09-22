# Provider page template

Copy this to `docs/providers/<name>.md`, fill it in, and delete this first
section. Every heading below earns its place: a test asserts some of them, and
the rest are the questions somebody asked after connecting and not finding an
answer.

The one part nobody else can write for you is **Verified**. Everything above it
is describable from the table row. What you measured is the part a reviewer
cannot reproduce without your account.

Three phrases are checked by `tests/test_provider_docs.py` and have to be typed
exactly when they apply:

- `Registers a client on demand: **no**` when `auth` is not `registers`
- `Endpoint: **per installation**` and `--url` when `per_client_url` is set
- Do not write "probed" on a page you want listed as connected live

---

# <Provider>

<The note from the row, verbatim. It says what was measured and when.>

- Endpoint: `<url>`   *(or `**per installation**` when each install has its own)*
- Registers a client on demand: **yes** / **no**

## Setup

None, when the authorization server issues a client on demand. Say so plainly
and show the command:

```bash
munim connect <name>                 # pick a client
munim connect "<client>" <name>      # or name the client yourself
```

When something has to be supplied by hand, say what, where it comes from, and
roughly how long it takes. `gmail.md` is the worked example for an application
registered by hand; `zoho.md` is the one for an address supplied with `--url`.

## What you are granting

The provider decides this, not Munim: the MCP specification takes the scope
from the server's own advertised list and a client cannot ask for less. So read
the consent screen and write down what it actually said. If it grants more than
the reader would expect, that is the most useful sentence on the page.

## Verified

What you ran, what came back, and the date. For example:

```
2026-09-15  tools/list with no credentials  ->  401, www-authenticate: Bearer
2026-09-15  connected live                  ->  14 tools, 5 marked readOnlyHint
```

If you added the row from `munim servers add` and never completed a login, say
that instead. "Probed, not connected" is a useful and honest state, and the
index has a column for it.

## Gotchas

The thing that cost you an hour. Leave this out if there was not one.

## Check it

```bash
munim clients      # should list <name> for that client
munim doctor       # says what is missing, and the fix
```
