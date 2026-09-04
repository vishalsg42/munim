# The agent should not decide whether the check passed

*Draft for builder.aws.com, post 3 of 3*

I built an agent that inspects a small business's domain: is email
authentication set up, will the certificate renew, does the site load. It writes
DNS records when it finds something wrong.

The interesting design question was not which model to use. It was **which half
of the work the model is allowed to touch.**

## Two halves

**Deciding whether a check passed is not model work.** Whether a domain has two
SPF records is a fact. You fetch the TXT records, count the ones starting
`v=spf1`, and if there are two then receivers ignore both. That is RFC 7208, not
an opinion. Code decides it:

```python
spf = [t for t in txts if t.lower().startswith("v=spf1")]
if len(spf) == 1:
    return CheckResult("spf_single", "pass", ...)
```

The model never sees this decision, so it cannot invent a record that is not
there, and it cannot be talked into calling a failing domain healthy. In a tool
that then *writes to production DNS*, that boundary is the difference between a
useful agent and a liability.

**Deciding what to do about it is exactly model work.** A domain with two SPF
records has a wrong answer that looks right: add a third record containing the
new provider. What it needs is the two combined into one, keeping every sender,
taking the stricter qualifier, and checking the result still fits inside SPF's
ten-lookup limit, because a merged policy that busts the limit fails too and is
not a fix.

That is judgement over evidence, and the evidence is deterministic.

## What it looks like

```
checks (code)          →  two SPF records, here they are, verbatim
agent (model)          →  these must be merged, not appended; here is why,
                          in words a florist can act on; a person must
                          approve because this is their live DNS
adapter (code)         →  read-before-write, upsert, never blind append
checks (code) again    →  one record now, and here it is
```

The model is in the middle. It cannot manufacture the input and it cannot
falsify the output.

## The failure this prevents

An earlier version would have appended. A launch that failed halfway and got
re-run would have added a second SPF record beside the first, **producing the
exact fault the tool was built to detect.** A tool that causes the bug it reports
is worse than no tool.

The fix was not a better prompt. It was making every mutation read-before-write
and upsert on `(type, name)`, and recording each one so a resumed run skips what
it already did. Tests assert it:

```python
async def test_a_differing_record_is_updated_in_place_not_appended():
    ...
    assert not create.called, "appended instead of updating"
```

## What I would tell someone starting

Write down which decisions the model is allowed to make, before you write the
prompt. My rule ended up as one line: **enumeration and checking are
deterministic; only interpretation and judgement are model work.**

It is also a good sales pitch, which I did not expect. "The agent cannot tell you
your domain is fine when it isn't, because it doesn't get a vote" is a much
stronger thing to say to someone whose production DNS you are asking to touch
than any amount of talk about accuracy.
