# The bug was in the code I published last week

My previous post argued that an agent should not be allowed to decide whether a
check passed. Facts are code's job; judgement is the model's. To make the point
I printed the check:

```python
spf = [t for t in txts if t.lower().startswith("v=spf1")]
if len(spf) == 1:
    return CheckResult("spf_single", "pass", ...)
```

That line is correct about the thing I was arguing, and it had a bug in it that
I found a week later on a live zone. It is a better argument for the post than
the post was, because of *how* it failed.

## What a TXT record looks like depends on who created it

Cloudflare's API returns a TXT record's content in whichever form the record was
created. Added through the dashboard, it comes back quoted:

```
"v=spf1 include:amazonses.com ~all"
```

Added through the API, it comes back bare:

```
v=spf1 include:amazonses.com ~all
```

Measured on a live zone on 2026-09-13. One zone carried both forms at once, and
the SPF records were the quoted ones.

A DNS resolver reports neither the quotes nor the character-string split that
quoting implies. So everything downstream of that API, which compares these
values against what a policy should be and against what a resolver says, was
comparing two different things and had no idea.

`"v=spf1 include:amazonses.com ~all"` does not start with `v=spf1`. It starts
with a quotation mark.

## What that cost

Three things went wrong, and each one is worse than the last.

**A published policy became invisible.** The check counted zero SPF records for
a domain that had one.

**The planner offered to create a second one.** This is the part worth sitting
with. The tool exists partly to detect domains with two SPF records, which is a
real and common fault: receivers ignore both, and mail that was authenticating
stops. Unable to see the policy that was there, the planner proposed publishing
another. **The tool proposed the exact fault it was built to find.**

**The guard written for that failure agreed.** `merge_spf`, whose whole job is
to leave exactly one policy behind, could not see the other one to remove. Its
read-back check then counted the result with the same blind spot and reported
success. Every layer was consistent and every layer was wrong, because they all
asked the same question the same wrong way.

## Why no test caught it

Every test I had wrote its own fixtures. I wrote `v=spf1 include:...` because
that is what an SPF record is, and the code agreed with me, and the tests
passed. The quotes only exist on the path between Cloudflare's API and my
parser, and that path had no test with a real payload in it.

This is the ordinary shape of the bug: not a hard case anybody reasoned about
wrongly, but an assumption so obvious that it never got written down as an
assumption, and so never got checked.

## The fix, and where it goes

One function, at the single point where a record enters the codebase:

```python
def unquoted(content: str) -> str:
    """A TXT value as a resolver reports it: no quotes, no split."""
    text = content.strip()
    if not text.startswith('"'):
        return content
    parts = QUOTED.findall(text)
    if not parts:
        return content
    return "".join(part.replace('\\"', '"').replace("\\\\", "\\") for part in parts)
```

Two details in a nine-line function, both of which are the point.

It handles the **split**, not just the quotes. A TXT value longer than 255
characters is stored as several quoted strings that a resolver concatenates,
which is why this collects every match and joins them rather than stripping the
first and last character. DKIM keys are long enough to hit this, so a naive
strip fixes SPF and breaks DKIM.

It is **left alone unless the value actually starts with a quote**, so a policy
that merely contains one is not mangled by a rule about how it was stored.

And it lives at the boundary rather than at each comparison. Counted just now,
seven places in this codebase ask `startswith("v=spf1")`, across the checks, the
planner, the merge and the Cloudflare adapter. Fixing seven call sites means the
eighth one, written next month by somebody who has never heard of any of this,
is wrong again. A comparison that has to remember is a comparison somebody will
write without remembering.

## What I actually take from it

The last post's claim was that code should own the facts because a model can be
talked out of one. I still think that. What this bug adds is the other half:
**code owning a fact is only worth anything if the fact is the one the outside
world is reporting.**

`startswith("v=spf1")` was deterministic, testable, and passing. It was also
answering a question about my fixtures rather than about the zone. Determinism
bought me nothing there, because all three layers were deterministic and all
three were consistently wrong. A model would not have saved me either. Reading
one real API response would have.

So the boundary is the thing to be suspicious of. Inside it, be as strict as you
like. At it, go and look at what actually arrives, on a real account, before you
write the parser that says what it means.
