# Development

```bash
git clone https://github.com/vishalsg42/munim && cd munim
uv venv && uv pip install -e ".[dev]"

uv run pytest -q                       # the Python suite
node --test "tests/room/*.test.mjs"    # the control room's reducer
```

The control room is one HTML page and one ES module, served as written. There is
no build step and no `node_modules`; the only reason Node appears at all is to run
six tests over the reducer, and those need no install.

To check the claim this project rests on, connect two of your own accounts and run:

```bash
uv run python scripts/cross_account_probe.py
```

It fails if either account is empty, and fails if the two return the same
resources: two grants returning the same thing are one account wearing two names,
which would make the claim vacuous.
