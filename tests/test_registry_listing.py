"""`server.json` is what the MCP Registry lists, and it repeats things.

The registry lists a server rather than hosting it, so `server.json` names the
PyPI package and its version alongside `pyproject.toml`, which names the same
two. A number written in two files is a number that will disagree, and the way
this one disagrees is quiet: the registry keeps pointing at a version that is no
longer current, and nothing fails.

`publish.yml` already refuses a tag that disagrees with `pyproject.toml`, for
the same reason and after burning a version to learn it. This is that check, one
file along.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER = json.loads((ROOT / "server.json").read_text())
PYPROJECT = (ROOT / "pyproject.toml").read_text()


def declared_version() -> str:
    found = re.search(r'^version = "([^"]+)"', PYPROJECT, re.M)
    assert found, "pyproject declares no version"
    return found.group(1)


def test_the_listed_version_matches_the_package():
    assert SERVER["version"] == declared_version()


def test_the_listed_package_version_matches_too():
    """Two versions in one file, and the packages entry is the one a client
    actually installs from."""
    assert SERVER["packages"][0]["version"] == declared_version()


def test_it_lists_the_package_this_repository_publishes():
    package = SERVER["packages"][0]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == "munim"
    assert 'name = "munim"' in PYPROJECT


def test_the_name_is_the_one_github_ownership_grants():
    """`login github-oidc` grants `io.github.<owner>/*` and nothing else, so a
    name outside that namespace is refused at publish rather than at review."""
    assert SERVER["name"] == "io.github.vishalsg42/munim"


def test_the_readme_carries_the_ownership_marker():
    """The registry verifies ownership by finding this string in the PyPI long
    description, which is README.md. Losing it does not break a build; it makes
    the next publish fail verification, which is a worse place to find out."""
    readme = (ROOT / "README.md").read_text()
    assert f"mcp-name: {SERVER['name']}" in readme


def test_the_entry_point_named_is_one_the_package_installs():
    """The registry entry says to run `munim-mcp`. If that console script is
    renamed, the listing sends people to a command that does not exist."""
    named = SERVER["packages"][0]["runtimeArguments"][0]["value"]
    assert f"{named} = " in PYPROJECT, f"{named} is not a console script"


def test_the_description_fits_what_the_schema_allows():
    """maxLength 100 in the published schema. A description that fails
    validation fails at publish time, on a tag, which cannot be undone."""
    assert len(SERVER["description"]) <= 100
