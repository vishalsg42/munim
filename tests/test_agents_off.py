"""With agents off, no tool reaches a model, and every one of them says so.

The tools stay registered rather than disappearing from the MCP tool list. That
was a decision: a tool called with agents off returns early, so absence would
buy no safety, and it would cost discoverability, because a coding agent that
cannot see the tool cannot tell its operator the feature exists or what to run.
The guarantee lives in build_model instead, which is the boundary where data
would actually leave.
"""

import pytest

from munim.registry import ClientRecord, Registry
from munim.server import build_server


class _Keychain:
    def __init__(self): self.store = {}
    def get(self, c, p): return self.store.get((c, p))
    def set(self, c, p, s): self.store[(c, p)] = s
    def forget(self, c, p): return self.store.pop((c, p), None) is not None


@pytest.fixture
def server(tmp_path):
    registry = Registry(tmp_path / "registry.json")
    registry.add(ClientRecord(name="acme", domain="example.com"))
    return build_server(backend=_Keychain(), registry=registry,
                        runs_dir=tmp_path / "runs",
                        reports_dir=tmp_path / "reports")


@pytest.fixture
def no_model_may_be_built(monkeypatch):
    """Fails the test rather than the assertion, so a refusal that happens to
    read correctly while still having built an agent cannot pass."""
    import munim.agent.across
    import munim.agent.launch
    import munim.agent.within

    def explode(*args, **kwargs):
        raise AssertionError("a model was built while agents were off")

    for module in (munim.agent.launch, munim.agent.across, munim.agent.within):
        monkeypatch.setattr(module, "build_model", explode)


def test_build_model_refuses_when_agents_are_off():
    """The guarantee. Every caller goes through here, including ones written
    later, which is why the gate is not repeated in each tool."""
    from munim.agent.model import AgentsDisabled, build_model

    with pytest.raises(AgentsDisabled) as raised:
        build_model()
    assert "munim config ai on" in str(raised.value)


def test_build_model_works_when_agents_are_on(monkeypatch):
    """The other direction. Without it the test above would pass just as well
    if build_model always raised."""
    from munim import settings
    from munim.agent import model as model_module

    monkeypatch.setenv("MUNIM_AI", "1")
    monkeypatch.setenv("MUNIM_AI_HOST", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(settings, "installed", lambda host: True)
    monkeypatch.setattr(model_module, "_construct",
                        lambda host, key: (object(), f"fake {host}"))

    _, label = model_module.build_model()
    assert label == "fake gemini"


async def test_work_on_client_refuses_and_names_the_command(server, no_model_may_be_built):
    result = await server.call_tool("work_on_client",
                                    {"client": "acme", "request": "anything"})
    text = str(result)
    assert "off" in text
    assert "munim config ai on" in text


async def test_ask_across_clients_refuses_and_names_the_command(server, no_model_may_be_built):
    result = await server.call_tool("ask_across_clients", {"question": "who?"})
    text = str(result)
    assert "off" in text
    assert "munim config ai on" in text


async def test_the_refusals_come_before_any_credential_is_read():
    """Both functions are importable, so a guard living only in the MCP tool
    would miss other callers, and reading the keychain first only to refuse
    would be the same answer for more work."""
    import asyncio

    from munim.agent.across import ask
    from munim.agent.within import work_on

    class Explode:
        # Vault-shaped, because that is what the session store is. This used to
        # define get/set, a CredentialBackend, and pass it where a keyring goes:
        # `get_password` would have raised AttributeError rather than the
        # assertion, so the test only worked as a sentinel by accident. Two
        # shapes, two names, and the parameter is now the one it always was.
        def get_password(self, *a, **k):
            raise AssertionError("read the credential store")

        def set_password(self, *a, **k):
            raise AssertionError("wrote to the credential store")

        def delete_password(self, *a, **k):
            raise AssertionError("deleted from the credential store")

    class Log:
        def append(self, **k): raise AssertionError("wrote to the run log")

    got = await work_on("c_1", "acme", "do a thing", Log(), keyring=Explode())
    assert got["agents"] == "off"
    assert "munim config ai on" in await ask("who?", [], keyring=Explode())


async def test_the_tools_are_still_listed(server):
    """Deliberately not hidden. A capability the operator switched off is not
    the same as one that was never built, and a coding agent needs to be able to
    see it in order to say how to turn it on."""
    names = {t.name for t in await server.list_tools()}
    assert {"work_on_client", "ask_across_clients", "check"} <= names


async def test_the_deterministic_tools_are_untouched(server, no_model_may_be_built):
    """The catalogue, the audit and the cross-client read never needed a model,
    and this must not have quietly changed that."""
    result = await server.call_tool("audit_all_clients", {})
    assert "error" not in str(result).lower() or "checked" in str(result)

    result = await server.call_tool("list_clients", {})
    assert "acme" in str(result)
