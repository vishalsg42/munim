# Stitch

Google's design tool. The same Google story as [Gmail](gmail.md): it needs an
application registered by hand, once, because `accounts.google.com` publishes no
registration endpoint.

- Endpoint: `https://stitch.googleapis.com/mcp`
- Registers a client on demand: **no**

## Setup

Identical to Gmail, with `stitch` in place of `gmail` everywhere. **Follow
[the Gmail page](gmail.md)**, which explains each step and why, then:

```bash
uv run python scripts/setup_google_oauth.py --provider stitch
```

The variables are `STITCH_OAUTH_CLIENT_ID` and `STITCH_OAUTH_CLIENT_SECRET`.

If you already registered an application for Gmail in the same project, you
still need the API enabled for Stitch, which the helper does. You can reuse the
same OAuth client id and secret: the consent screen is per project, not per API.

## What you are granting

Whatever Stitch's resource metadata advertises. Munim cannot narrow it.

Unlike Gmail, these are not Google restricted scopes, so the test-user
restriction may not apply the same way. That is **unverified**: nobody has
connected Stitch through Munim yet.

## Status

Registration requirements confirmed by probing. **Not yet connected live.** If
you connect it and something is surprising, that is worth an issue.

## Check it

```bash
munim clients
munim doctor
```
