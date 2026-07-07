"""Tests for ui.translation_quality_review_window.TranslationQualityReviewWindow.

Covers the heuristic-findings table shape (columns collapsed onto grouped findings, see
i18n.translation_quality_review._grouped_locale_finding) and a regression for column widths
shifting after filtering: the "Signal" column used to be QHeaderView.ResizeMode.ResizeToContents,
which recomputes width from whatever rows are currently in the model, so filtering to a narrower
set of signal names visibly reflowed every column after it.
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_PYQT6 = True
except Exception:
    QApplication = None
    _HAS_PYQT6 = False

from test_utils import isolated_settings_and_cache_env
from utils.globals import QualityHeuristicKind
from utils.translations import I18N

_ = I18N._


class _FakeI18nManager:
    def __init__(self, translations: dict, default_locale: str = "en"):
        self.translations = translations
        self.default_locale = default_locale


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestTranslationQualityReviewWindow:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_quality_review_window_")
        self._env_ctx.__enter__()

        from ui.translation_quality_review_window import TranslationQualityReviewWindow

        self.window = TranslationQualityReviewWindow(
            parent=None,
            project_path=None,
            settings_manager=None,
            i18n_manager=None,
        )

    def teardown_method(self):
        self.window.deleteLater()
        self._env_ctx.__exit__(None, None, None)

    # -- helpers --------------------------------------------------------------

    def _make_group(self, msgid: str, values: dict):
        from i18n.translation_group import TranslationGroup

        g = TranslationGroup(msgid, is_in_base=True)
        g.default_locale = "en"
        for locale, text in values.items():
            g.add_translation(locale, text)
        return g

    def _findings_from_groups(self, groups: list, locales: list):
        from i18n.translation_quality_review import collect_findings_for_group
        from i18n.invalid_translation_groups import TranslationQualityFindings

        rows = []
        for g in groups:
            rows.extend(collect_findings_for_group(g, "en", locales))
        return TranslationQualityFindings(findings=rows)

    # -- table shape ------------------------------------------------------------

    def test_heuristic_table_has_six_columns(self):
        assert self.window._heuristic_table.columnCount() == 6

    def test_heuristic_table_headers_use_locales_not_locale_and_notes(self):
        # Headers are gettext-translated (see ui/translation_quality_review_window.py's `_ = I18N._`),
        # so compare against the same translation call rather than hardcoded English literals --
        # the active locale in the test environment may not be English.
        table = self.window._heuristic_table
        headers = [
            table.horizontalHeaderItem(i).text() for i in range(table.columnCount())
        ]
        assert headers == [
            _("Key"),
            _("Locales"),
            _("Default locale value"),
            _("Locale value"),
            _("Signal"),
            _("Detail"),
        ]

    # -- grouped-finding rendering ------------------------------------------------

    def test_grouped_latin_in_cjk_finding_renders_one_row_with_locales_listed(self):
        group = self._make_group(
            "shared.term",
            {
                "en": "Enable LoRA",
                "ja": "LoRA を有効にする Extra",
                "ko": "LoRA 활성화 Extra",
                "zh": "启用 LoRA Extra",
            },
        )
        self.window._i18n_manager = _FakeI18nManager({group.key: group})
        qf = self._findings_from_groups([group], ["en", "ja", "ko", "zh"])
        self.window._heuristic_rows = self.window._build_heuristic_rows(qf)
        self.window._apply_heuristic_filters()

        table = self.window._heuristic_table
        assert table.rowCount() == 1
        locales_text = table.item(0, 1).text()
        assert set(locales_text.split(", ")) == {"ja", "ko", "zh"}

    def test_heuristic_row_key_and_locale_uses_first_listed_locale(self):
        group = self._make_group(
            "shared.term",
            {
                "en": "Enable LoRA",
                "ja": "LoRA を有効にする Extra",
                "ko": "LoRA 활성화 Extra",
                "zh": "启用 LoRA Extra",
            },
        )
        self.window._i18n_manager = _FakeI18nManager({group.key: group})
        qf = self._findings_from_groups([group], ["en", "ja", "ko", "zh"])
        self.window._heuristic_rows = self.window._build_heuristic_rows(qf)
        self.window._apply_heuristic_filters()

        key, locale = self.window._heuristic_row_key_and_locale(0)
        assert key is not None
        assert locale == "ja"

    # -- column-width stability across filtering (regression) --------------------

    def test_column_widths_stable_after_filtering_to_a_narrower_signal_set(self):
        latin_group = self._make_group(
            "shared.term",
            {
                "en": "Enable LoRA",
                "ja": "LoRA を有効にする Extra",
                "ko": "LoRA 활성화 Extra",
            },
        )
        stop_char_group = self._make_group(
            "ui.save",
            {
                "en": "Save",
                "de": "Speichern.",
            },
        )
        self.window._i18n_manager = _FakeI18nManager(
            {latin_group.key: latin_group, stop_char_group.key: stop_char_group}
        )
        qf = self._findings_from_groups(
            [latin_group, stop_char_group], ["en", "ja", "ko", "de"]
        )
        self.window._heuristic_rows = self.window._build_heuristic_rows(qf)
        self.window._apply_heuristic_filters()
        signal_names = {r["signal_name"] for r in self.window._heuristic_rows}
        assert len(signal_names) >= 2  # a narrower filtered subset must exist to be meaningful

        table = self.window._heuristic_table
        widths_before = [table.columnWidth(i) for i in range(table.columnCount())]

        # Re-render with only the narrower subset of rows/signal names, simulating what
        # _apply_heuristic_filters does once the user picks a single "Signal" filter value.
        # signal_name is QualityHeuristicKind.get_display_name(), also gettext-translated.
        latin_display_name = QualityHeuristicKind.LATIN_IN_CJK_LOCALE.get_display_name()
        latin_only_rows = [
            r for r in self.window._heuristic_rows if r["signal_name"] == latin_display_name
        ]
        assert latin_only_rows
        assert len(latin_only_rows) < len(self.window._heuristic_rows)
        self.window._render_heuristic_rows(latin_only_rows)

        widths_after = [table.columnWidth(i) for i in range(table.columnCount())]
        # Columns 0-4 are all fixed-width Interactive now (see _build_heuristic_tab); only the
        # trailing Stretch "Detail" column (index 5) is allowed to change size.
        assert widths_before[:5] == widths_after[:5]

    def test_no_finding_ever_sets_a_single_locale_directly(self):
        # All built-in heuristics are group-scoped (see _grouped_locale_finding /
        # _finding_identical_to_default_for_group / _finding_identical_to_nondefault_for_group),
        # so the "Locale" column was removed entirely in favor of "Locales". If a future
        # heuristic reintroduces per-locale findings, this test will fail as a prompt to
        # reconsider whether the column should come back.
        latin_group = self._make_group(
            "shared.term",
            {"en": "Enable LoRA", "ja": "LoRA を有効にする Extra"},
        )
        qf = self._findings_from_groups([latin_group], ["en", "ja"])
        assert qf.findings
        assert all(f.locale == "" for f in qf.findings)


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestCatalogLlmWorkerModelSelection:
    """The catalog-wide "LLM review" tab should use the same per-key/all-locales model
    configured in LLM Settings (a cloud model by default), not lib.llm.LLM's own hardcoded
    single-locale default (deepseek-r1:14b, a local model)."""

    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _make_worker(self, settings_manager):
        from ui.translation_quality_review_window import _CatalogLlmWorker

        return _CatalogLlmWorker(
            translations={},
            locales=["en", "de"],
            default_locale="en",
            settings_manager=settings_manager,
            project_path="C:/tmp/some-project",
        )

    def test_uses_multi_locale_model_from_settings_manager(self):
        class _FakeSettingsManager:
            def get_llm_model_multi_locale(self, project_path):
                assert project_path == "C:/tmp/some-project"
                return "glm-4.7:cloud"

        worker = self._make_worker(_FakeSettingsManager())
        with patch(
            "i18n.llm_catalog_review.run_catalog_llm_review"
        ) as mock_run:
            from i18n.llm_catalog_review import CatalogLlmReviewResult

            mock_run.return_value = CatalogLlmReviewResult(
                final_report="ok", rolling_summary="", error_message=None
            )
            worker.run()

        assert mock_run.called
        llm_arg = mock_run.call_args[0][0]
        assert llm_arg.model_name == "glm-4.7:cloud"

    def test_falls_back_to_default_multi_locale_model_when_no_settings_manager(self):
        from utils.settings_manager import SettingsManager

        worker = self._make_worker(settings_manager=None)
        with patch(
            "i18n.llm_catalog_review.run_catalog_llm_review"
        ) as mock_run:
            from i18n.llm_catalog_review import CatalogLlmReviewResult

            mock_run.return_value = CatalogLlmReviewResult(
                final_report="ok", rolling_summary="", error_message=None
            )
            worker.run()

        llm_arg = mock_run.call_args[0][0]
        assert llm_arg.model_name == SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE


class _InstantFailLlm:
    """Stand-in for lib.llm.LLM that fails immediately with no real network I/O.

    TestLlmCatalogReviewThreading starts a real _CatalogLlmWorker/QThread on purpose (that's the
    thing under test), but originally relied on "no Ollama server is listening on localhost, so
    the connection fails instantly" to keep that real thread short-lived. That assumption doesn't
    hold in every sandbox -- a firewalled/dropped connection can hang for the full multi-minute
    LLM timeout instead of failing instantly, which raced QThread.wait(5000) in teardown against
    isolated_settings_and_cache_env's temp-dir cleanup and could leave a stray
    tests/.tmp_llm_catalog_threading_*/ directory behind (still being written into by the still-
    running background thread when shutil.rmtree ran). Using this fake instead of the real LLM
    class removes the network dependency entirely: the worker thread now fails synchronously,
    with no I/O and no timing assumptions.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    def generate_response(self, *args, **kwargs):
        from lib.llm import LLMResponseException

        raise LLMResponseException("no server in tests")


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestLlmCatalogReviewThreading:
    """Regression tests for two bugs in the LLM review tab's threading:

    1. The Cancel button never became enabled, because _update_settings_dependent_controls()
       (which computes its enabled state from self._llm_thread.isRunning()) was called *before*
       thread.start() in _on_run_llm_analysis, when isRunning() was still False.
    2. closeEvent() blocked the whole app for up to 30s via self._llm_thread.wait(30000) --
       the in-flight LLM HTTP call can't be interrupted mid-request, so this froze the UI on
       close instead of letting the background thread finish/cancel on its own.

    Starts a real worker thread (see _InstantFailLlm for why lib.llm.LLM itself is patched out):
    QThread.isRunning() is documented to become true synchronously as part of start(), before the
    underlying OS thread necessarily runs any code, so this is still exercising real Qt threading
    behavior, just without a real network call underneath it.
    """

    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_llm_catalog_threading_")
        env = self._env_ctx.__enter__()

        # These tests start a real _CatalogLlmWorker/QThread (see class docstring), which -- for
        # any run with translations loaded -- creates a llm_review_output/<timestamp>/ directory
        # via i18n.llm_catalog_review.ReviewResponseLog before the (now fake) LLM call fails.
        # Without this patch that would write real (if empty) directories into the actual repo on
        # every test run instead of the isolated temp dir.
        from i18n import llm_catalog_review

        self._review_log_root_patcher = patch.object(
            llm_catalog_review, "REVIEW_LOG_ROOT", Path(env["root"]) / "llm_review_output"
        )
        self._review_log_root_patcher.start()

        self._llm_class_patcher = patch("lib.llm.LLM", _InstantFailLlm)
        self._llm_class_patcher.start()

        from ui.translation_quality_review_window import TranslationQualityReviewWindow

        self.window = TranslationQualityReviewWindow(
            parent=None,
            project_path="C:/tmp/some-project",
            settings_manager=None,
            i18n_manager=None,
        )

        from i18n.translation_group import TranslationGroup

        group = TranslationGroup("hello", is_in_base=True)
        group.default_locale = "en"
        group.add_translation("en", "Hello")
        group.add_translation("de", "Hallo")

        class _FakeI18nManagerLocal:
            translations = {group.key: group}
            locales = ["en", "de"]
            default_locale = "en"

        self.window._i18n_manager = _FakeI18nManagerLocal()

    def teardown_method(self):
        # Let the background thread actually finish before tearing down, so we don't leak a
        # running QThread across tests.
        if self.window._llm_thread is not None:
            self.window._llm_thread.wait(5000)
        self.window.deleteLater()
        self._llm_class_patcher.stop()
        self._review_log_root_patcher.stop()
        self._env_ctx.__exit__(None, None, None)

    def test_cancel_button_enabled_immediately_after_starting_llm_analysis(self):
        assert not self.window._cancel_llm_btn.isEnabled()
        self.window._on_run_llm_analysis()
        try:
            assert self.window._llm_thread is not None
            assert self.window._llm_thread.isRunning()
            assert self.window._cancel_llm_btn.isEnabled()
        finally:
            if self.window._llm_worker is not None:
                self.window._llm_worker.cancel()

    def test_close_event_does_not_block_while_llm_thread_running(self):
        from PyQt6.QtGui import QCloseEvent

        self.window._on_run_llm_analysis()
        assert self.window._llm_thread is not None
        assert self.window._llm_thread.isRunning()

        start = time.monotonic()
        self.window.closeEvent(QCloseEvent())
        elapsed = time.monotonic() - start

        # The old behavior called self._llm_thread.wait(30000), blocking for up to 30s.
        assert elapsed < 5.0

    def test_close_event_disconnects_window_touching_signals(self):
        from PyQt6.QtGui import QCloseEvent

        self.window._on_run_llm_analysis()
        worker = self.window._llm_worker
        assert worker is not None

        self.window.closeEvent(QCloseEvent())

        # Already disconnected by closeEvent(); disconnecting again must raise, proving the
        # window's slots are no longer attached (so a late 'finished'/'progress' emission after
        # the window is gone can't try to touch a closed widget).
        with pytest.raises((TypeError, RuntimeError)):
            worker.finished.disconnect(self.window._on_llm_finished)
        with pytest.raises((TypeError, RuntimeError)):
            worker.progress.disconnect(self.window._on_llm_progress)

    def test_on_llm_finished_does_not_drop_thread_reference(self):
        """Regression test for a crash ("QThread: Destroyed while thread is still running")
        that aborted the whole process at the end of a real catalog review.

        worker.finished fires the instant worker.run() returns -- *before* the QThread's own
        event loop has processed quit() and actually unwound, so isRunning() can still be True
        at that point. self._llm_thread is the only Python reference to an unparented QThread,
        so nulling it out there raced against Qt's own shutdown: lose the race and PyQt deletes
        a still-running QThread. Cleanup must instead wait for thread.finished, which Qt only
        emits once the thread has genuinely stopped (see _cleanup_llm_thread).

        Deliberately uses plain sentinel objects rather than a real QThread: an earlier version
        of this test started a real background worker/thread and then called _cleanup_llm_thread()
        on it directly. Nothing pumped the Qt event loop, so the thread's queued quit() was never
        actually delivered and the thread was still genuinely running -- calling
        _cleanup_llm_thread() at that point didn't simulate the race, it reproduced the real
        crash, and aborted the whole pytest process (no traceback, just a dead run). The
        assertions below only care about *which method touches which attribute*, so plain
        sentinels are enough and there is no real thread to race against.
        """
        from i18n.llm_catalog_review import CatalogLlmReviewResult

        sentinel_thread = object()
        sentinel_worker = object()
        self.window._llm_thread = sentinel_thread
        self.window._llm_worker = sentinel_worker

        result = CatalogLlmReviewResult(final_report="ok", rolling_summary="", error_message=None)
        self.window._on_llm_finished(result)

        # Simulates the moment worker.finished fires: references must survive this call.
        assert self.window._llm_thread is sentinel_thread
        assert self.window._llm_worker is sentinel_worker

        # Simulates thread.finished actually firing: only now is clearing safe.
        self.window._cleanup_llm_thread()
        assert self.window._llm_thread is None
        assert self.window._llm_worker is None
