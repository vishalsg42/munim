"""The two Vercel failures worth catching are the ones the dashboard hides.

A variable set after the last build looks correct in the dashboard and is not
live. A variable scoped to Preview works every time you test it and is missing
when a customer arrives. Neither is visible by looking.
"""

import time

import httpx
import respx

from munim.adapters.vercel import Vercel
from munim.container import Container

API = "https://api.vercel.com"


class Keychain:
    def get(self, client, provider):
        return "vc-token" if provider == "vercel" else None


def _v():
    return Vercel(Container("acme", Keychain()))


def _ms(days_ago):
    return int((time.time() - days_ago * 86400) * 1000)


def _deploys(items):
    return httpx.Response(200, json={"deployments": items})


def _envs(items):
    return httpx.Response(200, json={"envs": items})


@respx.mock
async def test_a_failed_production_deploy_means_the_old_site_is_still_live():
    respx.get(f"{API}/v6/deployments").mock(return_value=_deploys([
        {"uid": "d3", "readyState": "ERROR", "target": "production",
         "url": "x.vercel.app", "createdAt": _ms(1)},
        {"uid": "d2", "readyState": "ERROR", "target": "production",
         "url": "x.vercel.app", "createdAt": _ms(2)},
    ]))
    result = await _v().check_deploy_current("p1")
    assert result.status == "fail"
    assert "older version" in result.human_text
    assert result.detail["failed"] == 2


@respx.mock
async def test_a_ready_production_deploy_passes():
    respx.get(f"{API}/v6/deployments").mock(return_value=_deploys([
        {"uid": "d1", "readyState": "READY", "target": "production",
         "url": "x.vercel.app", "createdAt": _ms(1)},
    ]))
    assert (await _v().check_deploy_current("p1")).status == "pass"


@respx.mock
async def test_a_variable_changed_after_the_last_build_is_not_live():
    """Vercel bakes build-time values in. The dashboard shows the new value and
    the running site uses the old one."""
    respx.get(f"{API}/v9/projects/p1/env").mock(return_value=_envs([
        {"key": "STRIPE_KEY", "target": ["production"], "createdAt": _ms(1)},
        {"key": "API_URL", "target": ["production"], "createdAt": _ms(9)},
    ]))
    respx.get(f"{API}/v6/deployments").mock(return_value=_deploys([
        {"uid": "d1", "readyState": "READY", "target": "production",
         "url": "x.vercel.app", "createdAt": _ms(5)},
    ]))
    result = await _v().check_env_applied("p1")
    assert result.status == "fail"
    assert result.detail["stale"] == ["STRIPE_KEY"]
    assert "never applied" in result.human_text


@respx.mock
async def test_variables_predating_the_build_are_live():
    respx.get(f"{API}/v9/projects/p1/env").mock(return_value=_envs([
        {"key": "API_URL", "target": ["production"], "createdAt": _ms(9)},
    ]))
    respx.get(f"{API}/v6/deployments").mock(return_value=_deploys([
        {"uid": "d1", "readyState": "READY", "target": "production",
         "url": "x.vercel.app", "createdAt": _ms(5)},
    ]))
    assert (await _v().check_env_applied("p1")).status == "pass"


@respx.mock
async def test_a_preview_only_variable_is_missing_where_it_matters():
    respx.get(f"{API}/v9/projects/p1/env").mock(return_value=_envs([
        {"key": "STRIPE_KEY", "target": ["preview"], "createdAt": _ms(9)},
        {"key": "API_URL", "target": ["production", "preview"], "createdAt": _ms(9)},
    ]))
    result = await _v().check_env_scoped("p1")
    assert result.status == "fail"
    assert result.detail["preview_only"] == ["STRIPE_KEY"]
    assert "customer arrives" in result.human_text


@respx.mock
async def test_reading_configuration_never_returns_a_value():
    """D6: inspecting a client's setup must not pull their secrets into a
    coding agent's context."""
    respx.get(f"{API}/v9/projects/p1/env").mock(return_value=_envs([
        {"key": "STRIPE_KEY", "target": ["production"], "createdAt": _ms(9),
         "value": "sk_live_do_not_leak"},
    ]))
    env = await _v().env_vars("p1")
    assert env[0].key == "STRIPE_KEY"
    assert "sk_live_do_not_leak" not in str(env)
    assert not hasattr(env[0], "value")


@respx.mock
async def test_the_token_is_sent_and_never_returned():
    route = respx.get(f"{API}/v9/projects").mock(
        return_value=httpx.Response(200, json={"projects": []}))
    result = await _v().projects()
    assert route.calls.last.request.headers["authorization"] == "Bearer vc-token"
    assert "vc-token" not in str(result)
