"""Advisory translation quality review: built-in heuristics, custom rules (future), LLM batching.

Built-in signals are collected per :class:`~i18n.translation_group.TranslationGroup` and aggregated
into :class:`~i18n.invalid_translation_groups.TranslationQualityFindings` when
:data:`~i18n.translation_manager_results.TranslationAction.QUALITY_REVIEW` runs.

Per-project settings (see :class:`utils.settings_manager.SettingsManager`): excluded msgids,
custom rules, and LLM catalog token budget per batch.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import AbstractSet, Dict, List, Optional, Sequence, TYPE_CHECKING

from i18n.stop_character_utils import translation_has_stop_inconsistency_vs_source
from utils.globals import QualityHeuristicKind
from utils.logging_setup import get_logger
from utils.utils import Utils

if TYPE_CHECKING:
    from utils.settings_manager import SettingsManager

from .invalid_translation_groups import QualityReviewFinding, TranslationQualityFindings
from .text_scrub import scrub_dynamic_segments
from .translation_group import TranslationGroup, TranslationKey




logger = get_logger("translation_quality_review")
_DEBUG_MIXED_SCRIPT_PROBE = ""
_DEBUG_MIXED_SCRIPT_KEY = ""


def _should_debug_probe(mid: str, text: str) -> bool:
    if (mid or "").strip() != _DEBUG_MIXED_SCRIPT_KEY:
        return False
    hay = (text or "").casefold()
    if _DEBUG_MIXED_SCRIPT_PROBE.casefold() in hay:
        return True
    # Common confusable variant from current debugging examples.
    return "если вы сбросите mfa, еe можно снова настроить".casefold() in hay


def _debug_heuristic_probe(mid: str, loc: str, tstrip: str, latin_ignore_patterns: Sequence[str]) -> None:
    if not _should_debug_probe(mid, tstrip):
        return
    run_hit = _has_significant_latin_run(tstrip, latin_ignore_patterns)
    mixed_hit = _has_mixed_script_latin_leakage(tstrip, latin_ignore_patterns)
    scrubbed = scrub_dynamic_segments(tstrip)
    scrubbed = _apply_latin_ignore_patterns(scrubbed, latin_ignore_patterns)
    logger.warning(
        "[QUALITY-DEBUG] key=%r locale=%r non_latin_locale=%s run_hit=%s mixed_hit=%s ignore_patterns=%r text=%r scrubbed=%r",
        mid,
        loc,
        Utils.is_non_latin_script_locale(loc),
        run_hit,
        mixed_hit,
        list(latin_ignore_patterns),
        tstrip,
        scrubbed,
    )


def collect_findings_for_group(
    group: TranslationGroup,
    default_locale: str,
    locales: List[str],
    latin_ignore_patterns: Sequence[str] = (),
) -> List[QualityReviewFinding]:
    """Return advisory findings for one translation group (built-in heuristics only)."""
    findings: List[QualityReviewFinding] = []
    ctx = group.key.context or ""
    mid = group.key.msgid
    base = (group.get_translation(default_locale) or "").strip()

    for loc in locales:
        if loc == default_locale:
            continue
        text = group.get_translation(loc)
        if not text or not text.strip():
            continue
        tstrip = text.strip()
        # DEBUG PROBE DISABLED (keep helper method for quick future investigations):
        # if _base_language(loc) == "ru":
        #     _debug_heuristic_probe(mid, loc, tstrip, latin_ignore_patterns)
        if Utils.is_non_latin_script_locale(loc):
            if _has_significant_latin_run(tstrip, latin_ignore_patterns):
                h = QualityHeuristicKind.LATIN_IN_CJK_LOCALE
                findings.append(
                    QualityReviewFinding(
                        key_msgid=mid,
                        key_context=ctx,
                        locale=loc,
                        signal=h,
                    )
                )
            if _has_mixed_script_latin_leakage(tstrip, latin_ignore_patterns):
                h = QualityHeuristicKind.LATIN_MIXED_SCRIPT_IN_NON_LATIN_LOCALE
                findings.append(
                    QualityReviewFinding(
                        key_msgid=mid,
                        key_context=ctx,
                        locale=loc,
                        signal=h,
                    )
                )

        if base and translation_has_stop_inconsistency_vs_source(base, tstrip, loc):
            findings.append(
                QualityReviewFinding(
                    key_msgid=mid,
                    key_context=ctx,
                    locale=loc,
                    signal=QualityHeuristicKind.STOP_CHARACTER_INCONSISTENCY,
                )
            )

    default_match = _finding_identical_to_default_for_group(
        group,
        locales,
        default_locale,
        latin_ignore_patterns,
        mid,
        ctx,
    )
    if default_match is not None:
        findings.append(default_match)

    nond = _finding_identical_to_nondefault_for_group(
        group,
        locales,
        default_locale,
        mid,
        ctx,
    )
    if nond is not None:
        findings.append(nond)

    findings.extend(_findings_high_english_ratio_stub(group, default_locale, locales))
    return findings


# Values that may stay identical to the default (or across locales) in any language.
# Extend over time for international scientific/technical terms, brand names, etc.
_GLOBALLY_SHARED_IDENTICAL_VALUES: frozenset[str] = frozenset(
    {
        "celsius",
        "fahrenheit",
        "kelvin",
    }
)

# When default locale is English: loanwords / cognates per target language that may match en.
# See also :data:`_GLOBALLY_SHARED_IDENTICAL_VALUES` for language-agnostic allowances.
_EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE: Dict[str, frozenset[str]] = {
    "de": frozenset(
        {
            "AM/PM",
            "api",
            "April",
            "August",
            "email",
            "e-mail",
            "emoji",
            "global",
            "id",
            "json",
            "info",
            "minute",
            "name",
            "navigation",
            "November",
            "plan",
            "September",
            "signal",
            "status",
            "url",
            "version",
            "xml",
        }
    ),
    "fr": frozenset(
        {
            "absent",
            "action",
            "actions",
            "alliance",
            "alliances",
            "api",
            "avatar",
            "cuisine",
            "date",
            "description",
            "descriptions",
            "document",
            "documentation",
            "documents",
            "e-mail",
            "email",
            "emoji",
            "etc",
            "exclusion",
            "exclusions",
            "format",
            "id",
            "info",
            "json",
            "locale",
            "locales",
            "menu",
            "messages",
            "messsage",
            "minute",
            "minutes",
            "navigation",
            "note",
            "notes",
            "notification",
            "notifications",
            "page",
            "pages",
            "participant",
            "participants",
            "plan",
            "restaurant",
            "restaurants",
            "service",
            "services",
            "signal",
            "status",
            "terrible",
            "total",
            "type",
            "url",
            "version",
            "vote",
            "votes",
            "xml",
        }
    ),
    "es": frozenset(
        {
            "api",
            "email",
            "e-mail",
            "emoji",
            "error",
            "etc",
            "general",
            "global",
            "id",
            "info",
            "json",
            "locales",
            "no",
            "personal",
            "terrible",
            "total",
            "url",
            "xml",
        }
    ),
    "it": frozenset(
        {
            "AM/PM",
            "api",
            "email",
            "e-mail",
            "emoji",
            "id",
            "info",
            "json",
            "no",
            "password",
            "status",
            "url",
            "xml",
        }
    ),
    "pt": frozenset(
        {
            "AM/PM",
            "api",
            "email",
            "e-mail",
            "emoji",
            "id",
            "info",
            "json",
            "no",
        }
    ),
}


def _finding_identical_to_default_for_group(
    group: TranslationGroup,
    locales: List[str],
    default_locale: str,
    latin_ignore_patterns: Sequence[str],
    key_msgid: str,
    key_context: str,
) -> Optional[QualityReviewFinding]:
    """One group-level finding for non-default locales that copy the default locale text."""
    matching: List[str] = []
    base = (group.get_translation(default_locale) or "").strip()
    if not base:
        return None
    for loc in locales:
        if loc == default_locale:
            continue
        text = (group.get_translation(loc) or "").strip()
        if not text:
            continue
        if text == base and not _is_allowed_identical_copy(
            default_locale, loc, text, latin_ignore_patterns
        ):
            matching.append(loc)
    if not matching:
        return None
    return QualityReviewFinding(
        key_msgid=key_msgid,
        key_context=key_context,
        locale="",
        signal=QualityHeuristicKind.IDENTICAL_TO_DEFAULT,
        notes=", ".join(sorted(matching)),
    )


def _finding_identical_to_nondefault_for_group(
    group: TranslationGroup,
    locales: List[str],
    default_locale: str,
    key_msgid: str,
    key_context: str,
) -> Optional[QualityReviewFinding]:
    """One group-level finding when 2+ non-default locales share the same translation text."""
    base = (group.get_translation(default_locale) or "").strip()
    by_text: Dict[str, List[str]] = {}
    for loc in locales:
        if loc == default_locale:
            continue
        text = (group.get_translation(loc) or "").strip()
        if not text:
            continue
        if base and text == base:
            continue
        if _is_globally_shared_identical_value(text):
            continue
        by_text.setdefault(text, []).append(loc)

    clusters = [sorted(locs) for locs in by_text.values() if len(locs) >= 2]
    if not clusters:
        return None

    clusters.sort(key=lambda locs: (-len(locs), locs[0]))
    notes = "; ".join(", ".join(locs) for locs in clusters)
    return QualityReviewFinding(
        key_msgid=key_msgid,
        key_context=key_context,
        locale="",
        signal=QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT,
        notes=notes,
    )


def _base_language(locale: str) -> str:
    if not locale:
        return ""
    return locale.replace("-", "_").split("_", 1)[0].strip().lower()


_UI_LABEL_PAREN_SUFFIX = re.compile(r"\s*\((?=[^)]*[A-Za-z])[^)]*\)")


def _is_globally_shared_identical_value(text: str) -> bool:
    return (text or "").strip().lower() in _GLOBALLY_SHARED_IDENTICAL_VALUES


def _strip_ui_label_parentheticals(text: str) -> str:
    """Remove sort/filter parentheticals such as ``(A-Z)`` after shared-term stripping."""
    return _UI_LABEL_PAREN_SUFFIX.sub("", text).strip()


def _strip_allowed_shared_terms(
    text: str, terms: frozenset[str], *, case_insensitive: bool = True
) -> str:
    scrubbed = text
    flags = re.IGNORECASE if case_insensitive else 0
    for term in sorted(terms, key=len, reverse=True):
        scrubbed = re.sub(rf"\b{re.escape(term)}\b", "", scrubbed, flags=flags)
    return scrubbed


def _is_allowed_identical_copy(
    default_locale: str,
    locale: str,
    text: str,
    latin_ignore_patterns: Sequence[str] = (),
) -> bool:
    """True when copying the default locale text is expected for this locale/value."""
    if _is_globally_shared_identical_value(text):
        return True

    allowed_lang: frozenset[str] = frozenset()
    if _base_language(default_locale) == "en":
        allowed_lang = _EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE.get(
            _base_language(locale), frozenset()
        )

    normalized = (text or "").strip().lower()
    if normalized in allowed_lang:
        return True

    scrubbed = scrub_dynamic_segments(text or "")

    # Allow if user-configured Latin-ignore patterns account for all Latin characters.
    scrubbed_without_patterns = _apply_latin_ignore_patterns(scrubbed, latin_ignore_patterns)
    if not _contains_latin_letter(scrubbed_without_patterns):
        return True

    scrubbed_without_patterns = _strip_allowed_shared_terms(
        scrubbed_without_patterns, _GLOBALLY_SHARED_IDENTICAL_VALUES
    )
    scrubbed_without_patterns = _strip_allowed_shared_terms(
        scrubbed_without_patterns, allowed_lang
    )
    scrubbed_without_patterns = _strip_ui_label_parentheticals(scrubbed_without_patterns)
    return not _contains_latin_letter(scrubbed_without_patterns)


def _is_allowed_identical_to_english_default(
    default_locale: str,
    locale: str,
    text: str,
    latin_ignore_patterns: Sequence[str] = (),
) -> bool:
    """Backward-compatible alias for :func:`_is_allowed_identical_copy`."""
    return _is_allowed_identical_copy(
        default_locale, locale, text, latin_ignore_patterns
    )


def _apply_latin_ignore_patterns(text: str, patterns: Sequence[str]) -> str:
    scrubbed = text
    for pat in patterns:
        p = (pat or "").strip()
        if not p:
            continue
        try:
            scrubbed = re.sub(p, "", scrubbed)
        except re.error:
            # Invalid user regex should not break quality review.
            continue
    return scrubbed


def _is_latin_char(ch: str) -> bool:
    if not ch or not ch.isalpha():
        return False
    return "LATIN" in unicodedata.name(ch, "")


def _contains_latin_letter(text: str) -> bool:
    for ch in text:
        if _is_latin_char(ch):
            return True
    return False


def _contains_non_latin_letter(text: str) -> bool:
    for ch in text:
        if ch.isalpha() and not _is_latin_char(ch):
            return True
    return False


def _has_latin_sequence(text: str, minimum_length: int) -> bool:
    run = 0
    for ch in text:
        if _is_latin_char(ch):
            run += 1
            if run >= minimum_length:
                return True
        else:
            run = 0
    return False


def _is_non_latin_alpha(ch: str) -> bool:
    return ch.isalpha() and not _is_latin_char(ch)


def _has_single_latin_char_embedded_in_non_latin_word(text: str) -> bool:
    """True for typo-like leakage in non-Latin text.

    Matches either:
    - one Latin char directly between non-Latin letters, or
    - a single-letter Latin token (e.g. ``c``), including when separated by spaces/punctuation.
    """
    if len(text) < 1:
        return False

    for i, ch in enumerate(text):
        if not _is_latin_char(ch):
            continue
        left = text[i - 1] if i > 0 else ""
        right = text[i + 1] if i + 1 < len(text) else ""
        # Embedded typo: Latin between non-Latin letters.
        if _is_non_latin_alpha(left) and _is_non_latin_alpha(right):
            return True
        # Boundary typo: single Latin char touching non-Latin on either side.
        if _is_non_latin_alpha(left) or _is_non_latin_alpha(right):
            # Ensure this Latin char is not part of a longer Latin run.
            if not _is_latin_char(left) and not _is_latin_char(right):
                return True
    # Also catch isolated one-letter Latin tokens surrounded by non-Latin or separators.
    for i, ch in enumerate(text):
        if not _is_latin_char(ch):
            continue
        left = text[i - 1] if i > 0 else ""
        right = text[i + 1] if i + 1 < len(text) else ""
        if not _is_latin_char(left) and not _is_latin_char(right):
            return True
    return False


def _has_significant_latin_run(text: str, latin_ignore_patterns: Sequence[str] = ()) -> bool:
    # Ignore placeholder-like segments and markup tags.
    scrubbed = scrub_dynamic_segments(text)
    scrubbed = _apply_latin_ignore_patterns(scrubbed, latin_ignore_patterns)
    # Catch longer Latin runs and short Latin sequences (e.g. "GM", "ee"),
    # including when adjacent to non-Latin letters.
    # after placeholder/tag/pattern scrubbing.
    return _has_latin_sequence(scrubbed, 2)


def _has_mixed_script_latin_leakage(
    text: str, latin_ignore_patterns: Sequence[str] = ()
) -> bool:
    scrubbed = scrub_dynamic_segments(text)
    scrubbed = _apply_latin_ignore_patterns(scrubbed, latin_ignore_patterns)
    if not _contains_latin_letter(scrubbed):
        return False
    return _has_single_latin_char_embedded_in_non_latin_word(scrubbed)


def _findings_high_english_ratio_stub(
    group: TranslationGroup, default_locale: str, locales: List[str]
) -> List[QualityReviewFinding]:
    """Placeholder for English-ratio heuristic (thresholds and tokenization TBD)."""
    _ = (group, default_locale, locales)
    return []


def collect_project_quality_findings(
    translations: Dict[TranslationKey, TranslationGroup],
    locales: Sequence[str],
    default_locale: str,
    excluded_msgids: AbstractSet[str] = frozenset(),
    latin_ignore_patterns: Sequence[str] = (),
) -> TranslationQualityFindings:
    """Scan the full in-memory catalog for built-in advisory signals."""
    loc_list = list(locales)
    excluded = set(excluded_msgids)
    rows: List[QualityReviewFinding] = []
    for group in translations.values():
        rows.extend(
            group.collect_quality_review_findings(
                default_locale,
                loc_list,
                excluded,
                tuple(latin_ignore_patterns),
            )
        )
    return TranslationQualityFindings(findings=rows)


def run_custom_rules(
    translations: Dict[TranslationKey, TranslationGroup],
    locales: Sequence[str],
    default_locale: str,
    rules: Sequence[dict],
    excluded_msgids: AbstractSet[str] = frozenset(),
) -> TranslationQualityFindings:
    """Evaluate user-defined business rules stored per project in settings.

    Rules are typically ``{"name": str, "description": str}``. The evaluation engine is
    extended here over time; excluded msgids are skipped like built-in heuristics.
    """
    _ = (translations, locales, default_locale, rules, excluded_msgids)
    return TranslationQualityFindings(findings=[])


# --- LLM catalog prompts & batching -------------------------------------------

# Default token budget for the catalog TSV slice only (per batch). Kept moderate so the full
# request (system prompt + user wrapper + this slice + model output) fits typical local LLMs
# with 4k–8k context; lower this in settings for stricter hardware.
DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS = 2400


def estimate_llm_tokens(text: str) -> int:
    """Rough token estimate for mixed Latin / CJK / symbols (no external tokenizer).

    Uses conservative weights so batching stays safe on small-context and local models:
    ASCII alphanumerics ~4 chars/token; CJK and kana often ~1 char/token; other Unicode in between.
    Returns at least 1 for non-empty strings.
    """
    if not text:
        return 0
    acc = 0.0
    for ch in text:
        o = ord(ch)
        if o < 128:
            acc += 0.25
        elif (
            0x4E00 <= o <= 0x9FFF
            or 0x3040 <= o <= 0x30FF
            or 0x31F0 <= o <= 0x31FF
            or 0xAC00 <= o <= 0xD7AF
            or 0x1100 <= o <= 0x11FF
        ):
            acc += 1.0
        else:
            acc += 0.5
    return max(1, int(math.ceil(acc)))


LLM_CATALOG_REVIEW_SYSTEM_PROMPT = (
    "You are an expert software localization reviewer. You receive translation data as TSV: "
    "each line is MSGID<TAB>LOCALE<TAB>TEXT. A header line gives default_locale=...\n"
    "Flag suspicious items only when justified: copy of default in non-default locales, "
    "glaring untranslated English in clearly localized contexts, broken placeholders, "
    "or inconsistent terminology. Be concise; reference msgid and locale. "
    "Do not invent keys that are not in the batch."
)


def build_llm_catalog_user_prompt(batch_text: str, batch_index: int, batch_total: int) -> str:
    return (
        f"Review batch {batch_index + 1} of {batch_total}.\n"
        "Each data line is: MSGID\\tLOCALE\\tTEXT\n\n"
        f"{batch_text}"
    )


def format_catalog_tsv_line(msgid: str, locale: str, text: str, max_text_len: int = 480) -> str:
    escaped = (text or "").replace("\n", " ").replace("\t", " ")
    if len(escaped) > max_text_len:
        escaped = escaped[: max_text_len - 3] + "..."
    return f"{msgid}\t{locale}\t{escaped}"


def iter_llm_catalog_batches(
    translations: Dict[TranslationKey, TranslationGroup],
    locales: Sequence[str],
    default_locale: str,
    max_catalog_tokens: Optional[int] = None,
) -> List[str]:
    """Split the catalog into chunks for sequential LLM calls.

    Batching uses :func:`estimate_llm_tokens` on each line (plus the ``default_locale=`` header
    repeated per batch) so long strings and CJK-heavy rows consume more of the budget than short
    Latin rows. ``max_catalog_tokens`` caps the estimated tokens for the header + data lines in
    each batch only; keep room in the real prompt for system text, instructions, and output.

    Args:
        max_catalog_tokens: Token budget per batch for catalog content. If ``None``, uses
            :data:`DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS`. Per-project overrides live in
            :meth:`SettingsManager.get_quality_review_llm_max_catalog_tokens`.
    """
    budget = max_catalog_tokens
    if budget is None:
        budget = DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS
    budget = max(32, int(budget))

    header = f"default_locale={default_locale}\n"
    header_tokens = estimate_llm_tokens(header)

    batches: List[str] = []
    lines: List[str] = []
    current_tokens = 0

    for group in translations.values():
        mid = group.key.msgid
        for loc in locales:
            raw = group.get_translation(loc) or ""
            line = format_catalog_tsv_line(mid, loc, raw) + "\n"
            line_tokens = estimate_llm_tokens(line)

            # Oversized row: flush pending lines, then emit this line alone (still truncated by format_catalog_tsv_line).
            if line_tokens >= budget:
                if lines:
                    batches.append(header + "".join(lines))
                    lines = []
                batches.append(header + line)
                current_tokens = 0
                continue

            if not lines:
                lines = [line]
                current_tokens = header_tokens + line_tokens
                continue

            if current_tokens + line_tokens > budget:
                batches.append(header + "".join(lines))
                lines = [line]
                current_tokens = header_tokens + line_tokens
            else:
                lines.append(line)
                current_tokens += line_tokens

    if lines:
        batches.append(header + "".join(lines))
    return batches


def iter_llm_catalog_batches_for_project(
    translations: Dict[TranslationKey, TranslationGroup],
    locales: Sequence[str],
    default_locale: str,
    settings_manager: Optional["SettingsManager"],
    project_path: str,
) -> List[str]:
    """Build LLM catalog batches using per-project token budget from settings (if available)."""
    max_t = DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS
    if settings_manager and project_path:
        max_t = settings_manager.get_quality_review_llm_max_catalog_tokens(project_path)
    return iter_llm_catalog_batches(
        translations, locales, default_locale, max_catalog_tokens=max_t
    )
