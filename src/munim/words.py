"""Counting things in a sentence a person reads.

There is one function here and it exists because "3 record(s)" kept appearing.
That construction is the sound of a program that could not be bothered, and
these strings are not debug output: they are shown to the operator deciding
whether to change somebody else's live DNS, and to the business owner in a
report about their own domain.

`doctor.py` already carries a comment about closing on "1 thing(s) need
attention", so this was noticed once and worked around locally rather than
fixed. Three local copies of the same helper had appeared before this file did.
"""


def count(n: int, singular: str, plural: str = "") -> str:
    """`3 records`, `1 record`, and never `1 record(s)`.

    Args:
        n: how many.
        singular: the word for one of them.
        plural: only when it is not the singular plus an s.
    """
    if n == 1:
        return f"1 {singular}"
    return f"{n} {plural or singular + 's'}"


def things(n: int) -> str:
    """The one irregular enough to be worth its own name."""
    return count(n, "thing")
