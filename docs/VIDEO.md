# The video

Five minutes maximum. It is the whole evaluation surface: the organisers confirmed judges
will not install anything and may score from the video and description alone (D16). Every
criterion is read through this.

**Structure:** opens on a spam folder, closes on the same message in an inbox. That rhyme
costs nothing and is the difference between a recording and something authored.

**Required by the rules (R8):** the pitch must state (1) the problem, (2) who it is for,
(3) why it matters. All three land in the first 30 seconds and again in the last 20.

---

## Script

### 0:00–0:14  Cold open. A spam folder.

*On screen:* Gmail spam folder, full screen. One message: **Invoice #1042, Ivy & Fern
Studio.** No logo, no title card.

> "This invoice sat in a customer's spam folder for six weeks.
> The website was fine. The domain was fine. One DNS record was wrong.
> and nothing broke. That is exactly why nobody found it."

*Why first:* the problem, stated in human terms, before any software. Eight seconds to the
hook.

### 0:14–0:34  Who this is for.

*On screen:* the control room at rest. Eleven client cards, different providers connected,
different ages.

> "Priya looks after the websites and email for eleven small businesses.
> A bakery, a dentist, a yoga studio. She does not own those accounts.
> they do. She just keeps them working."

*Covers R8 (2) and (3): who it is for, and why it matters: eleven businesses whose mail
either arrives or does not.*

### 0:34–0:52  The wall.

*On screen:* Vercel, logged in as one client. Log out. Log in as another. Cut back.

> "Every one of these providers allows one login at a time.
> So the job is: log out, log in, log out. And the work itself crosses accounts.
> what one company's dashboard gives you has to be typed into another's."

*Keep this fast. Friction shown too long becomes the viewer's friction.*

### 0:52–1:12  It is one MCP server.

*On screen:* Claude Code. `claude mcp list` → `munim: ✔ Connected`. Then typed in plain
English, not a command:

```
which of my clients has a domain expiring this quarter?
```

Answers span containers.

> "It is one MCP server, added once to whatever coding agent you already use.
> Each client is a container. You can read across all of them at once,
> which is a question she has never been able to ask before."

*Type a sentence, never a magic word: a command reads as a script and undercuts the MCP claim.*

### 1:12–1:28  Write within.

*On screen:* typed, *"check ivyandfern.co.uk for Ivy & Fern Studio."* That card expands to
fill the screen; the other ten dim and show a lock.

> "Writing is different. A change names one client,
> and only that client's credentials are loaded. The others are not dimmed for show.
> they are not in the room."

*The design moment. Hold the transition a beat; it explains read-across/write-within with
no narration.*

### 1:28–2:20  The launch.

*On screen:* stage rail: deploy → domain → dns. Real values crossing from one provider into
another. One **labelled** time-cut for propagation, with the on-screen clock jumping to match.

> "Deploy the site. Point the domain. Vercel hands back records
> that have to be written into Cloudflare: a different company, a different login.
> That handoff is the job."

### 2:20–2:56  The checks.

*On screen:* Resend emits DKIM and SPF. The chip grid appears **all at once**, greyed, then
lights up in place. No scrolling, no insertion.

> "Then the checks. None of them are difficult.
> That is the point. Nobody runs thirteen checks by hand
> on every launch for every client. So nobody runs them at all."

### 2:56–3:18  The moment.

*On screen:* **one chip goes red.** Everything else recedes. A card owns the screen. Raw
resolver output beneath it, with the resolver named and timestamped.

> *(two seconds of silence)*
>
> "There was already an SPF record on this domain, from the mail provider
> they used before. Adding a second one does not merge them.
> Both are ignored, and mail from Ivy & Fern authenticates as neither."

*Lands at 60%: enough setup behind it, enough runway for the payoff. The only silence in
the video.*

### 3:18–3:48  Judgement, then a person.

*On screen:* the agent **merges** the two records rather than adding a third. Then pauses:
confirmation, **"Ivy & Fern Studio"** named on it. One click.

> "It does not add a record. It merges them.
> Then it stops and asks, because this is someone else's live DNS."

*This is the Strands beat, placed at peak attention. Approval appears as a consequence, never
as the headline.*

### 3:48–4:16  Proof.

*On screen:* the chip goes green. Then a **real received email**, headers open, full screen:
`spf=pass dkim=pass dmarc=pass`.

> "Not asserted. Sent. This is the message, and those are its headers."

*Say the constraint out loud here:*

> "This is a demo estate I own. My clients' real accounts are not in this video.
> The domain is on screen if you want to check the record yourself."

*Eight seconds, and it turns the biggest credibility liability into a credibility signal.*

### 4:16–4:42  What the client gets.

*On screen:* the site loading on the real domain, padlock visible. Then the **launch report**.

> "And this is what Priya sends her client. Not a log.
> 'Your site is live. Your email will reach inboxes.
> Here is what we checked, and the one thing we fixed.'"

*This is where "a complete product experience" is actually earned, and where the theme is
answered rather than claimed.*

### 4:42–4:52  How it works.

*On screen:* the architecture diagram, held still. No motion.

> "One server. One container per client.
> The checks are deterministic, so the model cannot argue a failing check into passing.
> What it does is work out why, and say it to someone who is not technical."

### 4:52–5:00  Close.

*On screen:* the same invoice, now in the **inbox**. Name and repo URL small beneath.

> "Six weeks in spam, or in the inbox. One record."

---

## Production notes

**Break it the way it actually breaks.** Not a typo'd DKIM value. Nobody makes that
mistake, so it reads staged. A leftover Google Workspace SPF record with Resend's added
alongside is a mistake a competent person makes, and the fix requires judgement.

**Exactly one red chip.** Zero looks scripted. Two looks broken.

**Keep real latency, make waiting legible.** Twenty checks resolving in 400ms reads as
hardcoded. A check that sits at "querying 1.1.1.1…" for two seconds, with the resolver
named, reads as real. Do not normalise stage durations.

**Label every cut.** DNS propagation is 30s–5min against a 300-second budget. An on-screen
"4 minutes later" card with the UI clock jumping to match reads as honest editing. A
concealed cut, if spotted, reads as fabrication.

**Never split-screen.** Both halves become illegible after compression. Full-screen one
thing and cut between them.

**Before recording:** full-screen the app with no browser chrome, real favicon and title,
do-not-disturb on, cursor hidden except when clicking, `localhost:8977` never in frame.

**Record voice separately** and mix under. Room-mic narration over live capture makes
everything sound like a screen recording rather than a product.

## Devpost gallery stills (R18)

Composed from the same frames, so they cost nothing extra:

1. The estate at rest, eleven clients
2. A launch mid-flight, check grid lighting up
3. The SPF finding card with resolver output
4. Passing email headers
5. The launch report
