"""Tests for i18n.llm_catalog_review.ReviewResponseLog and its wiring into
run_catalog_llm_review -- saving each raw LLM prompt/response to its own markdown file under
llm_review_output/<run timestamp>/ (see REVIEW_LOG_ROOT), since lib.llm.LLM itself only ever
logs a response's *length*, never its content.

See also tests/test_quality_review_window.py, which patches REVIEW_LOG_ROOT for the UI-thread
tests that start a real _CatalogLlmWorker.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from i18n import llm_catalog_review
from i18n.llm_catalog_review import ReviewResponseLog, run_catalog_llm_review
from i18n.translation_group import TranslationGroup
from lib.llm import LLMResult


@pytest.fixture
def review_log_root():
    """Redirects ReviewResponseLog output to a throwaway temp directory instead of the real
    repo's llm_review_output/, and removes it once the test is done -- whether it passed,
    failed, or raised. TemporaryDirectory's own __exit__ (via the `with` block below) runs on
    generator teardown regardless of outcome, so nothing written during the test survives it.
    """
    with tempfile.TemporaryDirectory(prefix="test_llm_review_output_") as tmp:
        root = Path(tmp) / "llm_review_output"
        with patch.object(llm_catalog_review, "REVIEW_LOG_ROOT", root):
            yield root


class _FakeLlm:
    """Stand-in for lib.llm.LLM: returns a fixed response for every call, no network I/O."""

    def __init__(self, response: str = "fake response"):
        self.response = response
        self.calls: list[str] = []

    def generate_response(self, query, timeout=None, context=None, system_prompt=None,
                           system_prompt_drop_rate=None, cjk_reject_threshold_percentage=None):
        self.calls.append(query)
        return LLMResult(
            response=self.response,
            context=None,
            context_provided=False,
            created_at="",
            done=True,
            done_reason="stop",
            total_duration=0,
            load_duration=0,
            prompt_eval_count=0,
            prompt_eval_duration=0,
            eval_count=0,
            eval_duration=0,
        )


def _make_group(msgid: str, values: dict, default_locale: str = "en") -> TranslationGroup:
    g = TranslationGroup(msgid, is_in_base=True)
    g.default_locale = default_locale
    for locale, text in values.items():
        g.add_translation(locale, text)
    return g


def _one_batch_catalog():
    """A catalog small enough to always fit in a single batch."""
    group = _make_group("hello", {"en": "Hello", "de": "Hallo"})
    return {group.key: group}, ["en", "de"], "en"


class TestReviewResponseLog:
    def test_write_creates_a_markdown_file_with_prompt_and_response(self, review_log_root):
        log = ReviewResponseLog()
        assert log.dir is not None
        assert log.dir.parent == review_log_root

        log.write("batch-01-findings", "the prompt text", "the response text")

        files = list(log.dir.iterdir())
        assert len(files) == 1
        assert files[0].name == "01_batch-01-findings.md"
        content = files[0].read_text(encoding="utf-8")
        assert "the prompt text" in content
        assert "the response text" in content

    def test_successive_writes_are_numbered_in_call_order(self, review_log_root):
        log = ReviewResponseLog()
        log.write("first", "p1", "r1")
        log.write("second", "p2", "r2")

        names = sorted(p.name for p in log.dir.iterdir())
        assert names == ["01_first.md", "02_second.md"]

    def test_label_is_slugified_for_the_filename(self, review_log_root):
        log = ReviewResponseLog()
        log.write("Batch 1 / Findings!!", "p", "r")

        names = [p.name for p in log.dir.iterdir()]
        assert names == ["01_batch-1-findings.md"]


class TestRunCatalogLlmReviewResponseLogging:
    def test_real_run_writes_findings_merge_and_final_report_files(self, review_log_root):
        translations, locales, default_locale = _one_batch_catalog()
        llm = _FakeLlm(response="distinctive marker xyz123")

        result = run_catalog_llm_review(
            llm, translations, locales, default_locale,
            settings_manager=None, project_path="",
        )

        assert result.ok
        run_dirs = list(review_log_root.iterdir())
        assert len(run_dirs) == 1
        files = sorted(p.name for p in run_dirs[0].iterdir())
        # One batch -> findings call, one rolling-merge call, then the final-report call.
        assert files == ["01_batch-01-findings.md", "02_batch-01-merge.md", "03_final-report.md"]

        final_report_file = run_dirs[0] / "03_final-report.md"
        assert "distinctive marker xyz123" in final_report_file.read_text(encoding="utf-8")

    def test_log_responses_false_creates_no_directory(self, review_log_root):
        translations, locales, default_locale = _one_batch_catalog()
        llm = _FakeLlm()

        run_catalog_llm_review(
            llm, translations, locales, default_locale,
            settings_manager=None, project_path="",
            log_responses=False,
        )

        assert not review_log_root.exists()

    def test_no_batches_creates_no_directory(self, review_log_root):
        # Empty catalog short-circuits before any LLM call or log directory is created.
        llm = _FakeLlm()

        result = run_catalog_llm_review(
            llm, {}, ["en"], "en",
            settings_manager=None, project_path="",
        )

        assert result.ok
        assert not llm.calls
        assert not review_log_root.exists()
