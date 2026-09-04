# Agents for Humans, contest analysis

Written 2026-09-03, before any concept is chosen. Facts verified against the Devpost
page and rules, the judge list, and a ~100-repo GitHub scan of the live field.
Read this before proposing a concept; the crowded lanes are already mapped.

---

## 1. The contest, as stated

| | |
|---|---|
| Sponsor | AWS. Every judge is an AWS employee. |
| Submission deadline | **2026-09-14, 17:00 PDT.** 11 days from today |
| Judging ends | **2026-10-08.** The project must stay live, free and unrestricted until then. |
| Winners | 2026-10-14, 14:00 PT |
| Prize pool | $40,000. 1 Grand $10k; each of 3 tracks Gold $5k / Silver $3k / Bronze $2k. **10 payouts.** |
| Registrants | 7,256 (registration ≠ submission; Devpost conversion is typically 5–12%) |
| Mandatory | Strands Agents SDK |
| Recommended | Amazon Bedrock AgentCore deployment, explicitly named as strengthening the Technical score |
| Licence | MIT or Apache, public repo |
| Video | **≤ 5 minutes** (note: 5, not 3, longer than the WebMCP limit) |

### Scoring

Stage One is pass/fail: does it fit the theme, does it actually use Strands.

Stage Two is **five equally weighted criteria, 20% each**:

1. **Technological Implementation.** "How thoroughly and skillfully does the project use
   Strands Agents? Does the code reflect genuine effort and working implementation?"
2. **Design.** "a complete, coherent product experience and not just a technical proof of concept"
3. **Potential Impact.** "a credible case for solving a real problem for a real audience"
4. **Creativity & Originality.** "a creative, non-obvious use of Strands Agents"
5. **Presentation.** "Does the video clearly demonstrate the project working end-to-end?"

**Bonus: up to 0.6 points for builder.aws.com posts, 0.2 each, maximum 3.** On a 5-criterion
scale this is roughly a 12% swing on one criterion's worth of points, for three blog posts.
It is the cheapest available margin in the entire contest and most entrants will write zero.

### Rules that bind

- **"Projects must be newly created during the Submission Period."** The window opened
  ~2026-08-03. This repo was created 2026-09-03, so it qualifies. Any code lifted from
  `web-mcp-2026` or `google-agentic-cinema` must be **disclosed** as pre-existing work.
- **AI coding assistants are explicitly permitted**, subject to disclosure. This is the
  opposite of Agentic Cinema's Rule 7.B (see that project's D14). Claude Code is allowed here.
  Disclose it and move on.
- The project must remain available **free of charge and without restriction** to judges
  through 2026-10-08. That is 24 days of uptime after submission, with judges invoking it.
- $50 AWS credits available on request. **Request them on day one.**

---

## 2. The judges

Twelve people, all AWS:

| Name | Role |
|---|---|
| Debjyoti Paul | Applied Scientist II, Spectrum |
| Elizabeth Fuentes Leone | Developer Advocate, SDE, GenAI |
| Gonzalo Ron | Principal Partner Solution Architect |
| Ian Holtz | Sr. GTM Specialist, Agentic Coding |
| Ifeanyi Otuonye | Technical Content Creator |
| Lahari Chowtoori | Open Source TPM, AI/ML |
| Rekha Chauhan | Sr. Technical Program Manager |
| Rohan Patil | Sr. Applied Scientist |
| Rohini Gaonkar | Sr. Developer Advocate |
| Sandhya Subramani | Sr. Dev Advocate, GenAI |
| Saurabh Garg | Sr. SDE |
| Sunil Divvela | Sr. WW Spec Solution Architect, Mainframe |

**What this changes versus the WebMCP field.** Those judges were browser and infrastructure
platform people from seven different companies; the working assumption there was that they
read repos and that domain charm earned nothing. This panel is different:

- **Heavy on Developer Advocates, Solution Architects and Content Creators.** Their job is
  finding and retelling builder stories. A project that is *easy to retell* has a structural
  tailwind that has nothing to do with code quality.
- **All from one company, whose product is on trial.** Demonstrating breadth of the AWS agent
  stack is scored, not neutral. AgentCore use is named in the criteria.
- **Volume.** If 400–900 projects arrive, no judge reads 900 repos. **The video and the Devpost
  description carry the score; the repo is a spot check.** Presentation is a full 20% by itself,
  and Design, "complete product, not a proof of concept", is judged largely off the video too.
  That is **40% of the total decided by what the screen recording looks like.**

Both previous projects front-loaded engineering rigour and treated the video as the last task.
Here, 40% of the score says do the opposite.

---

## 3. The field, measured

~100 repositories created since 2026-08-01 referencing Strands or this hackathon were scanned
on 2026-09-03. The field is not empty and it is not random. It clusters hard.

### Crowded lanes, by observed repo count

| Lane | Seen | Examples |
|---|---|---|
| DevOps / CI / incident / cost "sentinel" | 12+ | `opsguardian`, `assureops-sentinel`, `qa-sentinel`, `night-shift`, `strands-guardian` ×2, `recovery-agent` ×2, `aetherops-agent`, `costpilot`, `dependency-sentinel`, `changeset`, `SentinelMonitorIA` |
| **"Evidence-first / only acts on what it can prove / refuses to guess"** | **13+** | `byggeklar-agent`, `smishsentinel`, `proofpitch`, `caseworker`, `dependency-sentinel`, `assureops-sentinel`, `costpilot`, `agent-that-refuses-to-guess`, `recourse`, `ves-field-agent`, `strands-mca-agent`, `cogram-strands-afh`, `ezriva` |
| **Human-approval / bounded autonomy / "capability is not authority"** | **11+** | `DoormanSDK`, `gatekeeper`, `quietrelay`, `neighborly-queue`, `erh-guardian-agent`, `quorum-wip`, `gapbridge`, `handoff`, `so101-tic-tac-toe`, `ves-field-agent` |
| Food bank / mutual aid / neighbourhood coordination | 10+ | `pantrypilot`, `pantrywatch`, `food-rescue-router`, `neighborflow`, `neighborly-queue`, `barnraise`, `skwrl-agent`, `NeighborOps`, `baton`, `kpalastro` |
| **"Quiet / only wakes you when it matters / attention-aware"** | **8+** | `QuietDesk`, `only-when-it-matters`, `quorum-agent`, `Porchlight`, `SUBSENTRY`, `guardrail`, `decision-desk`, `quietrelay` |
| Elder care / family / health reminders | 6+ | `carepilot`, `guardrail` (elder fraud), `tenderloop`, `sonae`, `household-chief-of-staff`, `rxtrack-agent` |
| Invoice / AP / billing / reconciliation | 6+ | `clearline`, `payable-pilot`, `invoice-ai-assistant`, `invoicehound`, `ReconcileAI`, `Ratchet` |
| Subscription & bill watchdog | 4+ | `gatekeeper`, `sub-sentry`, `SUBSENTRY`, `duedatepulse` |
| Meetings / notes / scheduling | 4+ | `meetung-scheduler`, `meeting-minutes-agent`, `QuietDesk`, `TeAIm` |

### The finding that matters most

**The three most crowded framings in this hackathon are the three signature moves of the
previous two projects.** Evidence provenance, the approval boundary, and the refusal that has
to be reachable are D9, D12 and D25 of Agentic Cinema and the load-bearing claims of Passbook.
Here they are the house style of thirty-plus competitors.

Read the competitor descriptions and the reason is obvious: they are written in the same voice,
with the same vocabulary, "evidence-first", "bounded autonomy", "human-approved",
"deterministic … escalating to a human only when". This is a field of LLM-assisted submissions
converging on the same rhetoric. Passbook's own conclusion applies verbatim: *"Approval-gating
and revocation are the most crowded framings in this ecosystem; leading with either caps the
submission at mid-field."*

**So: build the rigour, never lead with it.** Evidence discipline stays. It is why the previous
projects survived adversarial review, but it goes in the README and the architecture section,
not the tagline, not the video's first thirty seconds, not the Devpost headline.

### Genuine whitespace

- **Voice and telephony as the interface.** Near-absent. Three SMS-native entries
  (`Shriniwas410/*`); essentially no phone-call agents. A person who cannot use an app can use a
  phone. It also happens to record beautifully on video.
- **Real proprietary data.** Almost the entire field runs on synthetic fixtures: the same
  finding as the WebMCP scan, where it was the decisive moat. Competitors cannot retrofit real
  operational data in eleven days.
- **Multi-agent used properly.** Most entries are one agent plus tools. Strands ships swarm,
  graph, workflow and agent-as-tool patterns; "thoroughly and skillfully" is the actual wording
  of criterion 1.
- **AgentCore breadth.** Very few entrants use more than Runtime. Memory, Gateway, Identity,
  Browser and Code Interpreter are largely untouched.
- **Non-English / regional specificity with real data.** Four entries total (Hebrew, Danish,
  Korean, Japanese). Nothing India-specific.

---

## 4. Track selection

| Track | Crowding | Read |
|---|---|---|
| Everyday | Very high | Every registrant's first idea. Personal finance, chores, subscriptions, health reminders. |
| Professional | Highest | The default for a developer audience, and the DevOps-sentinel pile lands here. Much of it is *agents for engineers*, which strains the "for humans" theme and risks Stage One. |
| **Good Neighbor** | **Moderate** | Populated (~10 seen) but least so, and the entries are thinner. Also the track whose stories Developer Advocates most want to retell. |

Same logic as Agentic Cinema D1, pick for odds, not ceiling. Grand Prize is drawn from the
same pool regardless, so choosing the least-crowded track costs nothing and buys three shots.

**Recommendation: Good Neighbor**, unless the concept has a real-data moat that only exists in
Professional. A Professional entry backed by a real small business's live operational data would
beat a synthetic Good Neighbor entry: the moat outranks the track.

---

## 5. What wins here, given five equal criteria

The previous two projects optimised for a technical panel. This scoring says spread the effort.

- **Technological Implementation (20%).** Skillful Strands use, not merely present. Multi-agent
  pattern, hooks, structured output, MCP tools, session state, evals. Deploy on **AgentCore
  Runtime**. It is named in the criterion. A live demo link is explicitly called out as
  strengthening this score.
- **Design (20%).** "Complete product, not a proof of concept." Cheapest criterion to win and the
  one most entrants ignore, Agentic Cinema D13 protected the single-screen control room for
  exactly this reason and it was right. Use `ui-ux-pro-max` / `impeccable` before writing UI.
- **Potential Impact (20%).** A real audience, named. Not "small businesses", *this* organisation,
  *this* many rows, *this* much time. Real data does the work here.
- **Creativity & Originality (20%).** Read §3 again. Anything in the crowded table scores mid-field
  no matter how well built.
- **Presentation (20%).** Five minutes, end-to-end, working. Storyboard it on day 2, not day 10.

Plus **0.6 bonus points for three builder.aws.com posts**. Write all three.

---

## 6. Risks specific to this contest

- **The 24-day uptime obligation.** Judging runs to 2026-10-08 with judges invoking the agent.
  Bedrock and AgentCore bill per call. $50 of credits against three weeks of unmetered judge
  traffic is a real exposure, budget, cap concurrency, and set a spend alarm. Agentic Cinema
  D28 already paid for the lesson that the thing needing a bound is the *work*, not the
  request count.
- **Stage One theme fit.** "Agents for humans": an agent whose user is a Kubernetes cluster is
  a pass/fail risk. Whoever the human is, name them in the first sentence.
- **Newly-created rule.** Anything carried over from Passbook or Agentic Cinema gets disclosed.
- **AgentCore is a deployment target, not a weekend.** Do the deploy on day 3–4, not day 10.
  Agentic Cinema D24 found four bugs only at Cloud Run deploy time; the same will happen here.
- **Eleven days is more than either previous project got** (both were ~4 working days, 95 and 71
  commits). That is enough time to do the video properly for once.

---

## 7. Working checklist

**Day 0–1**
- [ ] Request the $50 AWS credits. Create the AWS Builder ID.
- [ ] Confirm Bedrock model access (Claude Sonnet) in the chosen region.
- [ ] `pip install strands-agents`; run one agent end-to-end. Day-one gate, as in Passbook.
- [ ] Deploy a hello-world to AgentCore Runtime **before** committing to a concept, so the
      deployment risk is known rather than assumed.
- [ ] Choose the concept against §3. Anything in the crowded table needs an explicit reason.

**Day 2–4**
- [ ] Storyboard the ≤5-minute video. It is 20% of the score on its own.
- [ ] Real data secured and privacy-reviewed. No real records committed, ever.
- [ ] Architecture diagram: a submission requirement, not optional.
- [ ] Multi-agent structure decided: swarm, graph, or agent-as-tool. Justify it in `DECISIONS.md`.

**Day 5–8**
- [ ] Product UI, built with the design skill invoked *before* the first component.
- [ ] Evals with fixed fixtures and a printed failure table, per Agentic Cinema's `RESULTS.md`.
- [ ] builder.aws.com post #1.
- [ ] Adversarial review of the running code against the real schemas, D28's lesson: run
      `tools/list` before writing anything that constrains a tool.

**Day 9–11**
- [ ] Record and cut the video. Audio checked. Uploaded public.
- [ ] Devpost text: problem, audience, how it works, why it matters.
- [ ] Public repo, MIT or Apache detectable in About. README with setup instructions.
- [ ] Live demo URL up, spend alarm set, cost capped for the run to 2026-10-08.
- [ ] builder.aws.com posts #2 and #3.
- [ ] Disclose AI tooling and any pre-existing code.
- [ ] **Post-deadline freeze.** Same discipline as Passbook: after 2026-09-14 17:00 PDT, do not
      touch the repo, the entry or the deployment until judging ends 2026-10-08. Fork to keep
      building.

---

## 8. Claims discipline, carried forward

From `web-mcp-2026/docs/PROJECT-RULES.md`, still binding:

- No stubs. No placeholder implementations dressed as real paths.
- Every agent capability has a human UI equivalent. That is the test of *product* over *tool demo*.
- Do not assume or invent. Verify against the real schema, the real doc, the real data.
- The headline is the **scale of what was handled**, never the mechanism.

---

## 9. Strands surface area, and what "skillfully" can mean

Verified against `strandsagents.com/docs/user-guide/quickstart/overview/` and the
`strands-agents/harness-sdk` monorepo, 2026-09-03. Note the repo was renamed: the Python SDK
now lives at **`strands-agents/harness-sdk` → `strands-py/`**, not `sdk-python`. Pip package is
still `strands-agents`; npm is `@strands-agents/sdk`.

Strands is positioned as an agent *harness* that runs in-process, "no hosted control plane,
scheduler, or database to stand up first."

| Capability | Python | TypeScript |
|---|---|---|
| Built-in tools | 30+ (community package) | 4 |
| Model providers | Bedrock (default), Anthropic, OpenAI, Google, Ollama, LiteLLM, 5+ more | Bedrock, OpenAI, Anthropic, Google, custom |
| Multi-agent | Swarms, Graphs, Workflows, Agents-as-tools, A2A | same |
| Sessions | File, S3, repository managers | same |
| Conversation mgmt | Null, sliding-window, summarizing | same |
| Hooks | Lifecycle hooks + custom providers | same |
| Structured output, streaming, MCP | yes | yes |
| Observability | OpenTelemetry | yes |
| Guardrails, evals | yes (`strands-agents/evals`) |, |
| **Bidirectional streaming (voice / realtime)** | **experimental, Python only** | no |

Deployment targets include Lambda, Fargate, App Runner, EKS, EC2, Docker, Kubernetes, Terraform
and **Amazon Bedrock AgentCore**, which has its own documented section.

**Two consequences.**

**Python, not TypeScript.** 30+ tools against 4, every provider, evals, and the voice path.
The TS SDK cannot reach the same technical score.

**The voice path is the sharpest available differentiator.** §3 found telephony and voice
near-absent across ~100 competitor repos, and bidirectional streaming is the one headline
capability that exists in exactly one of the two SDKs. It scores on three criteria at once:
Technological Implementation (a real, non-obvious part of the SDK), Creativity & Originality
(nobody else is there), and Presentation (a phone call is the single most legible thing that can
happen in a five-minute video). Being flagged **experimental** is the risk, and it is why it
gets a day-one gate rather than a day-eight integration: the same discipline that caught
`executeTool`'s double-JSON in Passbook before it could cost a day.

**Two claims to keep honest.** Using many Strands features is not the same as using them
skillfully; a swarm that a single agent would have done better is a worse answer, not a richer
one. And "30+ built-in tools" is the *community* package, not the core SDK, cite it that way.
