"""Tests for TranslationService.translate_with_llm_multi_locale (LLMTranslationMode.PER_KEY_ALL_LOCALES).

lib.translation_service imports lib.argos_translate, which is a PyQt6 QObject, so this follows
the same PyQt6-availability gating as tests/test_ui_smoke.py.
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
class TestTranslateWithLlmMultiLocale:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_multi_locale_test_")
        self._env_ctx.__enter__()

        from lib.translation_service import TranslationService

        self.service = TranslationService(default_locale="en")

    def teardown_method(self):
        del self.service
        self._env_ctx.__exit__(None, None, None)

    def _stub_llm_multi(self, result_or_exception):
        def fake_generate_json_dict(**kwargs):
            if isinstance(result_or_exception, Exception):
                raise result_or_exception
            return result_or_exception

        self.service.llm_multi.generate_json_dict = fake_generate_json_dict

    def test_uses_a_separate_llm_instance_from_single_locale_mode(self):
        assert self.service.llm_multi is not self.service.llm

    def test_maps_each_locale_from_response(self):
        self._stub_llm_multi({"es": "Hola", "fr": "Bonjour", "de": "Hallo"})
        result = self.service.translate_with_llm_multi_locale("Hello", ["es", "fr", "de"])
        assert result == {"es": "Hola", "fr": "Bonjour", "de": "Hallo"}

    def test_empty_target_locales_returns_empty_dict_without_calling_llm(self):
        calls = []
        self.service.llm_multi.generate_json_dict = lambda **kwargs: calls.append(kwargs) or {}
        assert self.service.translate_with_llm_multi_locale("Hello", []) == {}
        assert calls == []

    def test_missing_locale_in_response_maps_to_empty_string(self):
        self._stub_llm_multi({"es": "Hola"})
        result = self.service.translate_with_llm_multi_locale("Hello", ["es", "fr"])
        assert result["es"] == "Hola"
        assert result["fr"] == ""

    def test_case_insensitive_locale_key_fallback(self):
        self._stub_llm_multi({"ES": "Hola"})
        result = self.service.translate_with_llm_multi_locale("Hello", ["es"])
        assert result["es"] == "Hola"

    def test_llm_exception_returns_all_empty_without_raising(self):
        self._stub_llm_multi(RuntimeError("boom"))
        result = self.service.translate_with_llm_multi_locale("Hello", ["es", "fr"])
        assert result == {"es": "", "fr": ""}

    def test_none_parsed_response_returns_all_empty(self):
        self._stub_llm_multi(None)
        result = self.service.translate_with_llm_multi_locale("Hello", ["es", "fr"])
        assert result == {"es": "", "fr": ""}

    def test_cjk_heavy_text_rejected_for_non_cjk_locale(self):
        self.service.set_cjk_reject_threshold_percentage(30)
        self._stub_llm_multi({"es": "你好世界你好世界"})
        result = self.service.translate_with_llm_multi_locale("Hello", ["es"])
        assert result["es"] == ""

    def test_cjk_text_kept_for_cjk_target_locale(self):
        self.service.set_cjk_reject_threshold_percentage(30)
        self._stub_llm_multi({"ja": "こんにちは"})
        result = self.service.translate_with_llm_multi_locale("Hello", ["ja"])
        assert result["ja"] == "こんにちは"

    def test_other_locales_in_batch_unaffected_by_one_locale_failing_cjk_filter(self):
        self.service.set_cjk_reject_threshold_percentage(30)
        self._stub_llm_multi({"es": "你好世界你好世界", "fr": "Bonjour"})
        result = self.service.translate_with_llm_multi_locale("Hello", ["es", "fr"])
        assert result["es"] == ""
        assert result["fr"] == "Bonjour"

    def test_prompt_lists_every_target_locale_and_context(self):
        captured = {}

        def fake_generate_json_dict(**kwargs):
            captured["query"] = kwargs.get("query")
            return {"es": "Hola", "fr": "Bonjour"}

        self.service.llm_multi.generate_json_dict = fake_generate_json_dict
        self.service.translate_with_llm_multi_locale("Hello", ["es", "fr"], context="greeting")
        assert "es, fr" in captured["query"]
        assert "greeting" in captured["query"]

    def test_set_llm_model_multi_locale_updates_only_the_multi_locale_client(self):
        original_single = self.service.llm.model_name
        self.service.set_llm_model_multi_locale("gpt-oss:120b-cloud")
        assert self.service.llm_multi.model_name == "gpt-oss:120b-cloud"
        assert self.service.llm.model_name == original_single
