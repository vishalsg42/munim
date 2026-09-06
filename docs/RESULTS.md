# What the agent actually said

Run on **2026-09-06**, Gemini 2.5 Flash through Strands, four fixtures, three
samples each. Reproduce with `munim config ai on && munim evals`.

**Read this as drift-detection, not as evidence.** The findings this project
shows are live ones: real domains, named resolvers, timestamps. Nothing here is
a fixture, and `DECISIONS.md` records that fixtures would not have found the
bugs real client infrastructure found in an afternoon. What this table is for is
the opposite direction: if a prompt or a model changes and the advice quietly
gets worse, this is what notices.

```
~ two_spf              unreliable  1/3
                       did not say any of: combine, merge, into one, single record, one record
                       did not say any of: combine, merge, into one, single record, one record
                       Your domain has two SPF records, which are like instructions to email providers about who can send email for you; having two means email providers wil
                       Your domain has two SPF records, which tells email servers conflicting information about who is allowed to send email on your behalf.
                       Your domain has two SPF records, which confuses email systems and causes them to ignore both.
✓ dmarc_monitor_only   pass  3/3
                       Your domain's DMAR C record, which helps protect against email fraud, is currently set to a monitoring-only policy (`p=none`).
                       Your DMARC record isn't fully protecting your domain, so email providers are not being told to block or quarantine suspicious emails pretending to be 
                       Your email sending policy, called DMARC, is set to "monitor only", which means that if someone sends an email pretending to be from The Bakery, email 
~ dkim_missing         unreliable  1/3
                       did not say any of: resend, provider, dashboard
                       did not say any of: resend, provider, dashboard
                       Your emails might not be reaching customers' inboxes because they lack a digital signature (called DKIM) that proves they are genuinely from The Baker
                       Your outgoing emails lack a digital signature called DKIM, which helps verify that they are genuinely from The Bakery and haven't been tam pered with.
                       Your domain is missing a special record called a DKIM record, which helps email providers like Gmail know your emails are real and not spam.
~ two_spf_and_no_dkim  unreliable  2/3
                       did not say any of: combine, merge, into one, single record, one record
                       Whether the two are ordered sensibly is a judgement no predicate here can make. Read the sentences.
                       The Bakery has two SPF records, which confuses email servers and causes them to ignore both.
                       You have two SPF (Sender Policy Framework) records, but you should only have one; this means email servers will ignore both, making your emails look l
                       You have two SPF records, but email servers only look at one; because you have two, they will ignore both.

1 of 4 fixtures answered the same way every time, over 3 samples each.
Not settled: two_spf, dkim_missing, two_spf_and_no_dkim. The advice changed between runs of the same model, which is a finding about the agent rather than noise.
Advisory. These pin drift, not correctness: read the sentences.
```

## What it says, plainly

**One fixture in four is settled.** DMARC is answered the same way every time.
The other three are not, and that is the useful part of this table.

**The agent names the fault reliably and prescribes the repair unreliably.**
Every sample of `two_spf` correctly says the domain has two sender policies and
that receivers ignore both. Only one of three goes on to say what to do about
it, and combining them is the whole point: deleting either one silently loses
that sender's mail. The system prompt asks for a decision about the fix, and the
model supplies it about a third of the time.

Same shape for `dkim_missing`. Every sample explains what DKIM is and why its
absence matters. One of three says where the value comes from, which is the only
actionable part, because there is no correct record to invent.

**This was found by running it three times.** The first two single-sample runs
of this file disagreed with each other on every fixture, minutes apart, same
model. A table built on one sample would have reported whichever run happened
last and called it a result, so the sample count is not a detail.

## What the rubric cannot tell you

Each fixture scores the **action**: the right operation on the right target,
existing values preserved, and an abstention where the evidence does not support
acting. That is stronger than checking for the fault's name, which is defeated
by paraphrase, and it is still not a judgement. An answer telling the operator
to "keep the record that lists your current provider and let the other one
lapse" names the fault, avoids every forbidden word, invents no value, and would
cost a client their mail. It is a test case in `tests/test_evals.py` for exactly
that reason.

So the model's own first sentence is printed beside every verdict. The reader is
the judge; the table is a way of noticing that something moved.
