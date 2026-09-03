"""Vercel: what a project is doing, and what it is configured with.

Read-first on purpose. The two failures worth catching here are quiet ones:

  - An environment variable set but never applied, because Vercel bakes
    build-time values in and setting one changes nothing until a redeploy. The
    dashboard shows the new value; the running site uses the old one.
  - A variable set on Preview instead of Production. It works when you test it
    and is missing when a customer arrives.

Both look correct in the dashboard, which is why nobody finds them by looking.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from munim.checks.dns import CheckResult
from munim.container import Container


class VercelError(RuntimeError):
    pass


@dataclass
class Deployment:
    uid: str
    state: str
    url: str
    created_at: datetime
    target: str | None = None

    @classmethod
    def from_api(cls, payload: dict) -> "Deployment":
        return cls(
            uid=payload.get("uid") or payload.get("id", ""),
            state=payload.get("readyState") or payload.get("state", "UNKNOWN"),
            url=payload.get("url", ""),
            created_at=datetime.fromtimestamp(
                payload.get("createdAt", 0) / 1000, tz=timezone.utc),
            target=payload.get("target"),
        )


@dataclass
class EnvVar:
    key: str
    targets: list[str]
    created_at: datetime
    # The value is deliberately absent. Reading configuration must not mean
    # pulling every client's secrets into a coding agent's context (D6).


class Vercel:
    """One client's Vercel account, reached through their container."""

    name = "vercel"

    def __init__(self, container: Container, team_id: str = "") -> None:
        self._container = container
        self._team = team_id

    def _params(self, **extra) -> dict:
        params = {k: v for k, v in extra.items() if v not in (None, "")}
        if self._team:
            params["teamId"] = self._team
        return params

    async def _get(self, path: str, **params):
        async with self._container.http("vercel") as http:
            response = await http.get(path, params=self._params(**params))
        if response.status_code >= 400:
            raise VercelError(
                f"Vercel returned {response.status_code} for {path}: "
                f"{response.json().get('error', {}).get('message', response.text[:120])}"
            )
        return response.json()

    async def projects(self) -> list[dict]:
        payload = await self._get("/v9/projects", limit=100)
        return [{"id": p["id"], "name": p["name"],
                 "framework": p.get("framework"),
                 "updated": p.get("updatedAt")}
                for p in payload.get("projects", [])]

    async def deployments(self, project: str, limit: int = 10) -> list[Deployment]:
        payload = await self._get("/v6/deployments", projectId=project, limit=limit)
        return [Deployment.from_api(d) for d in payload.get("deployments", [])]

    async def env_vars(self, project: str) -> list[EnvVar]:
        """Names and scopes only; never values."""
        payload = await self._get(f"/v9/projects/{project}/env")
        return [
            EnvVar(key=e["key"], targets=e.get("target", []),
                   created_at=datetime.fromtimestamp(
                       e.get("createdAt", 0) / 1000, tz=timezone.utc))
            for e in payload.get("envs", [])
        ]

    async def check_deploy_current(self, project: str) -> CheckResult:
        """Is the site people see the site you last built?"""
        deployments = await self.deployments(project, limit=10)
        production = [d for d in deployments if d.target == "production"]
        if not production:
            return CheckResult("deploy_current", "skip",
                               "No production deployment yet.", "")
        latest = production[0]
        if latest.state == "READY":
            return CheckResult("deploy_current", "pass",
                               f"Production is {latest.state}, deployed "
                               f"{latest.created_at:%d %b %Y}.",
                               "The site your customers see is the latest version.",
                               evidence=latest.url)
        failed = [d for d in production if d.state in ("ERROR", "CANCELED")]
        return CheckResult(
            "deploy_current", "fail",
            f"Latest production deployment is {latest.state}; "
            f"{len(failed)} of the last {len(production)} failed.",
            "Your site is still showing an older version, because recent updates "
            "did not go live.",
            evidence=f"{latest.uid} {latest.state} {latest.created_at:%d %b %Y}",
            detail={"state": latest.state, "failed": len(failed)})

    async def check_env_applied(self, project: str) -> CheckResult:
        """A variable set after the last deploy has not taken effect.

        Vercel bakes build-time values in, so changing one in the dashboard
        changes nothing on the running site until a rebuild.
        """
        env = await self.env_vars(project)
        production = [e for e in env if "production" in e.targets]
        if not production:
            return CheckResult("env_applied", "skip", "No production variables.", "")
        deployments = [d for d in await self.deployments(project, limit=10)
                       if d.target == "production" and d.state == "READY"]
        if not deployments:
            return CheckResult("env_applied", "skip", "No successful production build.", "")

        last_build = deployments[0].created_at
        stale = [e for e in production if e.created_at > last_build]
        if not stale:
            return CheckResult("env_applied", "pass",
                               "Every production variable predates the last build.",
                               "Your settings are live on the site.")
        return CheckResult(
            "env_applied", "fail",
            f"{len(stale)} production variable(s) changed after the last build "
            f"({', '.join(e.key for e in stale)}); Vercel bakes build-time values "
            "in, so the running site still uses the old ones.",
            "A setting was changed but never applied - your live site is still "
            "using the previous value.",
            detail={"stale": [e.key for e in stale]})

    async def check_env_scoped(self, project: str) -> CheckResult:
        """A variable only on Preview works when you test and is missing live."""
        env = await self.env_vars(project)
        preview_only = [e for e in env
                        if "preview" in e.targets and "production" not in e.targets]
        if not preview_only:
            return CheckResult("env_scoped", "pass",
                               "No variables are preview-only.",
                               "Your settings apply to the live site, not just to tests.")
        return CheckResult(
            "env_scoped", "fail",
            f"{len(preview_only)} variable(s) exist only on Preview: "
            f"{', '.join(e.key for e in preview_only)}.",
            "Something is configured for your test site but not the real one, so "
            "it works when we check it and not when a customer arrives.",
            detail={"preview_only": [e.key for e in preview_only]})
