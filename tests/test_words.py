"""Counting things in a sentence a person reads.

Small enough to look unnecessary, which is why it kept being written wrong.
Five places in this codebase said "3 record(s)", one of them in a line shown to
the operator deciding whether to change somebody else's live DNS, and `doctor`
carried a comment about closing on "1 thing(s) need attention" rather than
fixing it.
"""

from munim import words


def test_one_of_something_is_singular():
    assert words.count(1, "record") == "1 record"
    assert words.count(1, "provider tool") == "1 provider tool"


def test_more_than_one_takes_an_s():
    assert words.count(3, "record") == "3 records"
    assert words.count(11, "provider tool") == "11 provider tools"


def test_none_of_something_is_plural():
    """Zero takes the plural in English, and this matters: the line that says
    how many provider tools an agent holds reports 0 when a read-only filter
    emptied every toolset."""
    assert words.count(0, "provider tool") == "0 provider tools"


def test_a_word_that_does_not_just_take_an_s():
    assert words.count(2, "entry", "entries") == "2 entries"
    assert words.count(1, "entry", "entries") == "1 entry"


def test_nothing_ever_produces_a_parenthesised_plural():
    """The whole point."""
    for n in (0, 1, 2, 17):
        assert "(s)" not in words.count(n, "record")
        assert "(s)" not in words.things(n)


def test_things_reads_correctly_at_one():
    assert words.things(1) == "1 thing"
    assert words.things(4) == "4 things"
