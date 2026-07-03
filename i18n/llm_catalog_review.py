"""
Batched LLM catalog review with rolling state and a final synthesis pass.

Uses delimiter blocks and separate merge/final prompts to limit drift. Responses are requested in
the application's UI language where possible. CJK rejection in :class:`lib.llm.LLM` is disabled
for these calls because catalog text is multilingual; optional CJK ratio logging uses
:mod:`utils.utils`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, TYPE_CHECKING

from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

from .translation_group import TranslationGroup, TranslationKey
from .translation_quality_review import (
    build_llm_catalog_user_prompt,
    iter_llm_catalog_batches_for_project,
)

if TYPE_CHECKING:
    from lib.llm import LLM
    from utils.settings_manager import SettingsManager

logger = get_logger("llm_catalog_review")

_ = I18N._

# Keep rolling state bounded so prompts stay within context windows.
MAX_ROLLING_SUMMARY_CHARS = 8000
# Always attach system prompts for catalog review (no random drop).
SYSTEM_PROMPT_ALWAYS = 0.0


def response_language_name_for_prompts() -> str:
    """Human-readable language name for LLM instructions (follows app locale)."""
    loc = (I18N.locale or "en").lower().split("_")[0]
    names = {
        "en": "English",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "it": "Italian",
        "pt": "Portuguese",
        "ja": "Japanese",
        "zh": "Chinese",
        "ko": "Korean",
        "ru": "Russian",
        "pl": "Polish",
    }
    return names.get(loc, loc)


def _delimiter_block(tag: str, body: str) -> str:
    return f"<<<BEGIN_{tag}>>>\n{body.rstrip()}\n<<<END_{tag}>>>\n"


@dataclass
class CatalogLlmReviewResult:
    """Outcome of a full batched catalog LLM review."""

    final_report: str
    rolling_summary: str
    batch_findings: List[str] = field(default_factory=list)
    merge_transcripts: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.error_message


def _llm_generate(
    llm: "LLM",
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    timeout: int = 180,
) -> str:
    """Sync LLM call; disables CJK rejection because prompts/responses may be multilingual."""
    result = llm.generate_response(
        user_prompt,
        timeout=timeout,
        system_prompt=system_prompt,
        system_prompt_drop_rate=SYSTEM_PROMPT_ALWAYS,
        cjk_reject_threshold_percentage=None,
    )
    return (result.response or "").strip()


def _maybe_log_script_mismatch(
    text: str,
    response_lang: str,
    on_progress: Optional[Callable[[str], None]],
) -> None:
    """If output is unexpectedly CJK-heavy while instructions asked for Latin script, log once."""
    if not text or not on_progress:
        return
    if response_lang.lower() in ("japanese", "chinese", "korean"):
        return
    ratio = Utils.get_cjk_character_ratio(text)
    if ratio > 0.55 and len(text) > 40:
        on_progress(
            _("(Note: last model output was {pct:.0f}% CJK by character count; verify readability.)").format(
                pct=ratio * 100
            )
        )


def _truncate(s: str, max_chars: int) -> str:
    s = s.strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n… [truncated]"


def _fallback_merge_rolling(previous: str, batch_findings: str) -> str:
    combined = f"{previous}\n\n---\n\n{batch_findings}".strip()
    return _truncate(combined, MAX_ROLLING_SUMMARY_CHARS)


def merge_rolling_summary_with_llm(
    llm: "LLM",
    previous_summary: str,
    batch_findings: str,
    *,
    batch_index: int,
    batch_total: int,
    response_language: str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    """Compress previous rolling notes + new batch findings into the next rolling state."""
    system = _(
        "You consolidate localization review notes. You receive PRIOR_STATE (notes carried from "
        "earlier batches) and NEW_FINDINGS (observations for the current batch only). "
        "Produce UPDATED_STATE: a concise bullet list (max ~800 words) that (1) keeps recurring "
        "issues, terminology gaps, and locale patterns from PRIOR_STATE if still relevant, "
        "(2) adds important new points from NEW_FINDINGS, (3) drops noise. "
        "Stay within the facts given; do not invent entries. "
        "Use the same language as specified in the user message."
    )
    user = "\n".join(
        [
            _("Response language for UPDATED_STATE: {lang}").format(lang=response_language),
            _("Batch progress: {i} / {total}.").format(i=batch_index + 1, total=batch_total),
            _delimiter_block("PRIOR_STATE", previous_summary or _("(none — first batch)")),
            _delimiter_block("NEW_FINDINGS", batch_findings or _("(no findings)")),
            _(
                "Output ONLY the bullet list for UPDATED_STATE, with a short "
                "\"CarryForward:\" line at the end listing source-text/locale pairs to watch in "
                "later batches (or \"none\")."
            ),
        ]
    )
    try:
        out = _llm_generate(llm, user, system_prompt=system, timeout=120)
        if not out:
            if on_progress:
                on_progress(_("Rolling merge returned empty; using local merge fallback."))
            return _fallback_merge_rolling(previous_summary, batch_findings)
        _maybe_log_script_mismatch(out, response_language, on_progress)
        return _truncate(out, MAX_ROLLING_SUMMARY_CHARS)
    except Exception as e:
        logger.warning("Rolling merge LLM failed: %s", e, exc_info=True)
        if on_progress:
            on_progress(_("Rolling merge failed ({err}); using local merge fallback.").format(err=e))
        return _fallback_merge_rolling(previous_summary, batch_findings)


def build_batch_review_user_prompt(
    rolling_summary: str,
    batch_catalog_text: str,
    batch_index: int,
    batch_total: int,
    response_language: str,
) -> str:
    """User message for one catalog batch: rolling context + TSV batch + strict instructions."""
    base = build_llm_catalog_user_prompt(batch_catalog_text, batch_index, batch_total)
    return "\n".join(
        [
            _("You are reviewing a slice of a translation catalog. Reply in {lang}.").format(
                lang=response_language
            ),
            _delimiter_block(
                "ROLLING_NOTES",
                rolling_summary or _("(No prior notes — this is the first batch.)"),
            ),
            _("New data for this batch only:"),
            base,
            _(
                "Rules: (1) Comment only on entries in this batch. (2) Reference the source "
                "text (or a short excerpt of it) and locale. "
                "(3) Flag likely copy-paste of default locale, broken placeholders, or obvious "
                "untranslated fragments when the locale suggests translation. "
                "(4) Note cross-batch themes only if they match ROLLING_NOTES or clearly repeat here."
            ),
        ]
    )


def build_final_summary_user_prompt(
    rolling_summary: str,
    response_language: str,
    batch_count: int,
) -> str:
    """Single closing call to turn rolling state into an executive summary."""
    return "\n".join(
        [
            _("Write the final localization review report in {lang}.").format(
                lang=response_language
            ),
            _("Number of catalog batches reviewed: {n}.").format(n=batch_count),
            _delimiter_block("ACCUMULATED_NOTES", rolling_summary),
            _(
                "Produce: (1) Executive summary, (2) Top issues by severity, "
                "(3) Locale-specific gaps if any, (4) Suggested next checks. "
                "Be concise; do not invent entries not implied by the notes."
            ),
        ]
    )


def run_catalog_llm_review(
    llm: "LLM",
    translations: Dict[TranslationKey, TranslationGroup],
    locales: Sequence[str],
    default_locale: str,
    settings_manager: Optional["SettingsManager"],
    project_path: str,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> CatalogLlmReviewResult:
    """
    Run batch review, updating rolling summary after each batch, then a final synthesis call.

    ``on_progress`` receives human-readable status lines (also translated when called from UI thread).
    """
    response_lang = response_language_name_for_prompts()
    batches = iter_llm_catalog_batches_for_project(
        translations, locales, default_locale, settings_manager, project_path
    )
    if not batches:
        msg = _("No catalog data to send (empty project or batches).")
        return CatalogLlmReviewResult(
            final_report=msg,
            rolling_summary="",
            error_message=None,
        )

    system_batch = _(
        "You are an expert software localization reviewer. Translation data is grouped into "
        "blocks separated by a blank line: every line in a block, including the first, is "
        "LOCALE, TEXT (tab-separated); the first line's locale is the default (source) locale, "
        "which also identifies the entry -- there is no separate key/id column. "
        "A header line may show default_locale=. "
        "You are given ROLLING_NOTES from earlier batches to track trends—do not contradict them "
        "without evidence in the current batch."
    )
    system_final = _(
        "You write clear localization audit reports for developers. Only use information in "
        "ACCUMULATED_NOTES; do not fabricate entries."
    )

    rolling = ""
    batch_findings_list: List[str] = []
    merge_tx: List[str] = []

    n = len(batches)
    for i, batch_text in enumerate(batches):
        if should_cancel and should_cancel():
            return CatalogLlmReviewResult(
                final_report="",
                rolling_summary=rolling,
                batch_findings=batch_findings_list,
                merge_transcripts=merge_tx,
                error_message=_("Cancelled."),
                cancelled=True,
            )
        if on_progress:
            on_progress(_("Batch {i} / {n}: sending to model…").format(i=i + 1, n=n))

        user = build_batch_review_user_prompt(rolling, batch_text, i, n, response_lang)
        try:
            findings = _llm_generate(llm, user, system_prompt=system_batch, timeout=180)
        except Exception as e:
            logger.error("Batch LLM failed: %s", e, exc_info=True)
            return CatalogLlmReviewResult(
                final_report="",
                rolling_summary=rolling,
                batch_findings=batch_findings_list,
                merge_transcripts=merge_tx,
                error_message=_("Batch {idx} failed: {err}").format(idx=i + 1, err=e),
            )

        batch_findings_list.append(findings)
        _maybe_log_script_mismatch(findings, response_lang, on_progress)

        if on_progress:
            on_progress(_("Batch {i} / {n}: merging rolling summary…").format(i=i + 1, n=n))

        rolling = merge_rolling_summary_with_llm(
            llm,
            rolling,
            findings,
            batch_index=i,
            batch_total=n,
            response_language=response_lang,
            on_progress=on_progress,
        )
        merge_tx.append(rolling)

    if should_cancel and should_cancel():
        return CatalogLlmReviewResult(
            final_report="",
            rolling_summary=rolling,
            batch_findings=batch_findings_list,
            merge_transcripts=merge_tx,
            error_message=_("Cancelled before final summary."),
            cancelled=True,
        )

    if on_progress:
        on_progress(_("Generating final summary…"))

    final_user = build_final_summary_user_prompt(rolling, response_lang, n)
    try:
        final_report = _llm_generate(llm, final_user, system_prompt=system_final, timeout=240)
    except Exception as e:
        logger.error("Final summary LLM failed: %s", e, exc_info=True)
        return CatalogLlmReviewResult(
            final_report=_("Final summary failed: {err}\n\nLast rolling notes:\n\n{notes}").format(
                err=e, notes=rolling
            ),
            rolling_summary=rolling,
            batch_findings=batch_findings_list,
            merge_transcripts=merge_tx,
            error_message=str(e),
        )

    if not final_report.strip():
        final_report = _("(Empty final response; see rolling notes below.)\n\n") + rolling

    _maybe_log_script_mismatch(final_report, response_lang, on_progress)

    return CatalogLlmReviewResult(
        final_report=final_report.strip(),
        rolling_summary=rolling,
        batch_findings=batch_findings_list,
        merge_transcripts=merge_tx,
        error_message=None,
    )
