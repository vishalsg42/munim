"""Whether Munim may think, and on whose model.

Munim used to reach a model host whenever one happened to be configured. A key
in `~/.munim/.env` was treated as consent, so `check`, `work_on_client` and
`ask_across_clients` sent a client's provider data to Google without anybody
deciding that they should. For a tool whose subject is credential isolation that
is the wrong default, so reasoning is opt-in now and off until asked for.

This module is policy and nothing else. It answers: are agents on, which host,
which model id, is there a key, and is that host's backend even installed. It
imports nothing from Strands, because deciding whether we are allowed to build a
model should not require the ability to build one. `agent/model.py` does the
construction and refuses when this module says off.

Two stores, and which goes where is not arbitrary:

  - `~/.munim/settings.json` holds what is not secret, beside registry.json and
    servers.json. It is meant to be readable and hand-editable.
  - the keychain holds the API keys, under the same `__munim__` account
    appcreds.py already uses for credentials belonging to the installation
    rather than to any client.

Everything here fails closed. A corrupt file, an unknown host name and a junk
`MUNIM_AI` value all mean "off", each with a reason `doctor` can print. A
settings module that raises would break every command, including the one you
would run to fix it.

Never logs a key.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Not a client. The same name appcreds.py uses, so the installation has one
# identity in the keychain rather than two.
from munim.appcreds import APPLICATION

# Beside registry.json, servers.json, runs/ and reports/.
SETTINGS_HOME = Path.home() / ".munim" / "settings.json"

AUTO = "auto"


@dataclass(frozen=True)
class Host:
    """One model host, and everything needed to decide whether it can be used.

    `needs` is the package that must actually import. Strands declares gemini
    and anthropic as extras, so its own model module exists on disk and raises
    ModuleNotFoundError for `google` underneath. Checking the Strands module is
    not enough, which is why this names the real dependency instead. Naming it
    here would also put a backend import path outside agent/model.py, which
    tests/test_model_hosts.py forbids on purpose.
    """
    name: str
    needs: str
    extra: str
    keys: tuple[str, ...]
    default_model: str
    model_env: str


HOSTS: dict[str, Host] = {
    "bedrock": Host(
        name="bedrock",
        needs="boto3",
        extra="",  # ships with strands-agents
        keys=(),   # AWS credentials, not an API key we store
        default_model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        model_env="MUNIM_BEDROCK_MODEL",
    ),
    "gemini": Host(
        name="gemini",
        needs="google.genai",
        extra="gemini",
        keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        default_model="gemini-2.5-flash",
        model_env="MUNIM_GEMINI_MODEL",
    ),
    "anthropic": Host(
        name="anthropic",
        needs="anthropic",
        extra="anthropic",
        keys=("ANTHROPIC_API_KEY",),
        default_model="claude-sonnet-5",
        model_env="MUNIM_ANTHROPIC_MODEL",
    ),
}

# The order `auto` tries. Bedrock first keeps D17's intent: restoring Bedrock is
# a config line rather than a code change.
ORDER = ("bedrock", "gemini", "anthropic")

TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off", ""}


def _path() -> Path:
    """Where settings live. MUNIM_SETTINGS is for tests and odd layouts.

    Exclusive, like MUNIM_ENV in env.py: naming a file and then silently reading
    a different one because the named one was missing makes a typo invisible.
    """
    named = os.environ.get("MUNIM_SETTINGS")
    return Path(named).expanduser() if named else SETTINGS_HOME


def read() -> tuple[dict, str]:
    """The stored settings, and a reason if they could not be read.

    Returns `({}, reason)` rather than raising. A hand-edited file with a
    trailing comma should cost you the setting, not every command.
    """
    path = _path()
    if not path.is_file():
        return {}, ""
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {}, f"{path} could not be read ({type(exc).__name__}), so agents are off"
    if not isinstance(loaded, dict):
        return {}, f"{path} is not a JSON object, so agents are off"
    return loaded, ""


def write(settings: dict) -> Path:
    """Store settings. Written the way registry.py writes: whole file, atomic.

    A half-written settings.json is a file that fails to parse, and this module
    treats that as "agents off". Losing the setting because the disk filled
    mid-write would be a silent downgrade.
    """
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, indent=2, sort_keys=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload + "\n")
    os.replace(tmp, path)
    return path


def truthy(value: str) -> tuple[bool, str]:
    """Read a switch. Anything unrecognised is off, and says so.

    `MUNIM_AI=maybe` meaning "on" because it is a non-empty string would be a
    trap, and meaning "off" silently would be a different one.
    """
    text = (value or "").strip().lower()
    if text in TRUE:
        return True, ""
    if text in FALSE:
        return False, ""
    return False, f"MUNIM_AI={value!r} is not a yes or a no, so agents are off"


def default_backend():
    from munim.container import KeychainBackend
    return KeychainBackend()


def remember_key(host: str, secret: str, backend=None) -> None:
    """Store a model API key where the working directory cannot affect it."""
    backend = backend or default_backend()
    backend.set(APPLICATION, f"model:{host}", secret)


def forget_key(host: str, backend=None) -> bool:
    """Remove a stored key. Only the keychain copy: an exported variable is the
    operator's, and quietly failing to remove what we said we removed would be
    worse than doing less."""
    backend = backend or default_backend()
    return bool(backend.forget(APPLICATION, f"model:{host}"))


def resolve_key(host: str, backend=None) -> tuple[str, str]:
    """(key, where it came from). Environment first, then the keychain.

    A value already exported is a deliberate act, and CI sets these. Same rule
    as appcreds.resolve, deliberately: two config systems disagreeing about
    precedence would be worse than either rule alone.
    """
    spec = HOSTS.get(host)
    if spec is None:
        return "", ""
    for name in spec.keys:
        found = os.environ.get(name)
        if found:
            return found, "environment"
    backend = backend or default_backend()
    stored = backend.get(APPLICATION, f"model:{host}")
    return (stored, "keychain") if stored else ("", "")


def installed(host: str) -> bool:
    """Whether this host's backend can actually be imported.

    Strands ships gemini and anthropic as extras, so a bare install has
    the Strands model module for Gemini on disk and no `google` package
    underneath it.
    Reporting a host as configured because a key is set, without this, is how
    `doctor` came to print OK for a host that raised ModuleNotFoundError.
    """
    import importlib.util

    spec = HOSTS.get(host)
    if spec is None:
        return False
    try:
        return importlib.util.find_spec(spec.needs) is not None
    except (ImportError, ValueError):
        return False


def usable(host: str, backend=None) -> bool:
    """Installed, and holding whatever credential it needs.

    Bedrock takes AWS credentials rather than an API key we store, and whether
    those work is only knowable at invocation, so being importable is as far as
    this can honestly go for it.
    """
    if not installed(host):
        return False
    spec = HOSTS[host]
    if not spec.keys:
        return True
    return bool(resolve_key(host, backend)[0])


@dataclass(frozen=True)
class Ai:
    """The resolved answer to "may we think, and on what"."""
    enabled: bool
    host: str            # a real host name, or AUTO
    model: str           # the id for `host`; empty when host is AUTO
    key: str             # empty when none is set or none is needed
    where: dict = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    def chosen(self, backend=None) -> str:
        """The host `auto` would settle on, or "" if none is usable.

        `auto` used to return Bedrock before it looked at anything else, and
        constructing a model does not authenticate, so an unusable Bedrock beat
        a working Gemini and only failed at invocation.
        """
        if self.host != AUTO:
            return self.host if usable(self.host, backend) else ""
        for name in ORDER:
            if usable(name, backend):
                return name
        return ""


def ai(backend=None) -> Ai:
    """Resolve every agent setting, with the reason for each answer.

    Environment beats stored beats default, except for the switch itself: see
    below.
    """
    stored, problem = read()
    problems = [problem] if problem else []
    section = stored.get("ai") if isinstance(stored.get("ai"), dict) else {}

    # The switch is read from the real environment only, never through
    # env.load(). load_dotenv writes into os.environ permanently and the MCP
    # server loads once at startup, so a MUNIM_AI in a file would go sticky for
    # the life of that process and silently beat every later settings.json
    # write. `munim config ai on` would report success while the running server
    # stayed off. doctor reports a file that carries it, because people will try.
    enabled = bool(section.get("enabled", False))
    where = {"enabled": "settings" if "enabled" in section else "default"}
    raw = os.environ.get("MUNIM_AI")
    if raw is not None:
        enabled, complaint = truthy(raw)
        where["enabled"] = "environment"
        if complaint:
            problems.append(complaint)

    host = (os.environ.get("MUNIM_AI_HOST")
            or os.environ.get("MUNIM_PREFER")
            or section.get("host")
            or AUTO)
    where["host"] = ("environment"
                     if os.environ.get("MUNIM_AI_HOST") or os.environ.get("MUNIM_PREFER")
                     else "settings" if section.get("host") else "default")
    if host != AUTO and host not in HOSTS:
        problems.append(f"{host!r} is not a model host Munim knows, so agents "
                        f"are off. Known: {', '.join(ORDER)}")
        enabled, host = False, AUTO

    models = section.get("models") if isinstance(section.get("models"), dict) else {}
    model, model_from = "", "default"
    if host != AUTO:
        spec = HOSTS[host]
        from_env = os.environ.get(spec.model_env)
        if from_env:
            model, model_from = from_env, "environment"
        elif models.get(host):
            model, model_from = models[host], "settings"
        else:
            model, model_from = spec.default_model, "default"
    where["model"] = model_from

    key, key_from = ("", "") if host == AUTO else resolve_key(host, backend)
    where["key"] = key_from or "none"

    return Ai(enabled=enabled, host=host, model=model, key=key,
              where=where, problems=tuple(problems))


def model_for(host: str, backend=None) -> str:
    """The model id to use for one host, resolved the same way."""
    spec = HOSTS[host]
    stored, _ = read()
    section = stored.get("ai") if isinstance(stored.get("ai"), dict) else {}
    models = section.get("models") if isinstance(section.get("models"), dict) else {}
    return (os.environ.get(spec.model_env) or models.get(host)
            or spec.default_model)


def set_enabled(on: bool) -> Path:
    stored, _ = read()
    section = stored.setdefault("ai", {})
    section["enabled"] = bool(on)
    return write(stored)


def set_host(host: str) -> Path:
    stored, _ = read()
    section = stored.setdefault("ai", {})
    section["host"] = host
    return write(stored)


def set_model(host: str, model_id: str) -> Path:
    """Model ids are stored per host.

    One shared id would be a bug rather than a simplification: set a Gemini id,
    switch the host to Bedrock, and it is handed to BedrockModel(model_id=...).
    The environment variables this replaces were already separate.
    """
    stored, _ = read()
    section = stored.setdefault("ai", {})
    models = section.setdefault("models", {})
    models[host] = model_id
    return write(stored)
