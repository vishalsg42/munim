# Your MCP server cannot print to stdout, and other things I learned building one

*Draft for builder.aws.com — post 2 of 3*

I wanted a live view of what my agent was doing: a browser page that fills in as
the agent works. The obvious design was one sentence in a plan document — *"the
agent emits one event stream; the terminal prints it and the browser renders
it"* — and it is not possible. Here is why, and what to do instead.

## stdout belongs to the protocol

An MCP server over stdio speaks JSON-RPC on stdin and stdout. Look at the Python
SDK's `mcp/server/stdio.py`:

```python
stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
...
await stdout.write(json + "\n")
await stdout.flush()
```

One JSON message per line, on the same file descriptor `print()` writes to. A
single stray `print("checking DNS…")` puts a non-JSON line into the stream and
the client's parser gives up. **Log to stderr, always.** This is documented, and
it is still the first thing people get wrong, because every other program you
have written prints progress to stdout.

## One transport, not two

The second instinct is to serve the browser from the same process:

```python
FastMCP.run(transport="stdio" | "sse" | "streamable-http")
```

That signature is a `Literal` of three, and you pick one. You *can* start a
second listener from a `lifespan`, and I nearly did. Four problems, none of them
obvious until you have them:

1. **Lifecycle.** The MCP server is a subprocess your coding agent owns. It dies
   on session exit, on config reload, on `/mcp` reconnect. Your page goes blank
   in the middle of a demo.
2. **Port rebinding.** When the client respawns the subprocess, the new one tries
   to bind the port the old one may not have released. Now your MCP server fails
   at startup, and the failure looks nothing like its cause.
3. **Two clients, one port.** The whole pitch of an MCP server is "add it to
   whatever agent you use." Add it to two and the second process cannot bind.
4. **No replay.** Server-Sent Events have no history. Open the page after the
   agent started, or hit refresh, and you see nothing.

## What worked: a file in the middle

The agent appends events to a JSONL file, one run per file. A separate process
tails it and serves SSE. That is the whole change, and it fixes all four:

```python
with self.path.open("a", encoding="utf-8") as handle:
    handle.write(event.model_dump_json() + "\n")
    handle.flush()
    os.fsync(handle.fileno())
```

- The viewer survives the MCP server restarting, because it was never inside it.
- Replay is free. `Last-Event-ID` maps to a sequence number and the reader
  seeks; SSE keeps no history but the file does.
- Append-only means a half-written run is a valid prefix, not a corrupt document.
- Two coding agents can both drive the same estate. They write different runs.

And the claim I originally wanted — *one source of truth, two consumers* —
becomes literally true rather than something stdio makes impossible.

## The part that surprised me

A run log is not only for display. Because every mutation is recorded, an
interrupted run can resume from what it already did. That turned out to matter
more than the live view: my agent writes DNS records, and a re-run that appended
a second SPF record instead of resuming would have created **the exact fault the
tool exists to detect**. Two SPF records mean receivers ignore both.

I built the file for a browser page. It ended up being what makes the agent safe
to re-run.

## If you are starting one

- Log to stderr. Assume `print()` is a bug.
- Decide early whether anything needs to outlive the subprocess. If yes, it does
  not live in the subprocess.
- A tool call that can run for minutes will hit the client's timeout. Split it:
  start returns an id, status reads progress from somewhere durable.
