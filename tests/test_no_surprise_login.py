"""A read-only script must never start a browser login.

scripts/cross_account_probe.py exists to verify a claim without changing
anything. Run after a Cloudflare token had expired, it opened a browser,
printed an authorize URL and blocked for five minutes waiting for a callback,
then failed on a port another process was holding. None of that is verification.

The same applies to anything running unattended: an expired token should be a
legible "reconnect this client", not a prompt nobody is there to answer.
"""

import pytest

from munim.remote.session import NeedsLogin, session_for


class Ring:
    def __init__(self): self.s = {}
    def get_password(self, a, b): return self.s.get((a, b))
    def set_password(self, a, b, c): self.s[(a, b)] = c
    def delete_password(self, a, b): self.s.pop((a, b), None)


async def test_a_session_that_would_need_a_login_refuses_instead():
    """Nothing stored, so opening one means authorising. With allow_login off
    that has to raise rather than reach for a browser."""
    with pytest.raises(NeedsLogin) as caught:
        async with session_for("c_never_connected", "cloudflare",
                               keyring=Ring(), allow_login=False):
            pass

    assert "c_never_connected" in str(caught.value)
    assert "cloudflare" in str(caught.value)


async def test_the_message_says_how_to_fix_it():
    """A refusal that does not say what to run is a dead end."""
    with pytest.raises(NeedsLogin, match="munim connect"):
        async with session_for("c_never_connected", "cloudflare",
                               keyring=Ring(), allow_login=False):
            pass


async def test_the_refusal_is_not_buried_under_a_traceback(caplog):
    """A legible refusal is the whole point, so the SDK's traceback is dropped.

    `mcp.client.auth.oauth2` ends its flow with `logger.exception("OAuth flow
    error")` and re-raises. For a real failure that is right. For this one it
    printed fourteen lines of traceback above a one-line "run munim connect",
    which is the opposite of what allow_login=False is for.
    """
    import logging

    with caplog.at_level(logging.ERROR, logger="mcp.client.auth.oauth2"):
        with pytest.raises(NeedsLogin):
            async with session_for("c_never_connected", "cloudflare",
                                   keyring=Ring(), allow_login=False):
                pass

    assert "OAuth flow error" not in caplog.text


async def test_a_real_oauth_failure_still_logs(caplog):
    """Only the deliberate refusal is quieted. Hiding a fault would be the bug."""
    import logging

    from munim.remote.session import _QuietRefusal

    quiet = _QuietRefusal()

    def record(error):
        made = logging.LogRecord("mcp.client.auth.oauth2", logging.ERROR,
                                 __file__, 1, "OAuth flow error", (), None)
        made.exc_info = (type(error), error, None)
        return made

    assert quiet.filter(record(NeedsLogin("asked for"))) is False
    assert quiet.filter(record(ValueError("a real one"))) is True


# ---- the noise a provider makes about a session it already dropped -------

def test_a_teardown_404_is_not_reported_as_a_failure():
    """Supabase issues a session id then answers the teardown DELETE with 404.
    The SDK forgives 405 and warns on everything else, so every clean run ended
    with `Session termination failed: 404` under a line saying it worked."""
    import logging

    from munim.remote.session import _QuietTeardown

    quiet = _QuietTeardown()

    def record(message):
        return logging.LogRecord("mcp.client.streamable_http", logging.WARNING,
                                 "", 0, message, (), None)

    assert quiet.filter(record("Session termination failed: 404")) is False
    assert quiet.filter(record("Session termination failed: 405")) is False


def test_a_teardown_that_fails_for_another_reason_still_says_so():
    """The session was closing anyway, but a transport error there is a signal
    about the connection. Hiding every teardown failure would be the real bug."""
    import logging

    from munim.remote.session import _QuietTeardown

    quiet = _QuietTeardown()

    def record(message):
        return logging.LogRecord("mcp.client.streamable_http", logging.WARNING,
                                 "", 0, message, (), None)

    assert quiet.filter(record("Session termination failed: 500")) is True
    assert quiet.filter(
        quiet and record("Session termination failed: ConnectError")) is True
    assert quiet.filter(record("something else entirely")) is True


def test_the_filter_is_not_stacked_once_per_session():
    """It is added at import against the SDK's own logger; adding it per call
    would pile up one copy per session opened."""
    import logging

    from munim.remote.session import hush_teardown

    logger = logging.getLogger("mcp.client.streamable_http")
    hush_teardown()
    hush_teardown()
    from munim.remote.session import _QuietTeardown
    assert sum(isinstance(f, _QuietTeardown) for f in logger.filters) == 1


def test_the_sign_in_prompt_never_goes_to_stdout():
    """The MCP server speaks JSON-RPC over stdout. One non-protocol line there
    makes the client drop the server, which is what "all fourteen tools
    vanished mid-session and did not come back" looks like from the outside.

    No server path reaches this today, because each passes `allow_login=False`.
    The default is `True`, so the distance between unreachable and reachable is
    one keyword argument, and this is cheaper than remembering that."""
    from pathlib import Path

    source = Path("src/munim/remote/session.py").read_text()
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("print(") or stripped.startswith("print(f"):
            assert "file=sys.stderr" in line or "file=sys.stderr" in source[
                source.index(line):source.index(line) + 400], \
                f"a print in the session module may reach stdout: {stripped}"
