<!--
Long is fine. The pull requests here read like short incident reports, and that
has been useful more than once. If this is a one-line fix, delete what does not
apply rather than filling it in with "n/a".
-->

## What was wrong

<!-- The behaviour, not the diff. Where possible, the output that proves it. -->

## Why it was wrong

<!--
The reasoning, which is the part this project cares about keeping. If it is one
of several faults with a shared cause, say so: three bugs here were one root
cause spelled three ways.
-->

## What would have caught it

<!--
"I added a test" and "this test fails without the fix" are different claims and
only the second is worth anything. Say which. If no test could have caught it,
say that too, and how you found it instead.
-->

## Checklist

- [ ] `uv run pytest tests/ -q` passes
- [ ] `node --test tests/room/*.test.mjs` passes, if the control room changed
- [ ] A test fails without this change, and I have said so above
- [ ] No real client name, domain, email or credential anywhere in the diff
- [ ] `docs/DECISIONS.md` has an entry, if this makes a call worth recording
- [ ] `README.md` and `docs/SUBMISSION.md` are still true, if this changed what
      the project can do
- [ ] No em dashes
