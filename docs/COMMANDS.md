# Commands

The whole CLI. `munim doctor` says what is wrong at any point, and the
exact command to fix each gap.

Two nouns, and every command reads as one of them. `connect` stays a verb
because it is an event rather than a thing.

**Clients, the businesses you look after**

```bash
munim clients                                # navigable on a terminal, a table in a pipe
munim clients add "Ivy & Fern"               # write one down before connecting anything
munim clients add "Ivy & Fern" --domain ivyandfern.co.uk
munim clients rename "<old>" "<new>"         # the label; the id never changes
munim clients merge "<source>" "<target>"    # if one account became two clients
munim clients forget "<client>"              # only when it holds nothing
```

On a terminal `munim clients` navigates rather than printing: clients, the
providers under each with whether the session actually still opens, that
provider's tools, and one tool in full. Arrow keys or a number, Enter to go in,
Esc to come back up. Piped or redirected it stays the same table it always was,
and `--json` never touches the network.

Session status has three states, because they need different answers:
`✓ connected`, `⚠ needs authentication` when the session expired and a
`munim connect` will fix it, and `✗ could not be reached` when the network
failed and reconnecting would not help. `NO_COLOR=1` turns the colour off, and
so does redirecting the output.

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
munim disconnect --all                       # every client, every provider. Lists them and asks first
munim disconnect --all --dry-run             # what it would remove, removing nothing
munim disconnect --all --yes                 # skip the question, for scripts
```

**Doing the work, by calling the provider's own tools**

```bash
munim tools "Ivy & Fern" cloudflare          # what that account can be asked to do
munim tools "Ivy & Fern" cloudflare execute  # one tool in full: description and arguments
munim call  "Ivy & Fern" cloudflare execute --args '{"code": "..."}'
munim call  "Ivy & Fern" cloudflare execute --args-file args.json
munim tools "Ivy & Fern" cloudflare execute --json | jq . | \
  munim call "Ivy & Fern" cloudflare execute --args -
```

Naming a tool prints it whole. That matters more than it sounds: Cloudflare's
`execute` carries about 1200 characters of TypeScript interfaces, and they are
the only thing telling you what to put in `--args`. The listing shows one line
per tool; the detail shows all of it.

Omit any argument and you get the picker. `munim tools` lists what the provider
itself publishes, so it is never out of date with what the provider shipped
today, and `munim call` invokes one of those tools with that client's
credentials, forwarding the arguments untouched.

No model is involved, so this works with agents off. The result goes to stdout
and everything else to stderr, so `munim call ... | jq` needs no flag. Every call
is written to the run log with the tool and its arguments; the command prints the
run id, and `munim-room` or `launch_status` reads it back.

Both are also MCP tools, `list_provider_tools` and `call_provider_tool`, so your
coding agent can do the same thing. See [TOOLS.md](TOOLS.md) and D31 in
[DECISIONS.md](DECISIONS.md) for what this changes about the isolation guarantee.

**Everything else**

```bash
munim doctor                                 # what is wrong, and nothing else
munim doctor --verbose                       # also what is connected
munim config                                 # everything: applications and agents
munim config app set gmail --client-id ...   # the secret is prompted, never an argument
munim config app list                        # what is set, and where it came from
munim config app unset gmail

munim config ai                              # agents on or off, host, model, keys
munim config ai on | off                     # off by default; Munim is local
munim config ai host gemini                  # auto | bedrock | gemini | anthropic
munim config ai model gemini gemini-2.5-pro  # per host, so switching cannot mismatch
munim config ai key gemini                   # prompts, goes to ~/.munim/credentials.json
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
and that needs a model host. `munim call` and `munim tools` do not: they forward
the provider's own tools, so changing a client's account never depends on a model
being configured. It is switched off until you ask for it, so a key
sitting in a file is not the same as deciding to use one. Everything else in
Munim is deterministic and unaffected: the thirteen checks, `audit_all_clients`,
`find_across_clients`, the mail plan and the whole passthrough all work with no
key and no model call.

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

## Installing it, and where your credentials go

```bash
uv tool install munim          # or: pipx install munim
claude mcp add --scope user munim -- "$(dirname "$(command -v munim)")/munim-mcp"
```

Credentials go in `~/.munim/credentials.json`, mode `0600`, which means readable
only by your user account. It is not encrypted. Anything running as you can read
it without asking, the same as `~/.ssh/id_rsa` or `~/.aws/credentials`, and a
backup of your home directory contains it in readable form.

That is a deliberate trade and D30 records it. The short version: macOS binds a
keychain item's access rule to a code-signing identity, and a pip-installed
Python package cannot have a stable one, because the application macOS sees is
the interpreter. The protection was real but fragile in a way it is not for a
signed application, and it broke every time the interpreter changed.

**`rm -rf ~/.munim` now removes your credentials too.** Every provider would
need connecting again. Do not sync that directory anywhere you would not put a
password.

`munim doctor` reports where the store is and refuses to guess if it cannot read
it: a client that is connected and reads as disconnected is the most confusing
state this tool can be in.
