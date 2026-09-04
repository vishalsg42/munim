# The demo estate

A fictional business used to exercise Munim end to end against real DNS and real
mail delivery, so the demonstration runs on records that genuinely resolve rather
than on fixtures.

**Ivy & Fern Studio** is a flower studio. It has a site, a domain, and a mail
setup that is deliberately broken in the way this happens in practice: a leftover
SPF record from a previous mail provider, with a second one added alongside when
the new provider was set up. Two policies, both ignored, and mail that
authenticates as neither.

That fault is not a typo. Nobody mistypes a DKIM value; people do add a second
SPF record without realising the first one is still there. The realistic break is
the one worth demonstrating, and the fix requires judgement rather than
string-pasting.

**Real client accounts are never used here.** The clients whose infrastructure
this project was built against have not consented to appear in a public
repository or video, so the demonstration runs on a tenant owned outright by the
author (docs/DECISIONS.md D12).
