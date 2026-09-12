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

---

# The first time the repair graph ran

Run on **2026-09-07**, against a real client's live domain, through the MCP
tool rather than a script. The client's name and domain are replaced here with
the usual placeholders: they did not consent to a public repository, and this
file is public.

Every line below is the run log the framework wrote, not a transcript anybody
composed.

```
 1  diagnose  observation   0 provider tools available for Acme Ltd
 2  verify    stage_start   Checking acme.example
 3  verify    observation   Your outgoing mail is correctly claimed by one sender policy   spf_single
 4  verify    observation   Your sender policy is within the limits mail servers enforce   spf_lookups
 5  verify    finding       Your mail is not signed, so receivers cannot prove it really   dkim_present
                            came from you.
 6  verify    observation   You have told other mail servers what to do with messages      dmarc_present
 7  verify    finding       Anyone can still send mail pretending to be you: the policy    dmarc_policy
                            is set to watch, not to act.
 8  verify    observation   Mail sent to your address can be delivered.                    mx_present
 9  verify    observation   This domain is under your control.                             ns_delegated
10  verify    observation   Typing your address into a browser reaches your site.          apex_resolves
11  verify    observation   Nothing is blocking your security certificate                  caa_allows
12  verify    observation   Your address works with or without www.                        www_redirect
13  verify    observation   Visitors always arrive on the secure version of your site.     https_enforced
14  verify    observation   Your site is secure and the certificate is not close to        cert_valid
                            expiring.
15  verify    observation   Your cloudflare connection is working.                         account_cloudflare
16  verify    observation   Your supabase connection is working.                           account_supabase
17  verify    observation   Your vercel connection is working.                             account_vercel
18  verify    stage_done    13 of 15 checks passed
19  repair    observation   Not repairing acme.example: Acme Ltd has no API key for
                            cloudflare and resend. A browser session is not the same
                            credential: the repair calls their REST API.
20  diagnose  stage_start   Working out what is wrong with acme.example        node=triage
21  diagnose  stage_done    <the agent's answer>                               node=triage
22  repair    run_done      Finished with acme.example.
```

## What this is evidence of

**The check catalogue is not DNS-only any more.** Lines 15 to 17 are the family
that asks each connected provider whether that account still works, and it is
why the run says fifteen checks rather than thirteen. Until this run those had
never executed anywhere outside a test, and neither had the three Vercel
hosting checks that were written, tested and called by nothing (D37).

**The run log is written by the framework.** Lines 20 and 21 carry `node=triage`
and were produced by a Strands `AfterNodeCallEvent`, not by a hand-placed
`log.append`. The control room's rail is a rendering of that rather than a
parallel narration of it.

**The write boundary held, and said so.** Line 19 is the interesting one. Two
checks failed and one of them, `dkim_present`, is in the set the repair path can
produce a record for, so the only thing that stopped the repair was the
credential. The edge condition read that, refused, and wrote down why.

That last part matters more than a refusal usually would. An edge that does not
traverse is silent, and in the room's rail a silent step is indistinguishable
from one that hung. This is the same failure the ghost stage cells were, one
layer up, and it is the reason a skipped repair is required to produce a
sentence.

## What this is not evidence of

**Nobody has approved anything yet.** `~/.munim/decisions` is empty, the
control room's button has never been clicked in anger, and the `repair` node has
never been entered. The gate, the interrupt, the resume and the approval file
are covered by tests and by the day-one gate script against a real model, and
that is a weaker claim than this page otherwise makes.

The reason was the one in line 19, and it was a real seam rather than a missing
credential. `mailplan` reaches Cloudflare and Resend through their REST APIs,
and a browser session is a different credential from an API key: measured, an
MCP session token sent at the matching REST API answers 403 for Resend and 400
for Cloudflare. Only Vercel accepts its own (D33). So a client connected the
normal way, in a browser, could not be repaired until somebody also pasted a key.

Everything that goes through a provider's *own* MCP server writes happily on the
browser session alone, including Cloudflare's `execute`. The split was never
read against write. It is which server is being talked to, and from an
operator's point of view that is arbitrary.

**That seam is closed** (D41). `Container.http` now hands the adapters a client
whose requests leave as the provider's own MCP tool calls where there is a
session and no key, so the repair runs on the connection the operator already
made.

## Proof, 2026-09-12: a mail plan built with no API key anywhere

A client connected in a browser to Cloudflare and Resend, with an empty
pasted-key store, against their live accounts:

```
cloudflare  key=False  route=True
resend      key=False  route=True

unchanged DKIM  TXT   resend._domainkey.<domain>
unchanged SPF   MX    send.<domain>
create    SPF   TXT   send.<domain>
          next: v=spf1 include:amazonses.com ~all
```

Two of the three read `unchanged`, and that is the part worth keeping. Resend's
MCP server answers in prose, so the DKIM public key was parsed out of a
formatted block and compared against what is actually published in the zone.
`unchanged` means a 216 character base64 key survived that round trip byte for
byte. A parser that truncated or re-wrapped anything would have said `update`
and proposed publishing a key nobody holds.

The third is a genuine finding: the sender policy for the sending subdomain is
not published, and the plan is to create it.

The repair edge opens for that client now and refuses for a client connected to
Cloudflare and not Resend, naming the provider that is missing rather than
asking for a key.
