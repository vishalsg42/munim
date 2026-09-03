"""The launch report: one page per run, written for the business owner.

This is the only artefact in the project a non-technical person ever sees, which
makes it the answer to "agents for humans" rather than a claim about it. The
operator gets the run log; the owner gets this.

Rules it holds to:
  - Every line is something the owner can act on or be reassured by. No record
    names, no acronyms without a plain-English gloss in the same sentence.
  - It says what was checked, not just what failed. "Nothing wrong" is only
    meaningful if you can see the size of the net.
  - Findings come from the deterministic checks, so the page cannot claim a
    problem that was not measured (D7).
"""

import html
from datetime import datetime, timezone
from pathlib import Path

from munim.runlog import LaunchEvent, RunLog

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin:0; background:#fbfaf8; color:#17191c;
  font:16px/1.65 -apple-system,"Segoe UI",Inter,sans-serif; }
main { max-width:640px; margin:0 auto; padding:64px 24px 96px; }
.eyebrow { font-size:11px; letter-spacing:.18em; text-transform:uppercase;
  color:#8a8578; margin:0 0 8px; }
h1 { font-size:30px; line-height:1.2; letter-spacing:-.02em; margin:0 0 6px; }
.sub { color:#5f6368; margin:0 0 40px; }
h2 { font-size:13px; letter-spacing:.06em; text-transform:uppercase;
  color:#8a8578; margin:40px 0 12px; font-weight:600; }
.card { border:1px solid #e7e3db; background:#fff; border-radius:10px;
  padding:20px 22px; margin:0 0 12px; }
.card.warn { border-color:#f0b7b7; background:#fdf4f4; }
.card.fixed { border-color:#b9e0c4; background:#f3faf5; }
.card p { margin:0; }
.card .what { font-weight:600; margin:0 0 6px; }
.card .why { color:#5f6368; font-size:15px; }
ul.checks { list-style:none; margin:0; padding:0; column-count:2; column-gap:28px; }
ul.checks li { font-size:14px; color:#5f6368; padding:5px 0; break-inside:avoid; }
ul.checks li::before { content:"✓"; color:#3f9c5b; font-weight:700; margin-right:9px; }
ul.checks li.no::before { content:"!"; color:#c0504d; }
footer { margin-top:56px; padding-top:20px; border-top:1px solid #e7e3db;
  color:#8a8578; font-size:12px; }
code { font:12px/1.5 "SF Mono",ui-monospace,monospace; color:#5f6368;
  background:#f3f1ec; padding:2px 5px; border-radius:4px; }
"""


REPORTS_DIR = Path.home() / ".munim" / "reports"


def _e(text: str) -> str:
    return html.escape(str(text))


def render(log: RunLog, *, domain: str, business: str) -> str:
    events: list[LaunchEvent] = list(log.read())
    findings = [e for e in events if e.kind == "finding"]
    resolved = {e.detail.get("check") for e in events if e.kind == "resolved"}
    passed = [e for e in events if e.kind == "observation" and e.detail.get("check")]

    outstanding = [e for e in findings if e.detail.get("check") not in resolved]
    fixed = [e for e in findings if e.detail.get("check") in resolved]
    checked = len({e.detail.get("check") for e in passed} | {e.detail.get("check") for e in findings})

    if outstanding:
        headline = f"{len(outstanding)} thing{'s' if len(outstanding) > 1 else ''} needs your attention"
        sub = (f"We checked {checked} things about {domain}. Most were fine. "
               f"These were not, and they are the kind that break quietly.")
    else:
        headline = "Everything checks out"
        sub = (f"We checked {checked} things about {domain}, including the ones "
               "that fail without anyone noticing.")

    cards = []
    for e in fixed:
        cards.append(f'<div class="card fixed"><p class="what">Fixed &mdash; '
                     f'{_e(e.human_text)}</p></div>')
    for e in outstanding:
        why = e.detail.get("operator_text", "")
        cards.append(
            f'<div class="card warn"><p class="what">{_e(e.human_text)}</p>'
            + (f'<p class="why">Technically: {_e(why)}</p>' if why else "")
            + "</div>"
        )

    items = []
    for e in passed:
        items.append(f"<li>{_e(e.human_text)}</li>")
    for e in outstanding:
        items.append(f'<li class="no">{_e(e.human_text)}</li>')

    when = datetime.now(timezone.utc).strftime("%d %B %Y")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(business)} &mdash; what we checked</title>
<style>{_CSS}</style></head>
<body><main>
  <p class="eyebrow">{_e(when)}</p>
  <h1>{_e(headline)}</h1>
  <p class="sub">{_e(sub)}</p>
  {"".join(cards) if cards else ""}
  <h2>Everything we looked at</h2>
  <ul class="checks">{"".join(items)}</ul>
  <footer>
    Checked automatically for {_e(business)} &middot; <code>{_e(domain)}</code><br>
    Run {_e(log.run_id)}. Every result here came from a live lookup, not a guess.
  </footer>
</main></body></html>"""


def write(log: RunLog, *, domain: str, business: str, out_dir: Path | None = None) -> Path:
    directory = Path(out_dir or REPORTS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{log.run_id}.html"
    path.write_text(render(log, domain=domain, business=business), encoding="utf-8")
    return path
