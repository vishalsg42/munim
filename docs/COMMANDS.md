# Commands

The whole CLI. `munim doctor` says what is wrong at any point, and the
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
munim disconnect --all                       # every client, every provider. Lists them and asks first
munim disconnect --all --dry-run             # what it would remove, removing nothing
munim disconnect --all --yes                 # skip the question, for scripts
```

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

## Installing it, and why macOS may ask for your keychain password

Install it once, and use that one install for both the CLI and the MCP server.
That sentence is the whole of the advice, and the rest of this section is why it
matters more than it sounds.

```bash
uv tool install munim          # or: pipx install munim
claude mcp add munim "$(dirname "$(command -v munim)")/munim-mcp"
```

**A fresh install asks for nothing.** macOS files an access rule against each
keychain item naming the binary that may read it, and the binary that *stores* a
credential is on that rule automatically. So the interpreter that ran `munim
connect` reads the result back with no prompt, on that connection and on every
one after it. Verified rather than assumed: writing an item and reading it back
in the same interpreter returns the value with no dialog.

**Two installs is what causes the prompts.** The keychain sees two different
binaries, not two copies of munim. Each asks approval for every item the other
created, neither ever inherits the other's, and no amount of clicking converges,
because both keep writing new items the other has not been approved for. This is
easy to arrive at by accident: install munim into a project venv, install it
again with pipx for convenience, and now the MCP server your coding agent spawns
and the `munim` on your PATH are different Pythons.

`munim doctor` reports this directly:

```
! One interpreter    the MCP server and this command are different Pythons,
                     so the keychain will keep asking for your password
```

**What else re-prompts, once you are on one install.** Only the interpreter
changing underneath you. A pipx or uv venv symlinks to a real Python rather than
copying it, so uninstalling and reinstalling munim keeps the same identity and
costs nothing. Upgrading the Python it points at is a different binary, and so is
moving between 3.12 and 3.13, and both mean approving again.

**If you do get asked, "Always Allow" is the right button.** It adds that
interpreter to the item's rule permanently. Be aware of what it grants: any
Python script run by that same interpreter can then read those credentials
without a prompt. That is the trade the keychain offers and there is no version
of it that is both silent and narrow.

The measurement behind all of this, and what to do if prompts ever return, is
`docs/DECISIONS.md` D29.

**Linux and Windows do not have this.** Secret Service and Windows Credential
Manager have no per-item, per-binary rule, so none of the above applies and
`doctor` stays quiet about it there.


## Conventions

```bash
munim                    # what this is, and where to start
munim --version          # or -V
munim clients --json     # the listing, machine-readable, on stdout
```

**Exit codes.** `0` succeeded, including a dry run and a refusal you asked for.
`2` for anything else: a usage error, an unknown client, a confirmation you
declined, or a destructive command refusing because there was no terminal to
confirm on. Data goes to stdout, everything else to stderr, so
`munim clients --json | jq` works and nothing else has to be filtered out.

**Destructive commands list what they will do before doing it.**
`munim disconnect --all` prints every credential it is about to remove, then
asks. `--dry-run` prints that same list and stops, which is the only way to see
it from a script, since without a terminal the command refuses rather than
guessing. The list it prints and the list it acts on are one list, so they
cannot disagree.
