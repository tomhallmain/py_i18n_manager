"""Quote-character-style detection for the quote-style quality review heuristic.

Many languages have a formal convention for which quote characters are "correct"
(German „…", French «…», Japanese 「…」, ...), distinct from the plain ASCII/typewriter
quotes ("…") that software commonly uses everywhere regardless of locale. This module defines
a small set of known quote-character pairings and detects which one (if any) a piece of text
uses, so quality review can compare a translation's actual quote style against both the
locale's expected style and what the rest of the catalog is actually doing for that locale.

Scope notes:
- Only double-quote and single-quote *pairs* are recognized (an opening character followed
  later in the same string by its matching closing character). A string with no recognizable
  pair, or with more than one *conflicting* style's pair present (whether from double quotes,
  single quotes, or a mix of the two), is treated as unclassifiable (``None``) rather than
  guessed at.
- Double- and single-quote pairs are equally valid evidence of a style; neither is given
  priority over the other (a straight double pair and a straight single pair in the same string
  both just point to STRAIGHT). The straight single-quote pair specifically additionally
  requires the surrounding characters not be letters, since single quote characters are far more
  ambiguous than double quotes (English apostrophes/contractions reuse the straight ``'``
  character) -- this avoids matching contractions like "don't" as a quote pair.
- This list is intentionally not exhaustive of every world language; unknown locales simply
  have no built-in "valid" default (see :func:`default_valid_quote_style`) and fall back to
  whatever style is actually dominant in that locale's own translations.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from .translation_group import TranslationGroup, TranslationKey


class QuoteStyle(str, Enum):
    """A named pairing of opening/closing quote characters (double- and single-quote forms)."""

    STRAIGHT = "straight"
    CURLY = "curly"
    GUILLEMETS = "guillemets"
    GUILLEMETS_REVERSED = "guillemets_reversed"
    LOW_HIGH_9_9 = "low_high_9_9"
    LOW_HIGH_9_0 = "low_high_9_0"
    CJK_CORNER = "cjk_corner"

    @classmethod
    def from_value(cls, value, default: Optional["QuoteStyle"] = None) -> Optional["QuoteStyle"]:
        try:
            return cls(value)
        except (ValueError, TypeError):
            return default

    def get_display_name(self) -> str:
        from utils.translations import I18N

        _ = I18N._
        names: Dict["QuoteStyle", str] = {
            QuoteStyle.STRAIGHT: _('Straight quotes (" ")'),
            QuoteStyle.CURLY: _("Curly quotes (“ ”)"),
            QuoteStyle.GUILLEMETS: _("Guillemets (« »)"),
            QuoteStyle.GUILLEMETS_REVERSED: _("Reversed guillemets (» «)"),
            QuoteStyle.LOW_HIGH_9_9: _("Low-high quotes („ “)"),
            QuoteStyle.LOW_HIGH_9_0: _("Low-high quotes („ ”)"),
            QuoteStyle.CJK_CORNER: _("Corner brackets (「 」)"),
        }
        return names[self]


# (open, close) character pairs for each style's double- and single-quote forms.
_DOUBLE_QUOTE_PAIRS: Dict[QuoteStyle, Tuple[str, str]] = {
    QuoteStyle.STRAIGHT: ('"', '"'),
    QuoteStyle.CURLY: ("“", "”"),
    QuoteStyle.GUILLEMETS: ("«", "»"),
    QuoteStyle.GUILLEMETS_REVERSED: ("»", "«"),
    QuoteStyle.LOW_HIGH_9_9: ("„", "“"),
    QuoteStyle.LOW_HIGH_9_0: ("„", "”"),
    QuoteStyle.CJK_CORNER: ("「", "」"),
}

_SINGLE_QUOTE_PAIRS: Dict[QuoteStyle, Tuple[str, str]] = {
    QuoteStyle.STRAIGHT: ("'", "'"),
    QuoteStyle.CURLY: ("‘", "’"),
    QuoteStyle.GUILLEMETS: ("‹", "›"),
    QuoteStyle.GUILLEMETS_REVERSED: ("›", "‹"),
    QuoteStyle.LOW_HIGH_9_9: ("‚", "‘"),
    QuoteStyle.LOW_HIGH_9_0: ("‚", "’"),
    QuoteStyle.CJK_CORNER: ("『", "』"),
}


def _pair_pattern(open_ch: str, close_ch: str) -> "re.Pattern[str]":
    return re.compile(re.escape(open_ch) + r"[^\n]*?" + re.escape(close_ch))


# Straight single quotes double as apostrophes (contractions, possessives), so require the
# opening quote not be preceded by a letter and the closing quote not be followed by a letter --
# "he said 'hi' to me" matches; "don't" and "the cats' toys" do not.
_STRAIGHT_SINGLE_QUOTE_PATTERN = re.compile(r"(?<![A-Za-z])'[^'\n]*?'(?![A-Za-z])")

_DOUBLE_QUOTE_PATTERNS: Dict[QuoteStyle, "re.Pattern[str]"] = {
    style: _pair_pattern(open_ch, close_ch)
    for style, (open_ch, close_ch) in _DOUBLE_QUOTE_PAIRS.items()
}

_SINGLE_QUOTE_PATTERNS: Dict[QuoteStyle, "re.Pattern[str]"] = {
    style: (
        _STRAIGHT_SINGLE_QUOTE_PATTERN
        if style is QuoteStyle.STRAIGHT
        else _pair_pattern(open_ch, close_ch)
    )
    for style, (open_ch, close_ch) in _SINGLE_QUOTE_PAIRS.items()
}


def detect_quote_style(text: str) -> Optional[QuoteStyle]:
    """Return the single quote style *text* appears to use, or ``None`` if none/ambiguous.

    Double- and single-quote pairs are equally valid evidence of a style -- neither form is
    given priority over the other. A style counts as present if *either* its double-quote pair
    or its single-quote pair is found. If that evidence spans more than one distinct style
    (e.g. a straight double pair alongside a curly single pair in the same string), the result
    is ambiguous and this returns ``None`` rather than guessing.
    """
    if not text:
        return None
    matched_styles = {
        style for style, pattern in _DOUBLE_QUOTE_PATTERNS.items() if pattern.search(text)
    }
    matched_styles.update(
        style for style, pattern in _SINGLE_QUOTE_PATTERNS.items() if pattern.search(text)
    )
    if len(matched_styles) == 1:
        return next(iter(matched_styles))
    return None


# Languages with a strong, low-ambiguity formal convention (i.e. a recognized style authority
# prescribes it, even if software in practice often ignores it for plain "" out of convenience).
# Deliberately not exhaustive -- languages with genuinely mixed/contested real-world conventions
# (e.g. it/pt/nl/zh/ko) are left unset here so they fall back to whatever is actually dominant in
# the catalog (see collect_quote_style_findings), rather than the app asserting a debatable
# "correct" answer. Extend this table, or override per-project via SettingsManager, as needed.
DEFAULT_VALID_QUOTE_STYLE_BY_LANGUAGE: Dict[str, QuoteStyle] = {
    "de": QuoteStyle.LOW_HIGH_9_9,
    "cs": QuoteStyle.LOW_HIGH_9_9,
    "sk": QuoteStyle.LOW_HIGH_9_9,
    "et": QuoteStyle.LOW_HIGH_9_9,
    "fr": QuoteStyle.GUILLEMETS,
    "ru": QuoteStyle.GUILLEMETS,
    "uk": QuoteStyle.GUILLEMETS,
    # Real Academia Espanola: comillas angulares («») are the prescribed primary quotation mark,
    # with "" / '' reserved for quotes nested inside a guillemet-quoted span.
    "es": QuoteStyle.GUILLEMETS,
    "pl": QuoteStyle.LOW_HIGH_9_0,
    "ja": QuoteStyle.CJK_CORNER,
}


def default_valid_quote_style(locale: str) -> Optional[QuoteStyle]:
    """Built-in "correct" quote style for *locale*'s language, or ``None`` if not curated."""
    if not locale:
        return None
    language = locale.replace("-", "_").split("_")[0].lower()
    return DEFAULT_VALID_QUOTE_STYLE_BY_LANGUAGE.get(language)


def compute_dominant_quote_style_by_locale(
    translations: Dict["TranslationKey", "TranslationGroup"],
    locales: Sequence[str],
    default_locale: str,
) -> Dict[str, QuoteStyle]:
    """Scan the whole catalog and return the most-used quote style per non-default locale.

    Locales with no classifiable quoted text anywhere in the catalog are omitted.
    """
    counts: Dict[str, Dict[QuoteStyle, int]] = {}
    for group in translations.values():
        for loc in locales:
            if loc == default_locale:
                continue
            text = group.get_translation(loc)
            if not text or not str(text).strip():
                continue
            style = detect_quote_style(str(text))
            if style is None:
                continue
            locale_counts = counts.setdefault(loc, {})
            locale_counts[style] = locale_counts.get(style, 0) + 1

    dominant: Dict[str, QuoteStyle] = {}
    for loc, style_counts in counts.items():
        dominant[loc] = max(style_counts.items(), key=lambda kv: kv[1])[0]
    return dominant
