"""What a coding agent is told about each argument before it calls anything.

A tool's description explains the tool. Nothing explained the arguments: all
thirty-seven of them, across sixteen tools, arrived as a bare name and a type.
`call_provider_api(client, provider, path, method, query, body)` is six of
those, and one of them refuses a full URL for a reason nothing said out loud.

These are not cosmetic. The schema is the only thing a model reads before
choosing what to pass, and this repository's whole argument is that it is
better to be told than to guess.
"""

import os
import tempfile

import pytest


@pytest.fixture
def tools(monkeypatch, tmp_path):
    for name in ("MUNIM_CREDENTIALS", "MUNIM_SETTINGS", "MUNIM_TOOL_CACHE"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    from munim.server import build_server

    return build_server()._tool_manager.list_tools()


def _props(tool):
    return (tool.parameters or {}).get("properties", {})


def test_every_argument_of_every_tool_says_what_it_is_for(tools):
    """The guard. Adding a tool without describing its arguments fails here."""
    bare = [f"{t.name}.{name}"
            for t in tools
            for name, spec in _props(t).items()
            if not (spec.get("description") or "").strip()]

    assert bare == [], \
        f"these arrive as a bare name and a type: {', '.join(bare)}"


def test_a_description_is_a_sentence_rather_than_a_restated_name(tools):
    """"client: the client" tells a model nothing it could not already see."""
    lazy = []
    for t in tools:
        for name, spec in _props(t).items():
            said = (spec.get("description") or "").strip()
            if len(said) < 25 or said.lower().rstrip(".") == name.replace("_", " "):
                lazy.append(f"{t.name}.{name}: {said!r}")

    assert lazy == [], f"these say nothing useful: {'; '.join(lazy)}"


def test_describing_the_arguments_did_not_make_them_optional(tools):
    """The bug this nearly shipped with.

    `pydantic.Field`'s first positional argument is the **default**, so
    `Field("what this is for")` silently turns a required argument into an
    optional one whose default is a sentence. It shows up in the generated
    schema and nowhere in the code, which is why this asserts the schema.
    """
    required = {t.name: set((t.parameters or {}).get("required", []))
                for t in tools}

    assert required["call_provider_api"] == {"client", "provider", "path"}
    assert required["call_provider_tool"] == {"client", "provider", "tool"}
    assert required["work_on_client"] == {"client", "request"}
    assert required["connect_provider"] == {"client", "provider", "credential"}
    assert required["apply_mail_setup"] == {"client", "plan_id"}
    assert required["launch_status"] == set(), "run_id was always optional"


def test_no_argument_defaults_to_its_own_description(tools):
    """The same bug, caught from the other side and by shape rather than by
    naming the tools, so a new tool is covered without editing this file."""
    for t in tools:
        for name, spec in _props(t).items():
            default, said = spec.get("default"), spec.get("description")
            if isinstance(default, str) and said:
                assert default != said, \
                    f"{t.name}.{name} defaults to its own description"


def test_the_argument_that_refuses_a_url_says_so(tools):
    """`call_provider_api` takes a path and refuses an absolute URL, because
    an absolute URL would send this client's credential to another host. A
    model that learns that by being refused has already been surprised."""
    said = _props(next(t for t in tools if t.name == "call_provider_api"))
    path = said["path"]["description"].lower()

    assert "never a full url" in path or "not a full url" in path
    assert "credential" in path


def test_the_approval_argument_says_whose_decision_it_is(tools):
    """`approved` is the one argument in this surface that authorises changing
    somebody else's live DNS."""
    said = _props(next(t for t in tools if t.name == "apply_mail_setup"))

    assert "decision" in said["approved"]["description"].lower()


def test_an_argument_that_recurs_reads_the_same_way_everywhere(tools):
    """`provider` means one thing. Three tools describing it three ways is how
    a reader concludes it means three things."""
    seen = {t.name: _props(t)["provider"]["description"]
            for t in tools if "provider" in _props(t)}

    # call_provider_api is deliberately different: it names the only three
    # providers with a REST profile, which is narrower than being connected.
    others = {name: said for name, said in seen.items()
              if name != "call_provider_api"}
    assert len(set(others.values())) == 1, \
        f"the same argument is described {len(set(others.values()))} ways"


def test_a_tool_description_says_more_than_its_name(tools):
    """`add_client` was eighty characters and one of them.

    A model choosing between sixteen tools has the description and nothing
    else. Not a length contest: this is a floor, and the four highest-scoring
    descriptions in this surface are among the shortest.
    """
    thin = [f"{t.name} ({len(t.description or '')} chars)"
            for t in tools if len(t.description or "") < 150]

    assert thin == [], f"these say too little to choose between: {', '.join(thin)}"


def test_no_tool_description_is_an_essay(tools):
    """The other direction, and the one this codebase is actually prone to.

    Glama's evaluation called `work_on_client` "overly metaphorical" and scored
    every long description down for conciseness. The design reasoning belongs
    in comments beside the code, where a reader keeps it; the description is
    read by a model deciding which tool to call.
    """
    long = [f"{t.name} ({len(t.description or '')} chars)"
            for t in tools if len(t.description or "") > 1000]

    assert long == [], f"these are essays, not descriptions: {', '.join(long)}"


def test_the_tools_that_could_be_confused_point_at_each_other(tools):
    """Four tools read across clients or inspect them read-only, and an agent
    going on names alone could pick the wrong one. Each says which sibling to
    use instead."""
    said = {t.name: (t.description or "") for t in tools}

    assert "audit_all_clients" in said["check"]
    assert "fix" in said["check"]
    assert "find_across_clients" in said["audit_all_clients"]
    assert "audit_all_clients" in said["find_across_clients"]
    assert "client_status" in said["list_clients"]
    assert "list_clients" in said["client_status"]
    assert "call_provider_tool" in said["call_provider_api"]
