"""Two answers that were wrong in the same way: confidently unhelpful.

Neither crashed. Both returned something that reads as an answer and is not
one, which is the failure mode this project keeps finding in itself: a report
that says nothing is wrong when the truth is that nothing was looked at.
"""

import pytest

from munim.container import (
    Container,
    KeychainBackend,
    UnknownCredential,
)
from munim.registry import ClientRecord, Registry
from munim.runlog import RunLog
from munim.server import build_server


class Backend:
    def __init__(self, store=None): self.store = store or {}
    def get(self, client, provider): return self.store.get((client, provider))


def test_an_unknown_run_says_so(tmp_path):
    """It reported events=0, done=false for a run id that does not exist.

    An agent that typos a run id was told the run exists and is empty, which is
    indistinguishable from a launch that has not started yet. It would wait.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    RunLog("20260101-000000-aaaaaa", runs).append(
        client="Acme", stage="dns", kind="stage_start", human_text="working")

    server = build_server(backend=Backend(),
                          registry=Registry(tmp_path / "r.json"),
                          runs_dir=runs)
    status = _tool(server, "launch_status")(run_id="nope-not-a-run")

    assert "error" in status, "an unknown run was reported as an empty run"
    assert "nope-not-a-run" in status["error"]
    assert status["runs"], "the ids that do exist should still come back"


def test_a_known_run_still_reads_back(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    log = RunLog("20260101-000000-aaaaaa", runs)
    log.append(client="Acme", stage="dns", kind="stage_start", human_text="working")
    log.append(client="Acme", stage="dns", kind="run_done", human_text="done")

    server = build_server(backend=Backend(),
                          registry=Registry(tmp_path / "r.json"),
                          runs_dir=runs)
    status = _tool(server, "launch_status")(run_id="20260101-000000-aaaaaa")

    assert "error" not in status
    assert status["events"] == 2 and status["done"] is True


def test_no_runs_at_all_is_not_an_error(tmp_path):
    """Nothing has run yet is a state, not a mistake."""
    runs = tmp_path / "runs"
    runs.mkdir()
    server = build_server(backend=Backend(),
                          registry=Registry(tmp_path / "r.json"),
                          runs_dir=runs)

    status = _tool(server, "launch_status")()
    assert status["runs"] == [] and status["run"] is None


def test_a_missing_credential_names_the_client_a_person_would_recognise(tmp_path):
    """It said `no resend credential for client 'c_2db35f36a043bf0c'`.

    That is the right identity and the wrong word for it. The operator has to
    map an opaque key back to a client before the message helps at all, and the
    label is right there on the record it was built from.
    """
    registry = Registry(tmp_path / "r.json")
    registry.add(ClientRecord(name="Kloudfirst"))
    box = Container.for_client(registry, "Kloudfirst", Backend())

    with pytest.raises(UnknownCredential) as caught:
        box.http("resend")

    assert "Kloudfirst" in str(caught.value)


def test_the_message_falls_back_to_the_id_when_there_is_no_label():
    """A container built directly has no record behind it and no label to use."""
    box = Container("c_abc", Backend())

    with pytest.raises(UnknownCredential) as caught:
        box.http("resend")

    assert "c_abc" in str(caught.value)


def _tool(server, name):
    """FastMCP keeps the undecorated callable; the tests want to call it."""
    import asyncio
    manager = server._tool_manager
    fn = manager._tools[name].fn
    if asyncio.iscoroutinefunction(fn):
        return lambda **kw: asyncio.run(fn(**kw))
    return fn


# ---- two stores, and a refusal that says which one is empty --------------


class _Sessions:
    """A vault holding one MCP session, the way `munim connect` leaves it."""

    def __init__(self, *, client="c_1", provider="resend"):
        self.store = {(f"munim-mcp:{provider}:tokens", client): '{"a": 1}'}
        self.asked = []

    def get_password(self, service, account):
        self.asked.append((service, account))
        return self.store.get((service, account))

    def set_password(self, service, account, secret):
        self.store[(service, account)] = secret

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


def test_a_provider_connected_by_oauth_says_so_rather_than_no_credential():
    """An operator was told by `client_status` that resend was connected and by
    `plan_mail_setup` that it had no resend credential, in the same minute.
    Both were true, about different stores, and neither said so."""
    from munim.container import Container, UnknownCredential

    box = Container("c_1", Backend(), keyring=_Sessions())

    with pytest.raises(UnknownCredential) as caught:
        box.http("resend")

    said = str(caught.value)
    assert "MCP session" in said, "it did not mention the session that exists"
    assert "REST API" in said, "it did not say what this path actually needs"
    assert "--token" in said, "it did not say how to fix it"


def test_a_provider_with_neither_credential_keeps_the_shorter_message():
    """The longer message is only useful when there is something to contrast
    with. Saying it always would be noise on the ordinary case."""
    from munim.container import Container, UnknownCredential

    box = Container("c_1", Backend(), keyring=_Sessions(provider="vercel"))

    with pytest.raises(UnknownCredential) as caught:
        box.http("resend")

    said = str(caught.value)
    assert "no resend credential" in said
    assert "MCP session" not in said


def test_the_session_lookup_names_only_this_client():
    """The isolation property, extended to the second store. `test_isolation`
    watches the injected backend and would have kept passing while a session
    read went to the module default and asked about anyone."""
    from munim.container import Container, UnknownCredential

    sessions = _Sessions()
    box = Container("c_1", Backend(), keyring=sessions)

    with pytest.raises(UnknownCredential):
        box.http("resend")

    assert sessions.asked, "the session store was never consulted"
    assert all(account == "c_1" for _, account in sessions.asked), \
        f"a container asked about another client: {sessions.asked}"


def test_a_container_with_no_keyring_still_refuses_cleanly():
    """The seam is optional: adapters built in tests pass no keyring at all."""
    from munim.container import Container, UnknownCredential

    with pytest.raises(UnknownCredential, match="no resend credential"):
        Container("c_1", Backend()).http("resend")
