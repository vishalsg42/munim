# Privacy

Munim runs on your own machine. There is no Munim server, no account, and no
telemetry.

**What is stored, and where**

| What | Where | Leaves your machine? |
|---|---|---|
| Provider credentials | Your OS keychain | Only to the provider they authenticate |
| Client names and domains | `~/.munim/registry.json` | No |
| Run logs | `~/.munim/runs/*.jsonl` | No |
| Launch reports | `~/.munim/reports/*.html` | No |

**What is sent, and to whom**

- **Provider APIs** — Cloudflare, Vercel and Resend receive the requests you ask
  Munim to make, authenticated with the credential you connected.
- **Public DNS resolvers** — checks query `1.1.1.1` and the domain's authoritative
  nameservers. These are public lookups about public records.
- **Your chosen model host** — Amazon Bedrock, Gemini, Anthropic or another
  Strands-supported provider receives the *findings* it is asked to explain: the
  domain, which checks failed, and the DNS evidence. **No credential is ever sent
  to a model.** Provider tokens are injected at the point of the API call and are
  never part of any prompt.

**What is never collected**

No usage analytics, no error reporting, no crash dumps, and nothing sent to the
author of this software.

**Deleting everything**

`rm -rf ~/.munim` removes all local state. Credentials are removed from the
keychain with your operating system's keychain tool.
