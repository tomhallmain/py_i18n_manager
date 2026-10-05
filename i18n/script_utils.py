"""Character-level writing-system helpers shared by validation and quality-review heuristics."""

import unicodedata


def is_latin_char(ch: str) -> bool:
    """True when ``ch`` is a single alphabetic character whose Unicode name contains ``LATIN``.

    Counts as Latin: plain and accented letters (``é``, ``ç``, ``ã``, ``ß``), fullwidth forms
    (``Ａ``) and ligatures (``ﬁ``). Not Latin: digits, punctuation, whitespace, non-letter
    symbols even when their name mentions Latin (circled ``ⓐ`` is not ``isalpha()``), and
    look-alike letters from other scripts such as Cyrillic ``с`` or ``В``. That last case is
    what lets the quality-review heuristics tell a stray Latin ``c`` from the Cyrillic ``с``
    it imitates. Returns False for an empty string or a character with no Unicode name.
    """
    if not ch or not ch.isalpha():
        return False
    return "LATIN" in unicodedata.name(ch, "")
