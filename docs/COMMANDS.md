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
munim config                                 # everything: applications and agents
munim config app set gmail --client-id ...   # the secret is prompted, never an argument
munim config app list                        # what is set, and where it came from
munim config app unset gmail

munim config ai                              # agents on or off, host, model, keys
munim config ai on | off                     # off by default; Munim is local
munim config ai host gemini                  # auto | bedrock | gemini | anthropic
munim config ai model gemini gemini-2.5-pro  # per host, so switching cannot mismatch
munim config ai key gemini                   # prompts, goes to your keychain
munim config ai unset gemini
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


## Agents are off by default

`check`, `work_on_client` and `ask_across_clients` can explain what they find,
and that needs a model host. It is switched off until you ask for it, so a key
sitting in a file is not the same as deciding to use one. Everything else in
Munim is deterministic and unaffected: the thirteen checks, `audit_all_clients`,
`find_across_clients` and the mail plan all work with no key and no model call.

`munim config ai on` takes effect on the next tool call. There is no need to
reconnect your coding agent: the setting is read when a tool runs, not when the
server starts.

The old spellings still work. `munim config set gmail --client-id ...` and
`munim config list` were published in 0.1.0 and are rewritten to the `app` form
rather than broken.

Two things worth knowing about where the switch is read from:

- `MUNIM_AI` in a `.env` file is ignored. Values from a file are written into
  the process environment permanently, and the MCP server loads once at startup,
  so a switch set that way would go sticky and silently beat every later
  `munim config ai on`. `munim doctor` reports one if it finds it.
- `export MUNIM_AI=1` in your shell changes what `munim doctor` reports and not
  what the MCP server does, because the server is a subprocess and does not
  inherit your shell. `doctor` says so rather than letting the two disagree
  quietly.
