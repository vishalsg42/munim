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
                               backend=Ring(), allow_login=False):
            pass

    assert "c_never_connected" in str(caught.value)
    assert "cloudflare" in str(caught.value)


async def test_the_message_says_how_to_fix_it():
    """A refusal that does not say what to run is a dead end."""
    with pytest.raises(NeedsLogin, match="munim connect"):
        async with session_for("c_never_connected", "cloudflare",
                               backend=Ring(), allow_login=False):
            pass
