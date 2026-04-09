"""Integration tests for JavaI18NManager using real temp .properties fixtures."""

import os
import tempfile
import unittest

from i18n.java.java_i18n_manager import JavaI18NManager
from i18n.translation_manager_results import TranslationAction
from i18n.translation_group import TranslationKey
from tests.helpers import FakeSettingsManager

_MESSAGES_EN = """\
# Base translations
greeting=Hello
farewell=Goodbye
items.count=You have {0} items
"""

_MESSAGES_FR = """\
# French translations
greeting=Bonjour
farewell=Au revoir
items.count=Vous avez {0} éléments
"""


def _build_java_project(root: str) -> str:
    """Create a minimal Java ResourceBundle project structure."""
    resources_dir = os.path.join(root, "src", "main", "resources")
    os.makedirs(resources_dir)
    with open(os.path.join(resources_dir, "messages.properties"), "w", encoding="utf-8") as f:
        f.write(_MESSAGES_EN)
    with open(os.path.join(resources_dir, "messages_fr.properties"), "w", encoding="utf-8") as f:
        f.write(_MESSAGES_FR)
    return root


class TestJavaI18NManagerLocaleDirectory(unittest.TestCase):
    def test_detects_src_main_resources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            resources = os.path.join(tmpdir, "src", "main", "resources")
            os.makedirs(resources)
            mgr = JavaI18NManager(tmpdir)
            self.assertIn("src", mgr._locale_dir)
            self.assertIn("resources", mgr._locale_dir)

    def test_detects_resources_at_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "resources"))
            mgr = JavaI18NManager(tmpdir)
            self.assertEqual(mgr._locale_dir, "resources")

    def test_defaults_to_src_main_resources_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = JavaI18NManager(tmpdir)
            self.assertIn("src", mgr._locale_dir)


class TestJavaI18NManagerSetDirectory(unittest.TestCase):
    def test_set_directory_resets_state(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = JavaI18NManager(d1)
            mgr.locales = ["en", "fr"]
            mgr.translations[TranslationKey("x")] = object()
            mgr.set_directory(d2)
            self.assertEqual(mgr.locales, [])
            self.assertEqual(mgr.translations, {})
            self.assertEqual(mgr._directory, d2)


class TestJavaI18NManagerFilePaths(unittest.TestCase):
    def test_get_pot_file_path_returns_default_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            pot = mgr.get_pot_file_path()
            self.assertIn("messages", pot)
            self.assertTrue(pot.endswith(".properties"))

    def test_list_translation_file_paths_returns_properties_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            paths = mgr.list_translation_file_paths()
            self.assertTrue(all(p.endswith(".properties") for p in paths))
            self.assertGreater(len(paths), 0)


class TestJavaI18NManagerParsing(unittest.TestCase):
    def test_parse_properties_file_populates_translations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            resources = os.path.join(tmpdir, "src", "main", "resources")
            mgr._parse_properties_file(
                os.path.join(resources, "messages.properties"),
                locale="en",
                bundle_id="messages",
                is_base=True,
            )
            msgids = [k.msgid for k in mgr.translations]
            self.assertIn("greeting", msgids)
            self.assertIn("farewell", msgids)

    def test_parse_properties_file_marks_is_base_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            resources = os.path.join(tmpdir, "src", "main", "resources")
            mgr._parse_properties_file(
                os.path.join(resources, "messages.properties"),
                locale="en",
                bundle_id="messages",
                is_base=True,
            )
            for group in mgr.translations.values():
                self.assertTrue(group.is_in_base)

    def test_parse_properties_file_loads_translation_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            resources = os.path.join(tmpdir, "src", "main", "resources")
            mgr._parse_properties_file(
                os.path.join(resources, "messages.properties"),
                locale="en",
                bundle_id="messages",
                is_base=True,
            )
            mgr._parse_properties_file(
                os.path.join(resources, "messages_fr.properties"),
                locale="fr",
                bundle_id="messages",
                is_base=False,
            )
            key = TranslationKey("greeting", context="messages")
            self.assertEqual(mgr.translations[key].get_translation("fr"), "Bonjour")


class TestJavaI18NManagerManageTranslations(unittest.TestCase):
    def test_check_status_returns_successful_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertTrue(result.action_successful)
            self.assertIsNone(result.error_message)

    def test_check_status_detects_locales(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertIn("en", mgr.locales)
            self.assertIn("fr", mgr.locales)

    def test_check_status_populates_translations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertGreater(result.total_strings, 0)

    def test_check_status_sets_latest_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertIsNotNone(result.latest_translation_file_mtime)

    def test_check_status_on_empty_dir_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = JavaI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            self.assertIsNotNone(result)
            self.assertTrue(result.action_successful)

    def test_create_mo_files_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_java_project(tmpdir)
            mgr = JavaI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.WRITE_MO_FILES)
            self.assertEqual(result.failed_locales, [])


if __name__ == "__main__":
    unittest.main()
