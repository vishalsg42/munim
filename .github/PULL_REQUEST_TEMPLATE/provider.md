<!--
The provider lane. Use this template for adding a server Munim can connect to.
For anything touching src/munim/ other than the table, use the default
template, which asks for more and means it.

Short is fine here. Three files and a measurement.
-->

## The server

<!-- Name, what it is, and who would want it connected. One or two lines. -->

## What it answered

<!--
The measurement, which is the part nobody can reproduce without your account.
What you sent, what came back, and the date. For example:

    2026-09-15  tools/list, no credentials  ->  401, www-authenticate: Bearer
    2026-09-15  connected live              ->  14 tools, 5 readOnlyHint

If you only probed it and never finished a login, say so. "Probed, not
connected" is an honest state and the index has a column for it.
-->

## Checklist

- [ ] The row is in `SERVERS` in `src/munim/remote/servers.py`, as
      `munim servers export <name>` printed it
- [ ] `docs/providers/<name>.md` exists, copied from `docs/providers/TEMPLATE.md`
- [ ] `docs/providers/README.md` links it
- [ ] The row's `note` says what was measured and when, not what the
      product claims about itself
- [ ] `uv run pytest tests/test_provider_docs.py -q` passes
- [ ] No real client name, domain, email or credential anywhere in the diff
- [ ] No em dashes

<!--
No failing test is required for this lane. The table is data, and
tests/test_provider_docs.py already checks that a row and its page arrive
together.
-->
