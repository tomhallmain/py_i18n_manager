"""Tests that a provider error that shouldn't be retried per-item propagates all the way to a
stopped batch: rate limiting (HTTP 429) and forbidden/subscription-required (HTTP 403) both
raise a subclass of LLMBatchStoppingException.

Covers the chain: LLM raises the exception -> TranslationService re-raises it (instead of
swallowing it like other failures) -> TranslationWorker stops the queue and emits a dedicated
signal instead of continuing to hammer the endpoint with a request that will keep failing the
same way.

lib.translation_service imports lib.argos_translate, which is a PyQt6 QObject, and
ui.translation_windows.outstanding_items.translation_orchestrator is a PyQt6 module, so this
follows the same PyQt6-availability gating as tests/test_ui_smoke.py.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_PYQT6 = True
except Exception:
    QApplication = None
    _HAS_PYQT6 = False

from test_utils import isolated_settings_and_cache_env


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestTranslationServicePropagatesBatchStoppingErrors:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_rate_limit_propagation_")
        self._env_ctx.__enter__()

        from lib.translation_service import TranslationService

        self.service = TranslationService(default_locale="en")

    def teardown_method(self):
        del self.service
        self._env_ctx.__exit__(None, None, None)

    @pytest.mark.parametrize("exc_name", ["LLMRateLimitException", "LLMForbiddenException"])
    def test_translate_with_llm_propagates(self, exc_name):
        import lib.llm as llm_module

        exc_type = getattr(llm_module, exc_name)

        def fake_generate_json_get_value(**kwargs):
            raise exc_type("provider error")

        self.service.llm.generate_json_get_value = fake_generate_json_get_value

        with pytest.raises(exc_type):
            self.service.translate_with_llm("Hello", "es")

    @pytest.mark.parametrize("exc_name", ["LLMRateLimitException", "LLMForbiddenException"])
    def test_translate_dispatcher_propagates_when_using_llm(self, exc_name):
        import lib.llm as llm_module

        exc_type = getattr(llm_module, exc_name)

        def fake_generate_json_get_value(**kwargs):
            raise exc_type("provider error")

        self.service.llm.generate_json_get_value = fake_generate_json_get_value

        with pytest.raises(exc_type):
            self.service.translate("Hello", "es", use_llm=True)

    @pytest.mark.parametrize("exc_name", ["LLMRateLimitException", "LLMForbiddenException"])
    def test_translate_with_llm_multi_locale_propagates(self, exc_name):
        import lib.llm as llm_module

        exc_type = getattr(llm_module, exc_name)

        def fake_generate_json_dict(**kwargs):
            raise exc_type("provider error")

        self.service.llm_multi.generate_json_dict = fake_generate_json_dict

        with pytest.raises(exc_type):
            self.service.translate_with_llm_multi_locale("Hello", ["es", "fr"])

    def test_non_batch_stopping_failures_still_swallowed(self):
        """Regression guard: only rate-limit/forbidden errors should propagate; other failures
        keep the existing best-effort behavior (return empty string/dict, no exception to the
        caller)."""

        def fake_generate_json_get_value(**kwargs):
            raise RuntimeError("some other failure")

        self.service.llm.generate_json_get_value = fake_generate_json_get_value

        assert self.service.translate_with_llm("Hello", "es") == ""


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestTranslationWorkerStopsOnBatchStoppingErrors:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    @pytest.mark.parametrize("exc_name", ["LLMRateLimitException", "LLMForbiddenException"])
    def test_stops_batch_and_emits_signal_without_processing_remaining_queue(self, exc_name):
        import lib.llm as llm_module
        from ui.translation_windows.outstanding_items.translation_orchestrator import TranslationWorker
        from utils.globals import LLMTranslationMode

        exc_type = getattr(llm_module, exc_name)
        calls = []

        class _FakeTranslationService:
            def translate(self, text, target_locale, context=None, use_llm=False):
                calls.append(target_locale)
                if target_locale == "fr":
                    raise exc_type("provider error (fr)")
                return f"[{target_locale}] {text}"

        queue = [
            (0, 1, "key1", "es", "Hello"),
            (0, 2, "key1", "fr", "Hello"),
            (0, 3, "key1", "de", "Hello"),
        ]
        worker = TranslationWorker(
            _FakeTranslationService(), queue, use_llm=True, mode=LLMTranslationMode.PER_LOCALE
        )

        completed_signals = []
        stopped_error_messages = []
        error_messages = []
        finished_count = []

        worker.translation_completed.connect(lambda row, col, text: completed_signals.append((row, col, text)))
        worker.batch_stopped_error.connect(lambda msg: stopped_error_messages.append(msg))
        worker.error.connect(lambda msg: error_messages.append(msg))
        worker.finished.connect(lambda: finished_count.append(1))

        worker.run()

        # "es" succeeded before the error hit on "fr"; "de" was never attempted.
        assert calls == ["es", "fr"]
        assert completed_signals == [(0, 1, "[es] Hello")]
        assert len(stopped_error_messages) == 1
        assert "fr" in stopped_error_messages[0]
        assert error_messages == []  # no duplicate generic-error popup on top of the dedicated one
        assert finished_count == [1]  # worker still finishes cleanly so the UI can react
        assert worker.completed == 1  # the failed item itself isn't counted as completed
        # "de" is still sitting in the queue, untouched - the batch stopped rather than continuing.
        assert worker.queue == [(0, 3, "key1", "de", "Hello")]

    def test_multi_locale_mode_also_stops_on_forbidden(self):
        from lib.llm import LLMForbiddenException
        from ui.translation_windows.outstanding_items.translation_orchestrator import TranslationWorker
        from utils.globals import LLMTranslationMode

        calls = []

        class _FakeTranslationService:
            def translate_with_llm_multi_locale(self, text, target_locales, context=None):
                calls.append(tuple(target_locales))
                raise LLMForbiddenException(
                    "Forbidden by the LLM provider (HTTP 403). this model requires a subscription"
                )

        queue = [
            (0, "key1", "Hello", [(1, "es"), (2, "fr")]),
            (1, "key2", "World", [(1, "es"), (2, "fr")]),
        ]
        worker = TranslationWorker(
            _FakeTranslationService(),
            queue,
            use_llm=True,
            mode=LLMTranslationMode.PER_KEY_ALL_LOCALES,
            total=4,
        )

        stopped_error_messages = []
        worker.batch_stopped_error.connect(lambda msg: stopped_error_messages.append(msg))

        worker.run()

        assert calls == [("es", "fr")]  # second key's request never went out
        assert len(stopped_error_messages) == 1
        assert "subscription" in stopped_error_messages[0]
        # key2 is still sitting in the queue, untouched.
        assert worker.queue == [(1, "key2", "World", [(1, "es"), (2, "fr")])]
