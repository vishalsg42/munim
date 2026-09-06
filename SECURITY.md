# Security

Munim holds other people's credentials. That is the whole point of it, and it is
also the reason this file says more than "email us".

## Reporting a vulnerability

Open a [private security advisory][advisory]. That reaches the maintainer
without the report being public first.

[advisory]: https://github.com/vishalsg42/munim/security/advisories/new

Please include what you did, what happened, and what you expected. A working
reproduction is worth more than a description, and a description is worth much
more than nothing: report it even if you cannot get it to fail twice.

You will get an acknowledgement within three days. If you do not, assume the
message went astray rather than that it was ignored, and open a plain issue
saying only that you are waiting on a security response, with no detail in it.

Please do not open a public issue for anything that would let somebody reach an
account they do not own.

## What is in scope

Anything that lets one client's credential reach another client's account, or
lets a credential reach anywhere it was not meant to go. Specifically:

- A tool call that touches an account other than the one it named. The isolation
  is per call now rather than structural (D31), so this is the property most
  worth attacking.
- A path, argument or provider response that causes a credential to be sent to a
  host that is not the provider's.
- A credential reaching the run log, a report, a tool result, or a coding
  agent's context. Munim goes to some trouble to keep secrets out of all four
  (D6), and any route past that is a finding.
- Anything that makes the tool authenticate as one client while reporting
  another.

## What is already known, and is not a vulnerability

These are documented decisions, not oversights. Reporting them is welcome as a
disagreement, but they will be answered with the reasoning rather than a fix.

**Credentials are stored unencrypted, at mode 0600, in
`~/.munim/credentials.json`.** Any process running as you can read that file
without a prompt. This is the same choice `gh`, `aws`, `docker`, `npm` and
Claude Code's own `~/.claude/.credentials.json` make. It is recorded in D30 with
what it costs, including that a backup or a disk image holds it in the clear.
Encrypting it with a key stored beside it would be theatre.

**Cloudflare's `execute` runs JavaScript against the account.** That is
Cloudflare's tool and Cloudflare's boundary. Munim forwards it with one client's
credential and records the call.

**A tool result reaches whichever model the coding agent runs on.** Munim is an
MCP server, so anything it returns crosses that boundary by construction. It is
stated in the privacy policy rather than defended against, because there is no
version of an MCP server where it is not true.

## Versions

Munim is pre-1.0 and fixes land on the latest release. There is no backport
branch. If you are running something older, the answer will be to upgrade.
