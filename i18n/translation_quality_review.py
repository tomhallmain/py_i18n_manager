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
from typing import AbstractSet, Dict, List, Optional, Sequence, TYPE_CHECKING

from utils.utils import Utils

if TYPE_CHECKING:
    from utils.settings_manager import SettingsManager

from .invalid_translation_groups import QualityReviewFinding, TranslationQualityFindings
from .translation_group import TranslationGroup, TranslationKey

SIGN_IDENTICAL_TO_DEFAULT = "identical_to_default"
SIGN_LATIN_IN_CJK_LOCALE = "latin_in_cjk_locale"
SIGN_HIGH_ENGLISH_RATIO = "high_english_ratio"


def collect_findings_for_group(
    group: TranslationGroup, default_locale: str, locales: List[str]
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
        if base and tstrip == base:
            findings.append(
                QualityReviewFinding(
                    key_msgid=mid,
                    key_context=ctx,
                    locale=loc,
                    signal=SIGN_IDENTICAL_TO_DEFAULT,
                    detail="Translation equals default locale text.",
                )
            )
        if Utils.is_cjk_locale(loc) and _has_significant_latin_run(tstrip):
            findings.append(
                QualityReviewFinding(
                    key_msgid=mid,
                    key_context=ctx,
                    locale=loc,
                    signal=SIGN_LATIN_IN_CJK_LOCALE,
                    detail="Latin letter run (4+ chars) inside a CJK locale string.",
                )
            )

    findings.extend(_findings_high_english_ratio_stub(group, default_locale, locales))
    return findings


_LATIN_RUN = re.compile(r"[A-Za-z]{4,}")


def _has_significant_latin_run(text: str) -> bool:
    return bool(_LATIN_RUN.search(text))


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
) -> TranslationQualityFindings:
    """Scan the full in-memory catalog for built-in advisory signals."""
    loc_list = list(locales)
    excluded = set(excluded_msgids)
    rows: List[QualityReviewFinding] = []
    for group in translations.values():
        rows.extend(
            group.collect_quality_review_findings(default_locale, loc_list, excluded)
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
