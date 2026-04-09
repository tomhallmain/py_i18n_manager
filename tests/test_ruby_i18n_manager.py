"""Integration tests for RubyI18NManager using real temp YAML fixtures."""

import os
import tempfile
import textwrap
import unittest

from i18n.ruby.ruby_i18n_manager import RubyI18NManager
from i18n.translation_manager_results import TranslationAction
from i18n.translation_group import TranslationKey
from tests.helpers import FakeSettingsManager

_EN_YAML = textwrap.dedent("""\
    en:
      greeting: "Hello"
      farewell: "Goodbye"
      items:
        count: "You have %{count} items"
""")

_FR_YAML = textwrap.dedent("""\
    fr:
      greeting: "Bonjour"
      farewell: "Au revoir"
      items:
        count: "Vous avez %{count} éléments"
""")


def _build_ruby_project(root: str) -> str:
    """Create a minimal Rails-style i18n project and return root."""
    locale_dir = os.path.join(root, "config", "locales")
    for locale, content in [("en", _EN_YAML), ("fr", _FR_YAML)]:
        path = os.path.join(locale_dir, locale)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "app.yml"), "w", encoding="utf-8") as f:
            f.write(content)
    return root


class TestRubyI18NManagerLocaleDirectory(unittest.TestCase):
    def test_detects_config_locales(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "config", "locales"))
            mgr = RubyI18NManager(tmpdir)
            self.assertEqual(mgr._locale_dir, "config/locales")

    def test_detects_root_locales_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locales"))
            mgr = RubyI18NManager(tmpdir)
            self.assertEqual(mgr._locale_dir, "locales")

    def test_detects_root_locale_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locale"))
            mgr = RubyI18NManager(tmpdir)
            self.assertEqual(mgr._locale_dir, "locale")

    def test_defaults_to_config_locales_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = RubyI18NManager(tmpdir)
            self.assertEqual(mgr._locale_dir, "config/locales")


class TestRubyI18NManagerSetDirectory(unittest.TestCase):
    def test_set_directory_resets_translation_state(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = RubyI18NManager(d1)
            mgr.locales = ["en", "fr"]
            mgr.translations[TranslationKey("x")] = object()
            mgr.written_locales = {"en"}
            mgr.set_directory(d2)
            self.assertEqual(mgr.locales, [])
            self.assertEqual(mgr.translations, {})
            self.assertEqual(mgr.written_locales, set())
            self.assertEqual(mgr._directory, d2)


class TestRubyI18NManagerFilePaths(unittest.TestCase):
    def test_get_pot_file_path_returns_locale_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "config", "locales"))
            mgr = RubyI18NManager(tmpdir)
            expected = os.path.join(tmpdir, "config", "locales")
            self.assertEqual(mgr.get_pot_file_path(), expected)

    def test_get_po_file_path_returns_locale_subdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "config", "locales"))
            mgr = RubyI18NManager(tmpdir)
            expected = os.path.join(tmpdir, "config", "locales", "fr")
            self.assertEqual(mgr.get_po_file_path("fr"), expected)


class TestRubyI18NManagerGatherYamlFiles(unittest.TestCase):
    def test_gather_yaml_files_finds_locale_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            files_by_locale = mgr.gather_yaml_files()
            self.assertIn("en", files_by_locale)
            self.assertIn("fr", files_by_locale)

    def test_gather_yaml_files_empty_on_missing_locale_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = RubyI18NManager(tmpdir)
            files_by_locale = mgr.gather_yaml_files()
            self.assertEqual(files_by_locale, {})

    def test_gather_yaml_files_detects_flat_locale_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            locale_dir = os.path.join(tmpdir, "config", "locales")
            os.makedirs(locale_dir)
            with open(os.path.join(locale_dir, "en.yml"), "w") as f:
                f.write("en:\n  hello: Hello\n")
            with open(os.path.join(locale_dir, "fr.yml"), "w") as f:
                f.write("fr:\n  hello: Bonjour\n")
            mgr = RubyI18NManager(tmpdir)
            files_by_locale = mgr.gather_yaml_files()
            self.assertIn("en", files_by_locale)
            self.assertIn("fr", files_by_locale)


class TestRubyI18NManagerParsing(unittest.TestCase):
    def test_parse_yaml_populates_translations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            yaml_files = mgr.gather_yaml_files()
            mgr._parse_yaml_files(yaml_files)
            msgids = [k.msgid for k in mgr.translations]
            self.assertIn("greeting", msgids)
            self.assertIn("farewell", msgids)

    def test_parse_yaml_marks_default_locale_as_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            yaml_files = mgr.gather_yaml_files()
            mgr._parse_yaml_files(yaml_files)
            for group in mgr.translations.values():
                self.assertTrue(group.is_in_base)

    def test_parse_yaml_adds_non_default_locale_translations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            yaml_files = mgr.gather_yaml_files()
            mgr._parse_yaml_files(yaml_files)
            greeting_key = TranslationKey("greeting")
            self.assertIn(greeting_key, mgr.translations)
            self.assertEqual(mgr.translations[greeting_key].get_translation("fr"), "Bonjour")

    def test_parse_yaml_flattens_nested_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            yaml_files = mgr.gather_yaml_files()
            mgr._parse_yaml_files(yaml_files)
            msgids = [k.msgid for k in mgr.translations]
            self.assertIn("items.count", msgids)


class TestRubyI18NManagerManageTranslations(unittest.TestCase):
    def test_check_status_returns_successful_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertTrue(result.action_successful)
            self.assertIsNone(result.error_message)

    def test_check_status_populates_locales(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertIn("en", mgr.locales)
            self.assertIn("fr", mgr.locales)

    def test_check_status_populates_total_strings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertGreater(result.total_strings, 0)

    def test_check_status_on_empty_dir_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = RubyI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertIsNotNone(result)

    def test_write_mo_files_is_noop_for_ruby(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.WRITE_MO_FILES)
            # Rails doesn't use MO files — should succeed with no failures
            self.assertEqual(result.failed_locales, [])

    def test_list_translation_file_paths_returns_yaml_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_ruby_project(tmpdir)
            mgr = RubyI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            paths = mgr.list_translation_file_paths()
            self.assertTrue(any(p.endswith(".yml") for p in paths))


if __name__ == "__main__":
    unittest.main()
