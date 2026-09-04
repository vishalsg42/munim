"""doctor must not give two different answers to "where does config go".

Run against a fresh HOME with nothing set up, it printed:

    ! Config      no .env found
                  -> create ~/.munim/.env, or a .env in the directory you run from
    x Model host  none configured
                  -> put GEMINI_API_KEY=... in .env

Two adjacent lines, one naming the file and one saying "in .env", which is the
exact ambiguity the env change existed to remove. A reader following the second
line puts the key wherever they happen to be and then cannot tell why it worked
yesterday and not today.

So no fix may say ".env" without saying which one.
"""

import re

from munim import doctor


def _all_fixes():
    """Every fix string doctor can print, gathered from the source rather than
    by running it, because reaching them all needs a machine with nothing set
    up and this has to hold on the machine running the tests."""
    import inspect
    source = inspect.getsource(doctor)
    return re.findall(r'fix=(?:f?"[^"]*"\s*)+', source)


def test_no_fix_line_says_dotenv_without_saying_which_one():
    vague = []
    for fix in _all_fixes():
        if ".env" not in fix:
            continue
        # CONFIG_HOME interpolates to ~/.munim/.env, so naming the variable
        # names the file just as well as writing it out.
        if any(ok in fix for ok in
               ("~/.munim/.env", "CONFIG_HOME", "munim config", "MUNIM_ENV")):
            continue
        vague.append(fix.strip()[:80])

    assert not vague, (
        "these tell somebody to edit .env without saying which .env, which is "
        f"the ambiguity ~/.munim/.env exists to remove: {vague}")


def test_the_config_finding_names_the_home_file():
    """The one line that gets it right, asserted so it stays right."""
    import inspect
    assert "CONFIG_HOME" in inspect.getsource(doctor._config)
