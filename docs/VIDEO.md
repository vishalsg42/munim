# The video

Five minutes maximum. It is the whole evaluation surface: the organisers confirmed judges
will not install anything and may score from the video and description alone (D16). Every
criterion is read through this.

**Structure:** opens on a spam folder, closes on the same message in an inbox. That rhyme
costs nothing and is the difference between a recording and something authored.

**Required by the rules (R8):** the pitch must state (1) the problem, (2) who it is for,
(3) why it matters. All three land in the first 30 seconds and again in the last 20.

**Target 4:40, hard cap 5:00.** The previous script ran to exactly 5:00 and had no room to
cut when a beat ran long, which is the same as having no margin at all.

---

## Before you record: what has to be true

Each of these was checked on 2026-09-13. Anything not on this list is not in the script.

- [ ] `git log` on main shows `42523a7` or later, and `uv run pytest -q` passes.
- [ ] The control room is running: `munim-room`, then `http://127.0.0.1:8977` answers.
- [ ] `munim config` shows `agents on` and a model host that answers.
- [ ] The client you film is connected. `munim clients` shows which, and
      `can_reach` decides whether a repair can run at all.
- [ ] **Decide whose domain is on camera.** See "The one thing to decide" below.

---

## The one thing to decide

The repair beat needs a domain with a real fault that Munim can fix. Today there is exactly
one, and it belongs to a real client:

```
balajiroofingindustries.com
  FAIL dkim_present   Your mail is not signed, so receivers cannot prove it came from you.
  FAIL dmarc_policy   Anyone can still send mail pretending to be you.
```

`dkim_present` is repairable. `dmarc_policy` is not, and the catalogue says so rather than
pretending. But that client is connected to Cloudflare and not to Resend, so the repair
edge refuses until `munim connect "<client>" resend` is run in a browser.

**Three ways to shoot it, in order of preference:**

1. **Ask the client.** One sentence of permission and the video shows a real fault on a
   real domain being fixed. Strongest footage available and it needs no staging.
2. **Film the refusal instead.** `fix` on that client names the missing connection and
   stops. The submission checklist is blunt about this: footage of a product refusing
   honestly is usually the most convincing you have. Costs the repair beat, keeps the
   video entirely truthful, and can be shot in the next ten minutes.
3. **Use a domain you own.** `grafison.com.au` passes all sixteen checks, so it shows the
   healthy path and the honest refusal and no repair.

Do not manufacture a fault to film. A removed record you then republish is staged, it will
read as staged, and the production note below about breaking things the way they actually
break exists because of exactly this temptation.

---

## Script

### 0:00–0:12  Cold open. A spam folder.

*On screen:* a spam folder, full screen. One message: an invoice. No logo, no title card.

> "This invoice sat in a customer's spam folder for six weeks.
> The website was fine. The domain was fine. One DNS record was wrong,
> and nothing broke. That is exactly why nobody found it."

*The problem, in human terms, before any software. Eight seconds to the hook.*

### 0:12–0:30  Who this is for.

*On screen:* a terminal. `munim clients`. One row per client, with what each one is
connected to.

> "Priya looks after the websites and email for a dozen small businesses.
> A bakery, a dentist, a roofing company. She does not own those accounts.
> They do. She just keeps them working."

*Covers R8 (2) and (3). Say the number you can actually show. If the estate on screen has
four clients, say a dozen only if a dozen are on screen.*

### 0:30–0:46  The wall.

*On screen:* a provider dashboard, logged in as one client. Log out. Log in as another.

> "Every one of these providers allows one login at a time.
> So the job is: log out, log in, log out. And the work crosses accounts,
> because what one company's dashboard gives you has to be typed into another's."

*Keep it fast. Friction shown too long becomes the viewer's friction.*

### 0:46–1:04  It is one MCP server.

*On screen:* Claude Code. `claude mcp list` → `munim: ✔ Connected`. Then `munim config ai on`.

> "It is one MCP server, added once to whatever coding agent you already use.
> Each client is a container, and the agent is off until you turn it on."

*`munim config ai on` is on screen on purpose. Agents are off in a fresh install because
Munim is local by default, and a tool that needs a model should say so rather than
pretend. Show it; do not edit around it.*

### 1:04–1:24  Connect once. There is no second credential.

*On screen:* `munim connect "<client>" cloudflare`. A browser opens, the provider's own
consent screen, approve, the terminal confirms. Then `munim clients` again, showing the
provider now connected.

> "She connects the way she already logs in: their account, their consent screen,
> in a browser. There is no API key to paste, and no second credential to keep
> somewhere. The session she just made is the one the repair uses."

*This beat is new and it is the one most likely to be underrated. Until 2026-09-12 the
repair path reached both providers over their REST APIs, which refuse the token their own
MCP servers issue, so connecting a client and repairing a client needed two different
credentials for the same account. Both were true and together they undid the product's
central claim. `Container.http` now sends those requests as the provider's own MCP tool
calls (D41). Keep the shot on the consent screen: it is somebody else's account saying yes,
which is the whole argument.*

### 1:24–1:42  Read across.

*On screen:* typed in plain English, not a command:

```
which of my clients has a stale deployment?
```

The answer spans containers and names clients.

> "One question, every client at once. She has never been able to ask that,
> because the answer lives in a dozen accounts she can only open one at a time."

*Type a sentence, never a magic word: a command reads as a script and undercuts the MCP
claim. Pick a question the connected providers can actually answer. Cross-client tools are
built only from tools the provider marks read-only, and Cloudflare marks none of its three
that way, so a Cloudflare question returns nothing and says why. Vercel and Resend answer.*

### 1:42–1:56  Write within.

*On screen:* typed, *"check <domain> for <client>."* The room fills with that one client.

> "Writing is different. A change names one client,
> and only that client's credentials are loaded. The others are not dimmed for show.
> They are not in the room."

*The design moment. Hold the transition a beat; it explains read-across and write-within
with no narration.*

### 1:56–2:30  The checks.

*On screen:* the control room. The stage rail lights `verify`, then the chip grid appears
**all at once**, greyed, and lights up in place. No scrolling, no insertion.

> "Then the checks. Sixteen of them, and none are difficult.
> That is the point. Nobody runs sixteen checks by hand
> on every domain for every client, so nobody runs them at all."

*Sixteen, not thirteen: thirteen about DNS, three about hosting, plus one per connected
provider asking whether that account is still reachable. The live run on 2026-09-13 read
`16 of 16 checks passed`. Count what is on screen and say that number.*

### 2:30–2:52  The moment.

*On screen:* **a chip goes red.** Everything else recedes. The finding card owns the
screen, with the raw resolver output beneath it, the resolver named and timestamped.

> *(two seconds of silence)*
>
> "Their mail is not signed. Receivers cannot prove a message really came from them,
> so it goes where unprovable mail goes."

*The only silence in the video. Lands just past halfway: enough setup behind it, enough
runway for the payoff.*

*Two chips are red on the real domain, not one. Say so, and say that the second one is not
repairable: a DMARC policy set to monitoring is the owner's decision to change, not a
missing record. A product that names the limit of what it will touch is more convincing
than one that claims everything.*

### 2:52–3:26  Judgement, then a person.

*On screen:* `fix` runs. The rail moves `verify → diagnose → repair`. The agent returns a
**plan**, not a change: each record, with what would happen to it and what is there now.

Then the two calls, filmed as two calls:

```
apply_mail_setup(client="<client>", plan_id="<id>")
  -> refused: this changes records somebody already published. Re-run with approved=true.

apply_mail_setup(client="<client>", plan_id="<id>", approved=true)
```

> "It works out what the record should be, and then it stops.
> Applying it is a second instruction, because this is someone else's live DNS."

*Film the refusal. It is the product declining to act, on screen, rather than a claim that
it would. An earlier version of this script showed a confirmation dialog the product could
not produce, which is the kind of thing found by whoever watches most carefully.*

*The control room's Approve button is real and works, and it appears only when a change
would **replace** a record somebody already published. Creating a record that is absent is
not a judgement call and does not stop, by design. If the fault you film is a missing
record, the two calls above are the approval beat and the button is not in this video. Do
not cut to a button that this run did not raise.*

### 3:26–3:46  Proof.

*On screen:* the chip turns green on the recheck. Then the record itself, queried from
outside the product:

```
dig +short TXT resend._domainkey.<domain> @1.1.1.1
```

> "Not asserted. Published. That is the record, read back from a public resolver,
> not from anything I wrote."

*Say the constraint out loud here, and say whichever of these is true:*

> "This is a real client's domain, filmed with their permission."

*or*

> "This is a domain I own. No client's real account is in this video."

*Eight seconds, and it turns the biggest credibility liability into a credibility signal.
Do not claim the first one unless it happened.*

### 3:46–4:04  What the client gets.

*On screen:* the report page, opened from the link in the control room's header.

> "And this is what Priya sends her client. Not a log.
> 'Here is what we checked, here is the one thing that was wrong,
> and here is what we did about it.'"

*This is where "a complete product experience" is earned rather than claimed. The report
has been written to disk since the first week and nothing linked to it until 2026-09-12;
the link in the header is new and it is what makes this shot a click rather than a file
path.*

### 4:04–4:22  It says no.

*On screen:* `fix` on a healthy domain. The rail lights `verify`, the repair cell renders
dashed with its reason, and the run finishes.

```
16 of 16 checks passed
Not repairing <domain>: nothing is failing, so there is nothing to repair
```

> "And when there is nothing wrong, it says so and stops.
> The checks are code, not a model, so it cannot be talked into
> calling a failing domain healthy, or a healthy one broken."

*The deterministic boundary, shown rather than asserted, and the most convincing
twenty seconds in the video. The refusal is an edge condition reading the check results:
the model is not consulted and cannot traverse it.*

### 4:22–4:34  How it works.

*On screen:* the architecture diagram from `ARCHITECTURE.md`, held still. No motion.

> "One server. One container per client. The checks are deterministic.
> What the model does is work out why, and say it to someone who is not technical."

### 4:34–4:44  Close.

*On screen:* the same invoice, now in the **inbox**. Name and repo URL small beneath.

> "Six weeks in spam, or in the inbox. One record."

---

## What was cut, and why

Kept here because the next person to edit this will otherwise put them back.

**The launch sequence (was 1:28 to 2:20, 52 seconds).** It showed a stage rail of
`deploy → domain → dns` and Vercel handing records to Cloudflare. **No code emits `deploy`
or `domain`**, across every run ever recorded, and the room stopped drawing those cells on
2026-09-12 because two permanently grey cells read as steps that hung. There is no launch
flow in the exposed product: `work_on_client` exists, has never run, and is not something
to film for the first time on camera.

**The SPF merge as the climax.** It needed a domain carrying two sender policies. No client
is in that state, `RESULTS.md` scores that fixture unreliable at 1 in 3, and manufacturing
one is staging. The merge code is real, tested and reachable; it is a thing to write about
in the Devpost description, not to fake in the video.

**"Eleven client cards" at rest.** The control room has never had client cards. It follows
one run, and at rest it says "Nothing running". `munim clients` in a terminal is the shot
that actually exists.

**"Thirteen checks".** It is sixteen.

---

## Production notes

**Break it the way it actually breaks.** Not a typo'd DKIM value. Nobody makes that
mistake, so it reads staged. A domain that was never set up for signing in the first place
is the fault a competent person actually leaves behind.

**Keep real latency, make waiting legible.** Sixteen checks resolving in 400ms reads as
hardcoded. A check that sits at "querying 1.1.1.1" for two seconds, with the resolver
named, reads as real. Do not normalise stage durations. A repair over MCP sessions is
slower than over a REST key, because each call opens a session; that is honest and it is
also why the checks should be on screen while it happens.

**Label every cut.** An on-screen "four minutes later" card with the UI clock jumping to
match reads as honest editing. A concealed cut, if spotted, reads as fabrication.

**Never split-screen.** Both halves become illegible after compression. Full-screen one
thing and cut between them.

**Keep credentials out of frame.** The consent screen at 1:04 is the highest-risk shot in
the video: plan the crop before you open the browser, and never show a token, an account
id or a URL carrying either.

**Before recording:** full-screen the app with no browser chrome, real favicon and title,
do-not-disturb on, cursor hidden except when clicking.

**Record voice separately** and mix under. Room-mic narration over live capture makes
everything sound like a screen recording rather than a product.

## Devpost gallery stills (R18)

Composed from the same frames, so they cost nothing extra:

1. `munim clients`: the estate, and what each client is connected to
2. The provider's own consent screen, mid-connect
3. The chip grid with the red finding card open
4. `apply_mail_setup` refusing without `approved=true`
5. The report page a client would receive
