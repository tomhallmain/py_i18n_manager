"""Trailing sentence punctuation alignment between default/source text and translations.

Used by machine translation cleanup and quality-review heuristics. Characters are grouped into
classes (period, question, exclamation, interrobang); locale rules pick the usual character for
that class (ASCII vs fullwidth CJK vs Arabic question mark, etc.).

**Limitations:** Matching is done on the **last Unicode scalar in logical (storage) order**, which
is what typical PO/YAML message strings use. Visually right-to-left lines (e.g. Arabic) still store
the sentence-final punctuation at the “string end” in logical order in most tools; we do not
analyze bidirectional runs or script-specific rules beyond a few language tags. Many scripts
(Devanagari, Thai, Hebrew, …) are not given bespoke punctuation here and use the Latin defaults
unless added later—or add the locale to :data:`LOCALES_WITHOUT_SENTENCE_STOP_ALIGNMENT` to skip
alignment entirely for that project.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

# --- Character classes (frozen sets; a character appears in at most one class) --------------------

# Full stop / period (ASCII, ideographic, fullwidth, CJK small form U+FE52).
PERIOD_CHARS: frozenset[str] = frozenset({".", "。", "\uff0e", "\ufe52"})

# Question (ASCII, fullwidth, Arabic, CJK small form U+FE56).
QUESTION_CHARS: frozenset[str] = frozenset({"?", "？", "\u061f", "\ufe56"})

# Exclamation (ASCII, fullwidth, double exclamation, CJK small form U+FE57, emoji-style marks).
EXCLAMATION_CHARS: frozenset[str] = frozenset(
    {"!", "！", "\u203c", "\ufe57", "\u2757", "\u2755"}
)

# Interrobang and combined question–exclamation marks (single codepoints).
INTERROBANG_CHARS: frozenset[str] = frozenset({"\u203d", "\u2048", "\u2049"})

# Unicode ellipsis (distinct from three ASCII full stops; strip as one unit when aligning).
ELLIPSIS_UNICODE_CHAR = "\u2026"


class SentenceEndingKind(Enum):
    """Semantic class of trailing sentence punctuation (last meaningful character)."""

    PERIOD = "period"
    QUESTION = "question"
    EXCLAMATION = "exclamation"
    INTERROBANG = "interrobang"


ALL_TRAILING_ALIGNABLE_CHARS: frozenset[str] = frozenset().union(
    PERIOD_CHARS,
    QUESTION_CHARS,
    EXCLAMATION_CHARS,
    INTERROBANG_CHARS,
    frozenset({ELLIPSIS_UNICODE_CHAR}),
)

# Locales where we skip aligning sentence-ending punctuation. Extend as needed.
LOCALES_WITHOUT_SENTENCE_STOP_ALIGNMENT: frozenset[str] = frozenset()

# ISO 639-1 language subtags that typically use the Arabic question mark (U+061F) for questions.
ARABIC_SCRIPT_PRIMARY_LANGUAGE_CODES: frozenset[str] = frozenset(
    {"ar", "fa", "ur", "ps", "ug", "sd"}
)


def _primary_language_subtag(locale: str) -> str:
    if not locale:
        return ""
    return locale.replace("_", "-").split("-", 1)[0].strip().lower()


def _uses_zh_ja_ideographic_sentence_punctuation(locale: str) -> bool:
    """Chinese and Japanese often use fullwidth 。／？／！ in UI; Korean usually uses ASCII .?! instead."""
    lang = _primary_language_subtag(locale)
    if lang == "ko":
        return False
    return lang in ("zh", "ja")


def classify_trailing_sentence_char(ch: str) -> Optional[SentenceEndingKind]:
    """Map a single trailing character to a :class:`SentenceEndingKind`, or ``None`` if not aligned."""
    if ch in INTERROBANG_CHARS:
        return SentenceEndingKind.INTERROBANG
    if ch in QUESTION_CHARS:
        return SentenceEndingKind.QUESTION
    if ch in EXCLAMATION_CHARS:
        return SentenceEndingKind.EXCLAMATION
    if ch in PERIOD_CHARS:
        return SentenceEndingKind.PERIOD
    return None


def source_trailing_sentence_kind(text: str) -> Optional[SentenceEndingKind]:
    """Return the sentence-ending kind of *text* after stripping trailing whitespace, if any.

    Strings that end with ``...`` (three ASCII periods) or the Unicode ellipsis (``…``) do not
    return a kind here; use :func:`source_expected_trailing_suffix` for those.
    """
    t = (text or "").rstrip()
    if not t:
        return None
    if t.endswith(ELLIPSIS_UNICODE_CHAR) or _endswith_three_ascii_full_stops(t):
        return None
    return classify_trailing_sentence_char(t[-1])


def _endswith_three_ascii_full_stops(text: str) -> bool:
    return len(text) >= 3 and text[-3:] == "..."


def source_expected_trailing_suffix(source_text: str, target_locale: str) -> Optional[str]:
    """Exact suffix the translation should use (ellipsis, locale-preferred ``.`` / ``?``, etc.)."""
    t = (source_text or "").rstrip()
    if not t:
        return None
    # Mirror ellipsis literally so ``Loading...`` does not normalize to ``Loading.``
    if t.endswith(ELLIPSIS_UNICODE_CHAR):
        return ELLIPSIS_UNICODE_CHAR
    if _endswith_three_ascii_full_stops(t):
        return "..."
    ch = t[-1]
    kind = classify_trailing_sentence_char(ch)
    if kind is None:
        return None
    return preferred_sentence_ending_for_locale(kind, target_locale)


def source_has_trailing_sentence_stop(text: str) -> bool:
    """True if *text* ends with any alignable sentence-ending character (any kind)."""
    t = (text or "").rstrip()
    if not t:
        return False
    if t.endswith(ELLIPSIS_UNICODE_CHAR) or _endswith_three_ascii_full_stops(t):
        return True
    return classify_trailing_sentence_char(t[-1]) is not None


def preferred_sentence_ending_for_locale(kind: SentenceEndingKind, target_locale: str) -> str:
    """Locale-preferred character for *kind* (ASCII vs zh/ja fullwidth vs Arabic question mark, etc.)."""
    loc = target_locale or ""
    if loc in LOCALES_WITHOUT_SENTENCE_STOP_ALIGNMENT:
        return _PREFERRED_LATIN[kind]

    lang = _primary_language_subtag(loc)

    # Arabic-script languages: question and interrobang map to the Arabic question mark; period and
    # exclamation stay ASCII (common in modern localized UIs).
    if lang in ARABIC_SCRIPT_PRIMARY_LANGUAGE_CODES:
        if kind in (SentenceEndingKind.QUESTION, SentenceEndingKind.INTERROBANG):
            return "\u061f"
        return _PREFERRED_LATIN[kind]

    if _uses_zh_ja_ideographic_sentence_punctuation(loc):
        return _PREFERRED_CJK[kind]

    return _PREFERRED_LATIN[kind]


_PREFERRED_LATIN: dict[SentenceEndingKind, str] = {
    SentenceEndingKind.PERIOD: ".",
    SentenceEndingKind.QUESTION: "?",
    SentenceEndingKind.EXCLAMATION: "!",
    SentenceEndingKind.INTERROBANG: "\u203d",  # ‽
}

_PREFERRED_CJK: dict[SentenceEndingKind, str] = {
    SentenceEndingKind.PERIOD: "。",
    SentenceEndingKind.QUESTION: "？",
    SentenceEndingKind.EXCLAMATION: "！",
    # No standard fullwidth interrobang; use fullwidth question as the usual substitute.
    SentenceEndingKind.INTERROBANG: "？",
}


def _strip_trailing_alignable_chars(s: str) -> str:
    t = s
    while t:
        u = t.rstrip()
        if not u:
            break
        if u.endswith(ELLIPSIS_UNICODE_CHAR):
            t = u[:-1]
            continue
        if u[-1] not in ALL_TRAILING_ALIGNABLE_CHARS:
            break
        t = u[:-1]
    return t


def normalize_translation_trailing_stop(
    source_text: str, translated_text: str, target_locale: str = ""
) -> str:
    """Align trailing sentence punctuation between *source_text* and *translated_text* for *target_locale*.

    When the source has no alignable closing punctuation, strip matching characters from the
    translation. When the source ends with a known pattern, strip any such run from the translation
    and append the expected suffix: three ASCII dots (``...``) or Unicode ellipsis (``…``) are kept
    as a unit (not collapsed to a single ``.``); other kinds use locale-preferred characters.
    """
    if translated_text is None:
        return ""
    raw = translated_text if isinstance(translated_text, str) else str(translated_text)
    loc = target_locale or ""

    if loc in LOCALES_WITHOUT_SENTENCE_STOP_ALIGNMENT:
        return raw

    suffix = source_expected_trailing_suffix(source_text, loc)
    if suffix is None:
        return _strip_trailing_alignable_chars(raw)

    u = raw.rstrip()
    core = _strip_trailing_alignable_chars(u)
    if not core:
        if not (raw or "").strip():
            return raw
        return suffix
    return core + suffix


def _both_end_with_equivalent_ellipsis(source_text: str, translated_text: str) -> bool:
    """True when both strings end with an ellipsis, mixing Unicode ``…`` (U+2026) and ``...`` freely."""
    s = (source_text or "").rstrip()
    t = (translated_text or "").rstrip()
    if not s or not t:
        return False
    s_ellipsis = s.endswith(ELLIPSIS_UNICODE_CHAR) or _endswith_three_ascii_full_stops(s)
    t_ellipsis = t.endswith(ELLIPSIS_UNICODE_CHAR) or _endswith_three_ascii_full_stops(t)
    return s_ellipsis and t_ellipsis


def _cjk_trailing_semantically_matches_source(source_text: str, translated_text: str) -> bool:
    """True when zh/ja should not flag ASCII vs fullwidth for the same sentence-ending *role*.

    Applies only to **exclamation** and **question** (e.g. English ``!`` vs Chinese ``！``). Periods
    stay strict: ``.`` vs ``。`` is still judged by :func:`normalize_translation_trailing_stop` alone.
    Ellipsis (``…`` vs ``...``) is handled only in :func:`translation_has_stop_inconsistency_vs_source`.
    """
    s = (source_text or "").rstrip()
    t = (translated_text or "").rstrip()
    if not s or not t:
        return False

    if (
        s.endswith(ELLIPSIS_UNICODE_CHAR)
        or _endswith_three_ascii_full_stops(s)
        or t.endswith(ELLIPSIS_UNICODE_CHAR)
        or _endswith_three_ascii_full_stops(t)
    ):
        return False

    ks = classify_trailing_sentence_char(s[-1])
    kt = classify_trailing_sentence_char(t[-1])
    if ks is None:
        return kt is None
    if ks != kt:
        return False
    if ks == SentenceEndingKind.PERIOD:
        return False
    return ks in (SentenceEndingKind.EXCLAMATION, SentenceEndingKind.QUESTION)


def translation_has_stop_inconsistency_vs_source(
    source_text: str, translated_text: str, target_locale: str
) -> bool:
    """True when *translated_text* is not what :func:`normalize_translation_trailing_stop` would produce."""
    if not (source_text or "").strip():
        return False
    if not (translated_text or "").strip():
        return False
    loc = target_locale or ""
    if loc in LOCALES_WITHOUT_SENTENCE_STOP_ALIGNMENT:
        return False
    fixed = normalize_translation_trailing_stop(source_text, translated_text, target_locale)
    tr = (translated_text or "").rstrip()
    if tr == (fixed or "").rstrip():
        return False
    # Unicode ellipsis (U+2026) vs three ASCII dots: same meaning; do not flag (all locales).
    if _both_end_with_equivalent_ellipsis(source_text, translated_text):
        return False
    # zh/ja: do not flag ASCII vs fullwidth when the sentence-ending *kind* matches (e.g. ``!`` vs ``！``).
    if _uses_zh_ja_ideographic_sentence_punctuation(loc) and _cjk_trailing_semantically_matches_source(
        source_text, translated_text
    ):
        return False
    return True


# Backward-compatible name used in early iterations (period-only); prefer :func:`source_trailing_sentence_kind`.
def preferred_trailing_sentence_stop_for_locale(target_locale: str) -> str:
    """Return the preferred *period* character for *target_locale* (``.`` vs ``。``)."""
    return preferred_sentence_ending_for_locale(SentenceEndingKind.PERIOD, target_locale)
