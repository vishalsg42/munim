# Contributing

Munim is a small project with an unusual amount of written reasoning in it, and
the reasoning is the part that is easy to lose. Most of this file is about that.

## Getting set up

```bash
uv sync --extra dev
uv run pytest tests/ -q          # the Python suite
node --test tests/room/*.test.mjs # the control room's reducer
uvx ty check src/munim/           # finds a class of fault no test here catches
```

No account and no key is needed for either suite, or for running the thirteen
checks against any domain you like:

```bash
uv run munim check example.com
```

## What a good change looks like here

**Say why, not what.** The code says what it does. Comments and commit messages
in this repository say why it is that way, and usually name the thing that went
wrong when it was the other way. That is not decoration: three separate bugs in
this project were one root cause spelled differently, and the comments are how
the fourth was caught before it shipped.

**A test that fails first.** Every fix should have a test that fails without it.
Say so in the commit message, because "I added a test" and "the test would have
caught this" are different claims and only the second is worth anything.

**Fake at the right depth.** Several bugs here lived for weeks because tests
replaced the very function that was broken with a stub that accepted anything.
If you are testing that A calls B correctly, fake below B, not B itself.

**Run it.** Four bugs in this project were found by running the thing and not by
any test: a tool-name collision, a rubric that could not fail, a status that read
the wrong store, and a stall that made the server look dead. If a change touches
a live path, drive it against something real before saying it works.

**No em dashes**, and no `(s)` plurals. Both read as machine-written and the rest
of the prose does not.

## Decisions

`docs/DECISIONS.md` is a numbered log, currently through D32. If a change makes
a call that a later reader would otherwise have to reverse-engineer, add an
entry. Several existing entries reverse an earlier one, and that is the point:
the log records what was believed and when, not a tidy final answer.

Code comments cite them by number, `(D5)`, `(D31)`. Keep that.

## Claims discipline

`docs/SUBMISSION.md` and `README.md` make claims about what works. If a change
makes one of them wrong, fix the sentence in the same commit. This has cut both
ways already: a section once said two functions were tested when one had no
test, and a section once disclaimed a capability that had since been built.

If you cannot make a claim true, say so plainly rather than softening it.
`docs/ROADMAP.md` exists for exactly that and is worth reading before you decide
something is a bug.

## Credentials, in tests and in prose

Never commit a real client's name, domain, email address or account identifier.
The examples are `Acme Ltd` and `acme.example`. This repository has had to
redact real ones once, from a README that was also the PyPI page, which is a
mistake worth not repeating.

Tests must not touch the real store. `tests/conftest.py` points every path at a
temporary directory and asserts it stays there; if you add a new file the tool
writes to, add it there too.

## Opening a pull request

Describe what was broken, how you know, and what would have caught it. Long is
fine. The pull requests in this repository read like short incident reports and
that has been useful more than once.
