# Commands

The whole CLI. `munim doctor` says what is missing at any point, and the
exact command to fix each gap.

Two nouns, and every command reads as one of them. `connect` stays a verb
because it is an event rather than a thing.

**Clients, the businesses you look after**

```bash
munim clients                                # who you have, and what is connected
munim clients add "Ivy & Fern"               # write one down before connecting anything
munim clients add "Ivy & Fern" --domain ivyandfern.co.uk
munim clients rename "<old>" "<new>"         # the label; the id never changes
munim clients merge "<source>" "<target>"    # if one account became two clients
munim clients forget "<client>"              # only when it holds nothing
```

**Servers, what a client can be connected to**

```bash
munim servers                                # what Munim knows, and what each needs
munim servers add acme https://mcp.acme.com/mcp
```

**Connecting, which joins the two**

```bash
munim connect cloudflare                     # pick a client, or let the account name a new one
munim connect "Ivy & Fern" cloudflare        # attach to one you named
munim connect "Ivy & Fern" zoho --url https://…   # Zoho: the URL is the credential
munim connect "Ivy & Fern" stitch --token    # Stitch: an API key in a header
munim disconnect "Ivy & Fern" cloudflare
munim disconnect --all                       # drop every credential
```

**Everything else**

```bash
munim doctor                                 # what is missing, and the fix for each
munim config set gmail --client-id ...       # the secret is prompted, never an argument
munim config list                            # what is set, and where it came from
munim config unset gmail
```

There is no wrong order. Write a client down first and connect later, or
connect first and let the account name the client. Both arrive in the same
place.

A rename is only a label change. Credentials are filed under a client id that
never changes, so renaming cannot orphan a session.

The flat spellings 0.1.0 shipped (`munim rename`, `munim forget`, `munim merge`,
`munim add-server`) still work.

### Watching a run

The control room follows a run as it happens. It reads the same run log the
terminal does, so it can be opened mid-launch, or after one, and replays from the
beginning:

```bash
munim-room                              # http://127.0.0.1:8977
munim-room --port 8986                  # if 8977 is taken
munim-room --runs DIR --reports DIR     # serve a different set of runs
```

---
