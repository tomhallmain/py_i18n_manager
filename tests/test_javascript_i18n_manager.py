"""Integration tests for JavaScriptI18NManager using real temp JSON fixtures."""

import json
import os
import tempfile

from i18n.javascript.javascript_i18n_manager import JavaScriptI18NManager
from i18n.translation_manager_results import TranslationAction
from i18n.translation_group import TranslationKey

_EN_TRANSLATIONS = {
    "greeting": "Hello",
    "farewell": "Goodbye",
    "items": {
        "count": "You have {0} items"
    }
}

_FR_TRANSLATIONS = {
    "greeting": "Bonjour",
    "farewell": "Au revoir",
    "items": {
        "count": "Vous avez {0} éléments"
    }
}


def _build_js_project(root: str) -> str:
    """Create a minimal JavaScript i18n project structure with JSON files."""
    locales_dir = os.path.join(root, "src", "locales")
    os.makedirs(locales_dir)
    for locale, data in [("en", _EN_TRANSLATIONS), ("fr", _FR_TRANSLATIONS)]:
        path = os.path.join(locales_dir, f"{locale}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return root


class TestJavaScriptI18NManagerLocaleDirectory:
    def test_detects_src_locales(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src", "locales"))
            mgr = JavaScriptI18NManager(tmpdir)
            assert "locales" in mgr._locale_dir

    def test_detects_root_locales(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locales"))
            mgr = JavaScriptI18NManager(tmpdir)
            assert mgr._locale_dir == "locales"

    def test_detects_i18n_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "i18n"))
            mgr = JavaScriptI18NManager(tmpdir)
            assert mgr._locale_dir == "i18n"

    def test_defaults_to_src_locales_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = JavaScriptI18NManager(tmpdir)
            assert "locales" in mgr._locale_dir


class TestJavaScriptI18NManagerSetDirectory:
    def test_set_directory_resets_state(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = JavaScriptI18NManager(d1)
            mgr.locales = ["en", "fr"]
            mgr.translations[TranslationKey("x")] = object()
            mgr.set_directory(d2)
            assert mgr.locales == []
            assert mgr.translations == {}
            assert mgr._directory == d2


class TestJavaScriptI18NManagerParsing:
    def test_check_status_loads_translations_from_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            msgids = [k.msgid for k in mgr.translations]
            assert "greeting" in msgids
            assert "farewell" in msgids

    def test_check_status_flattens_nested_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            msgids = [k.msgid for k in mgr.translations]
            assert "items.count" in msgids

    def test_check_status_loads_non_default_locale_translation(self):
        import pytest
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            # Find the greeting key (context is bundle id)
            for key, group in mgr.translations.items():
                if key.msgid == "greeting":
                    assert group.get_translation("fr") == "Bonjour"
                    break
            else:
                pytest.fail("greeting key not found in translations")


class TestJavaScriptI18NManagerManageTranslations:
    def test_check_status_returns_successful_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert result.action_successful
            assert result.error_message is None

    def test_check_status_detects_locales(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert "en" in mgr.locales
            assert "fr" in mgr.locales

    def test_check_status_populates_total_strings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert result.total_strings > 0

    def test_check_status_sets_latest_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert result.latest_translation_file_mtime is not None

    def test_check_status_on_empty_dir_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = JavaScriptI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert result is not None
            assert result.action_successful

    def test_create_mo_files_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.WRITE_MO_FILES)
            assert result.failed_locales == []

    def test_list_translation_file_paths_returns_json_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_js_project(tmpdir)
            mgr = JavaScriptI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            paths = mgr.list_translation_file_paths()
            assert any(p.endswith(".json") for p in paths)
