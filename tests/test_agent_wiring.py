"""The Strands agent has to be reachable from the MCP surface.

It was not. `check` ran the deterministic checks itself and returned the JSON,
so `launch` had no callers anywhere outside its own package and `explain` never
executed. The README's architecture diagram showed a diagnosis step that no
code path could reach, and every demonstration was dnspython in a wrapper.

Nothing about the tool's output would have revealed it, which is why it is
pinned here.
"""

import pytest

import munim.agent.launch as agent_module
from munim.registry import ClientRecord, Registry
from munim.server import CROSS_CLIENT, MUTATING, build_server


class _Keychain:
    def __init__(self): self.store = {}
    def get(self, c, p): return self.store.get((c, p))
    def set(self, c, p, s): self.store[(c, p)] = s


def _server(tmp_path):
    registry = Registry(tmp_path / "registry.json")
    registry.add(ClientRecord(name="acme", domain="neverssl.com"))
    return build_server(backend=_Keychain(), registry=registry,
                        runs_dir=tmp_path / "runs",
                        reports_dir=tmp_path / "reports"), registry


@pytest.fixture
def agents_on(monkeypatch):
    """Agents are off by default now, including in the suite, so a test about
    the agent has to say so. That default is deliberate: it is what a fresh
    install gets, and the tests below would otherwise be the only place in the
    project where reasoning happens without anybody asking for it."""
    monkeypatch.setenv("MUNIM_AI", "1")


@pytest.fixture(autouse=True)
def _canned_checks(monkeypatch):
    """The wiring is what is under test, not the catalogue. Live lookups made
    these three tests take 27 seconds and depend on someone else's DNS."""
    from munim.checks.dns import CheckResult

    async def failing(domain, **kwargs):
        return [
            CheckResult("dkim_present", "fail", "No DKIM record.",
                        "Your mail is not signed.", resolver="1.1.1.1"),
            CheckResult("mx_present", "pass", "MX records present.",
                        "Mail can be delivered.", resolver="1.1.1.1"),
        ]

    async def none(domain, **kwargs):
        return []

    monkeypatch.setattr(agent_module, "run_all_async", failing)
    monkeypatch.setattr(agent_module, "run_reachability_async", none)


class _FakeAgent:
    """Stands in for Strands. Records that it was asked."""
    asked = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def invoke_async(self, prompt):
        _FakeAgent.asked.append(prompt)
        return "Your mail is not signed, so receivers cannot prove it is you."


async def test_check_runs_the_agent_when_something_failed(tmp_path, monkeypatch, agents_on):
    _FakeAgent.asked = []
    monkeypatch.setattr(agent_module, "build_model", lambda *a, **k: (object(), "fake"))
    monkeypatch.setattr(agent_module, "Agent", _FakeAgent)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})

    assert _FakeAgent.asked, "check completed without ever invoking the agent"
    prompt = _FakeAgent.asked[0]
    assert "neverssl.com" in prompt
    assert "acme" in prompt
    # The agent is given the deterministic findings, not asked to decide them.
    assert "Failing checks:" in prompt


async def test_the_agents_explanation_reaches_the_run_log(tmp_path, monkeypatch, agents_on):
    monkeypatch.setattr(agent_module, "build_model", lambda *a, **k: (object(), "fake"))
    monkeypatch.setattr(agent_module, "Agent", _FakeAgent)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})

    from munim.runlog import all_runs, RunLog
    runs = all_runs(tmp_path / "runs")
    events = list(RunLog(runs[-1], tmp_path / "runs").read())
    stages = {e.stage for e in events}
    assert "diagnose" in stages, f"no diagnosis in the run: {sorted(stages)}"
    assert any("receivers cannot prove" in e.human_text for e in events)


async def test_agents_off_costs_the_explanation_not_the_findings(tmp_path):
    """A fresh install has agents off. The checks must still land.

    This used to assert an `escalated` event, under the docstring "a missing
    model host has to be said out loud". That was right while having no host was
    a fault. Agents being off is a setting somebody chose, so it is reported as
    an observation: escalating on the default state would cry wolf on every run
    a fresh install makes.
    """
    server, _ = _server(tmp_path)
    result = await server.call_tool("check", {"target": "acme"})
    text = str(result[1] if isinstance(result, tuple) else result)
    assert "dkim_present" in text, text[:400]
    assert "'agents': 'off'" in text or '"agents": "off"' in text, \
        "check has to say so where the coding agent is actually looking"

    from munim.runlog import all_runs, RunLog
    runs = all_runs(tmp_path / "runs")
    events = list(RunLog(runs[-1], tmp_path / "runs").read())
    assert any(e.kind == "observation" and e.detail.get("agents") == "off"
               for e in events), "the run log has to say why there is no prose"
    assert not any(e.kind == "escalated" for e in events), \
        "a setting is not an escalation"
    assert any(e.kind == "finding" for e in events), \
        "the deterministic findings must survive the model being absent"


async def test_a_broken_host_still_escalates(tmp_path, monkeypatch, agents_on):
    """The other half. Agents on and the host failing is a fault, and still has
    to be said out loud: this is what the old test was protecting."""
    def broken(*a, **k):
        raise RuntimeError("bedrock said no")

    monkeypatch.setattr(agent_module, "build_model", broken)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})

    from munim.runlog import all_runs, RunLog
    runs = all_runs(tmp_path / "runs")
    events = list(RunLog(runs[-1], tmp_path / "runs").read())
    assert any(e.kind == "escalated" for e in events), \
        "a host that fails while agents are on has to be said out loud"
    assert any(e.kind == "finding" for e in events)


async def test_a_client_with_nothing_connected_is_told_so_when_agents_are_on(
        tmp_path, monkeypatch, agents_on):
    """The refusal that is about the client rather than about the switch."""
    import munim.agent.within as within

    monkeypatch.setattr(within, "connected_providers", lambda cid, backend=None: [])
    server, _ = _server(tmp_path)
    result = await server.call_tool("work_on_client",
                                    {"client": "acme", "request": "anything"})
    text = str(result)
    assert "no provider connected" in text
    assert "munim connect" in text, "a refusal with no next step is a complaint"


def test_the_agent_is_built_with_printing_turned_off():
    """Strands streams tokens to stdout by default and the MCP server writes
    JSON-RPC to the same stdout with nothing in between. The default handler
    interleaves prose with the protocol and kills the connection.

    Asserted on the construction call rather than by capturing output, because
    whether the corruption shows up depends on timing: the first run of this
    over real stdio came back clean and was still wrong.
    """
    import inspect

    source = inspect.getsource(agent_module.explain)
    assert "callback_handler=None" in source, \
        "Agent must be constructed with callback_handler=None"


async def test_the_agent_gets_provider_tools_for_connected_providers(tmp_path, monkeypatch, agents_on):
    """Built and unreachable is this project's recurring fault: the whole
    Strands agent was that way this morning. A toolset module nothing calls is
    the same bug waiting."""
    import munim.remote.storage as storage_mod
    import munim.remote.toolsets as toolsets_mod

    # Keyed by the client **id**, which is what sessions are filed under. This
    # fixture used to key on the name, so it asserted the bug: `launch` was
    # handed a label, looked it up in a store keyed by identity, matched
    # nothing for every real client, and reported no error at all.
    # Built first so the id below is the one this server will actually use;
    # `_server` makes a fresh registry per call.
    server, registry = _server(tmp_path)
    record = registry.clients()[0]
    connected = {(record.id, "cloudflare")}
    monkeypatch.setattr(
        storage_mod.KeychainTokenStorage, "_read",
        lambda self, kind: {"access_token": "t"} if (self._client, self._provider) in connected else None)
    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "endpoint",
                        lambda self: "")

    built = []
    monkeypatch.setattr(toolsets_mod, "toolset_for",
                        lambda c, p, **k: built.append((c, p, k)) or _Stub(p))
    monkeypatch.setattr(agent_module, "build_model", lambda *a, **k: (object(), "fake"))

    captured = {}

    class Recording(_FakeAgent):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(agent_module, "Agent", Recording)

    await server.call_tool("check", {"target": "acme"})

    assert [(c, p) for c, p, _ in built] == [(record.id, "cloudflare")], \
        "the session was looked up by something other than the client id"
    kwargs = built[0][2]
    assert kwargs.get("label") == record.name, \
        "without a label every tool prefix becomes the opaque client id"
    assert kwargs.get("read_only") is True, \
        "a diagnosis agent was handed unfiltered write tools"
    names = [getattr(t, "_prefix", None) for t in captured["tools"]]
    assert "cloudflare" in names, f"the agent did not receive it: {names}"


async def test_an_unconnected_provider_does_not_open_a_browser(tmp_path, monkeypatch, agents_on):
    """Building a toolset for a provider the client has not connected would
    start an OAuth flow in the middle of a diagnosis."""
    import munim.remote.storage as storage_mod
    import munim.remote.toolsets as toolsets_mod

    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "_read",
                        lambda self, kind: None)
    built = []
    monkeypatch.setattr(toolsets_mod, "toolset_for",
                        lambda c, p, **k: built.append((c, p)) or _Stub(p))
    monkeypatch.setattr(agent_module, "build_model", lambda *a, **k: (object(), "fake"))
    monkeypatch.setattr(agent_module, "Agent", _FakeAgent)

    server, _ = _server(tmp_path)
    await server.call_tool("check", {"target": "acme"})
    assert built == [], "a toolset was built for a provider with no session"


class _Stub:
    def __init__(self, prefix):
        self._prefix = prefix


async def test_work_on_client_is_given_that_client_and_no_other(tmp_path, monkeypatch, agents_on):
    """"Write within" has to be a property of what the agent holds, not a rule
    it is asked to follow. A request needing a second account should have
    nothing to reach with."""
    import munim.agent.within as within

    monkeypatch.setattr(within, "connected_providers", lambda cid, backend=None: ["cloudflare"])
    built = []
    monkeypatch.setattr(within, "toolset_for",
                        lambda cid, provider, **kw: built.append((cid, kw.get("label")))
                        or _Stub(provider))
    monkeypatch.setattr(within, "build_model", lambda *a, **k: (object(), "fake"))

    captured = {}

    class Recording(_FakeAgent):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(within, "Agent", Recording)

    server, registry = _server(tmp_path)
    await server.call_tool("work_on_client",
                           {"client": "acme", "request": "list the zones"})

    acme = registry.get("acme")
    assert built == [(acme.id, "acme")], "built a toolset for somebody else"
    assert len(captured["tools"]) == 1, "the agent was given more than one client"


async def test_work_on_client_with_agents_off_says_which_command(tmp_path):
    """Rather than a traceback, or a tool that vanished from the list.

    Keeping the tool registered and answering is the whole reason it was not
    made to disappear: a coding agent can read this and tell its operator what
    to run.
    """
    server, _ = _server(tmp_path)
    result = await server.call_tool("work_on_client",
                                    {"client": "acme", "request": "anything"})
    text = str(result)
    assert "agents" in text and "off" in text
    assert "munim config ai on" in text, \
        "a refusal with no next step is a complaint"


async def test_working_on_one_client_is_declared_mutating(tmp_path):
    server, _ = _server(tmp_path)
    tools = {t.name: t for t in await server.list_tools()}
    assert "work_on_client" in MUTATING
    assert "client" in tools["work_on_client"].inputSchema.get("required", [])
    assert "work_on_client" not in CROSS_CLIENT, \
        "a tool that can write must never be allowed to span clients"


# ---- through the real toolset helpers, not around them -------------------
#
# Every test above replaces `toolsets_for` / `toolset_for` with a `**k` stub,
# which is exactly why three faults lived here unseen: the real signatures were
# never called. `across` and `within` passed `backend=` to functions that take
# `keyring=`, so both raised TypeError the moment agents were on; `launch`
# looked sessions up by label in a store keyed by identity and silently found
# none; and nothing passed `allow_login=False`, so a question could have opened
# a browser and blocked for five minutes.
#
# So these fake one level deeper, at MCPClient.


class _Client:
    """Stands in for strands' MCPClient, recording how it was constructed."""

    made = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._prefix = kwargs.get("prefix")
        _Client.made.append(kwargs)

    def list_tools_sync(self):
        return []


@pytest.fixture
def real_toolsets(monkeypatch):
    import munim.remote.toolsets as toolsets_mod
    _Client.made = []
    monkeypatch.setattr(toolsets_mod, "MCPClient", _Client)
    return _Client


async def test_asking_across_clients_reaches_a_client(
        tmp_path, monkeypatch, agents_on, real_toolsets):
    """The TypeError. `across` called `toolsets_for(..., backend=...)` and the
    helper takes `keyring=`, so this raised for every real caller."""
    import munim.agent.across as across_mod
    import munim.remote.storage as storage_mod

    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "_read",
                        lambda self, kind: {"access_token": "t"}
                        if self._provider == "resend" else None)
    monkeypatch.setattr(across_mod, "build_model",
                        lambda *a, **k: (object(), "fake"))
    monkeypatch.setattr(across_mod, "Agent", _FakeAgent)

    await across_mod.ask("who?", [ClientRecord(name="acme")])

    assert real_toolsets.made, "no toolset was built through the real helper"


async def test_working_on_one_client_reaches_it(
        tmp_path, monkeypatch, agents_on, real_toolsets):
    """The same fault in `within`, which nothing exercised either."""
    import munim.agent.within as within_mod
    import munim.remote.storage as storage_mod

    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "_read",
                        lambda self, kind: {"access_token": "t"}
                        if self._provider == "resend" else None)
    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "endpoint",
                        lambda self: "")
    monkeypatch.setattr(within_mod, "build_model",
                        lambda *a, **k: (object(), "fake"))
    monkeypatch.setattr(within_mod, "Agent", _FakeAgent)

    class Log:
        def append(self, **k): pass

    await within_mod.work_on("c_1", "Acme Ltd", "do a thing", Log())

    assert real_toolsets.made, "no toolset was built through the real helper"


async def test_no_agent_path_may_open_a_browser(
        tmp_path, monkeypatch, agents_on, real_toolsets):
    """The one that turns a crash into something worse.

    `toolset_for` built its auth provider with the default `allow_login=True`,
    so once the TypeError above was fixed an unattended cross-client question
    could open a browser and block for five minutes waiting for a callback
    nobody is there to complete."""
    import munim.agent.across as across_mod
    import munim.remote.session as session_mod
    import munim.remote.storage as storage_mod

    asked = []
    real = session_mod.auth_for
    monkeypatch.setattr(
        "munim.remote.toolsets.auth_for",
        lambda c, p, **k: asked.append(k) or real(c, p, **k))
    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "_read",
                        lambda self, kind: {"access_token": "t"}
                        if self._provider == "resend" else None)
    monkeypatch.setattr(across_mod, "build_model",
                        lambda *a, **k: (object(), "fake"))
    monkeypatch.setattr(across_mod, "Agent", _FakeAgent)

    await across_mod.ask("who?", [ClientRecord(name="acme")])

    assert asked, "the real auth path was never reached"
    for kwargs in asked:
        assert kwargs.get("allow_login") is False, \
            "an agent path was built with a browser login still allowed"


async def test_a_provider_that_will_not_open_does_not_take_the_others_with_it(
        tmp_path, monkeypatch, agents_on):
    """MCPClient connects and lists tools while the Agent is constructed, so a
    single expired provider could abort the whole diagnosis."""
    import munim.agent.launch as launch_mod
    import munim.remote.storage as storage_mod
    import munim.remote.toolsets as toolsets_mod

    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "_read",
                        lambda self, kind: {"access_token": "t"})
    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "endpoint",
                        lambda self: "")

    def sometimes(client, provider, **k):
        if provider == "cloudflare":
            raise RuntimeError("session will not open")
        return _Stub(provider)

    monkeypatch.setattr(toolsets_mod, "toolset_for", sometimes)

    written = []

    class Log:
        def append(self, **k): written.append(k)

    ready = launch_mod._connected_toolsets("c_1", "Acme Ltd", Log())

    assert ready, "one bad provider took every other provider with it"
    assert any("cloudflare" in (e.get("human_text") or "") for e in written), \
        "the provider that failed was dropped without saying so"


async def test_a_toolset_with_no_tools_is_not_counted_as_one(
        tmp_path, monkeypatch, agents_on):
    """Cloudflare annotates nothing, so a read-only filter leaves it empty. The
    log said "1 provider toolset(s) available" while the agent held nothing,
    which is the bug wearing a reassuring number."""
    import munim.agent.launch as launch_mod
    import munim.remote.storage as storage_mod
    import munim.remote.toolsets as toolsets_mod

    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "_read",
                        lambda self, kind: {"access_token": "t"}
                        if self._provider == "cloudflare" else None)
    monkeypatch.setattr(storage_mod.KeychainTokenStorage, "endpoint",
                        lambda self: "")
    monkeypatch.setattr(toolsets_mod, "toolset_for",
                        lambda c, p, **k: _Stub(p))

    written = []

    class Log:
        def append(self, **k): written.append(k)

    launch_mod._connected_toolsets("c_1", "Acme Ltd", Log())

    counted = [e for e in written if "available" in (e.get("human_text") or "")]
    assert counted, "nothing was reported at all"
    assert "0 provider tool(s)" in counted[0]["human_text"], \
        f"an empty toolset was counted as available: {counted[0]['human_text']}"
