Notes from another Claude Code session that used munim for real work.
Client names and domains are redacted: they did not consent to a public
repository. What the findings became is recorded in the commits that
reference this file.

The more useful thing is the specific friction. Each of these has evidence from this session.

1. A raw REST passthrough for every provider. This is the big one. Cloudflare's MCP has execute, so I could do anything the API allows — rotate DKIM, delete a record, query zones. Vercel's MCP is a curated 37-tool surface, and the moment I needed env vars, project settings or domain attachment, there was nothing and no fallback. munim already holds the credential; a generic raw_request(client, provider, method, path, body) would have made all three of those one call each instead of a blocker. Right now the ceiling on what munim can do for a provider is set by whoever wrote that provider's MCP server.

2. Never swallow the provider's error. list_projects returned {"error": "Failed to list projects."} — identical for a real team id, a slug, and a deliberately bogus id. create_git_project on the same broken grant returned the actual Vercel 403, naming the scope, the real teamId, and the fix ("You must re-authenticate to this scope"). Same credential, same underlying problem, one tool told me everything and the other told me nothing. I stopped and asked you a question I'd have answered myself in ten seconds with the raw error.

3. connected: true was a false positive. list_clients and client_status both reported vercel connected, and it was — the session opened fine. It just had access to zero scopes, so every real call 403'd. The docstring makes a point of connected meaning "the session opens right now, not that a credential is filed," which is exactly the right instinct applied one level too shallow. Probing a scoped read instead of a bare handshake would catch this, and a state like connected, no accessible scope would say precisely what's wrong.

4. plan_mail_setup and call_provider_tool disagree about credentials. plan_mail_setup <client> <their domain> failed with no resend credential for that client, while client_status said resend was connected and call_provider_tool <client> resend list-domains worked in the same minute. Two different credential lookups against one client. That looks like a bug, and it pushed me off the purpose-built path onto manual tool calls — which then meant I didn't get the create/update/merge diff that plan_mail_setup exists to give.

5. munim connect killed the MCP server mid-session. All fourteen mcp__munim__* tools vanished when you re-authenticated and didn't come back. The CLI saved it, but only because I thought to check which munim. Either the connect flow shouldn't restart the server, or it should reconnect afterwards.

6. list_provider_tools is unusable at full size. Vercel returned 76KB, Resend 165KB — the second exceeded the limit outright and had to be written to a file and parsed. A names_only mode, or a filter substring, would fix it. I needed "which tools take a teamId" and had to write Python to find out.

7. Put the run id on stderr. munim call prints Recorded as 20260906-155006-bcd96a. on stdout before the JSON, so every pipe into jq or python3 -c needs the first line stripped.