"""Character-level writing-system helpers shared by validation and quality-review heuristics."""

import unicodedata


def is_latin_char(ch: str) -> bool:
    """True for a Latin-script letter (including accented forms such as ``é``, ``ç``, ``ã``)."""
    if not ch or not ch.isalpha():
        return False
    return "LATIN" in unicodedata.name(ch, "")
