"""Tests for I18NManager — project type detection, manager creation, and delegation."""

import sys
import types
import tempfile
import unittest
from unittest.mock import MagicMock

# Stub polib before any i18n import so PythonI18NManager can be imported
if "polib" not in sys.modules:
    sys.modules["polib"] = types.ModuleType("polib")
_fake_polib = sys.modules["polib"]
if not hasattr(_fake_polib, "POFile"):
    class _POFile(list):
        metadata = {}
        def save(self, *a, **kw): pass
        def save_as_mofile(self, *a, **kw): pass
    _fake_polib.POFile = _POFile
if not hasattr(_fake_polib, "pofile"):
    _fake_polib.pofile = lambda *a, **kw: _fake_polib.POFile()

from i18n.i18n_manager import I18NManager
from i18n.translation_manager_results import TranslationAction
from utils.globals import ProjectType
from tests.helpers import FakeSettingsManager


class TestI18NManagerTypeDetection(unittest.TestCase):
    def test_uses_saved_project_type_from_settings(self):
        sm = FakeSettingsManager(saved_type="ruby")
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, settings_manager=sm)
            self.assertEqual(mgr._project_type, ProjectType.RUBY)

    def test_invalid_saved_type_falls_through_to_auto_detection(self):
        sm = FakeSettingsManager(saved_type="not_a_valid_type")
        with tempfile.TemporaryDirectory() as tmpdir:
            # Should not raise; falls through to auto-detection/default
            mgr = I18NManager(tmpdir, settings_manager=sm)
            self.assertIsNotNone(mgr._project_type)

    def test_explicit_project_type_skips_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            self.assertEqual(mgr._project_type, ProjectType.RUBY)

    def test_undetectable_directory_defaults_to_python(self):
        sm = FakeSettingsManager(saved_type=None)
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, settings_manager=sm)
            self.assertEqual(mgr._project_type, ProjectType.PYTHON)

    def test_detected_type_saved_to_settings_manager(self):
        sm = FakeSettingsManager(saved_type=None)
        with tempfile.TemporaryDirectory() as tmpdir:
            I18NManager(tmpdir, settings_manager=sm)
            # After detection the type must have been persisted
            self.assertIsNotNone(sm._saved_type)


class TestI18NManagerCreateManager(unittest.TestCase):
    def _make(self, project_type):
        with tempfile.TemporaryDirectory() as tmpdir:
            return I18NManager(tmpdir, project_type=project_type)

    def test_python_project_type_creates_python_manager(self):
        from i18n.python.python_i18n_manager import PythonI18NManager
        self.assertIsInstance(self._make(ProjectType.PYTHON)._manager, PythonI18NManager)

    def test_ruby_project_type_creates_ruby_manager(self):
        from i18n.ruby.ruby_i18n_manager import RubyI18NManager
        self.assertIsInstance(self._make(ProjectType.RUBY)._manager, RubyI18NManager)

    def test_java_project_type_creates_java_manager(self):
        from i18n.java.java_i18n_manager import JavaI18NManager
        self.assertIsInstance(self._make(ProjectType.JAVA)._manager, JavaI18NManager)

    def test_javascript_project_type_creates_javascript_manager(self):
        from i18n.javascript.javascript_i18n_manager import JavaScriptI18NManager
        self.assertIsInstance(self._make(ProjectType.JAVASCRIPT)._manager, JavaScriptI18NManager)

    def test_unsupported_project_type_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises((ValueError, AttributeError)):
                I18NManager(tmpdir, project_type="unsupported")


class TestI18NManagerSetDirectory(unittest.TestCase):
    def test_same_type_delegates_set_directory_to_inner_manager(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = I18NManager(d1, project_type=ProjectType.RUBY)
            inner_before = mgr._manager
            mgr.set_directory(d2)
            # Same project type → manager instance is reused, not recreated
            self.assertIs(mgr._manager, inner_before)
            self.assertEqual(mgr._manager._directory, d2)

    def test_different_type_recreates_inner_manager(self):
        sm = FakeSettingsManager(saved_type=None)
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = I18NManager(d1, settings_manager=sm, project_type=ProjectType.PYTHON)
            inner_before = mgr._manager
            # Switch saved type to Ruby before calling set_directory
            sm._saved_type = "ruby"
            mgr.set_directory(d2)
            self.assertIsNot(mgr._manager, inner_before)
            self.assertEqual(mgr._project_type, ProjectType.RUBY)

    def test_set_directory_updates_directory(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = I18NManager(d1, project_type=ProjectType.RUBY)
            mgr.set_directory(d2)
            self.assertEqual(mgr._directory, d2)


class TestI18NManagerDelegation(unittest.TestCase):
    def test_locales_property_delegates_to_inner_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            mgr._manager.locales = ["en", "fr", "de"]
            self.assertEqual(mgr.locales, ["en", "fr", "de"])

    def test_translations_property_delegates_to_inner_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            mock_translations = {"key": "val"}
            mgr._manager.translations = mock_translations
            self.assertIs(mgr.translations, mock_translations)

    def test_written_locales_property_delegates_to_inner_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            mgr._manager.written_locales = {"en", "fr"}
            self.assertEqual(mgr.written_locales, {"en", "fr"})

    def test_default_locale_property_delegates_to_inner_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            self.assertEqual(mgr.default_locale, mgr._manager.default_locale)

    def test_manage_translations_delegates_to_inner_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            mock_result = MagicMock()
            mgr._manager.manage_translations = MagicMock(return_value=mock_result)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            mgr._manager.manage_translations.assert_called_once_with(
                TranslationAction.CHECK_STATUS, None
            )
            self.assertIs(result, mock_result)

    def test_manage_translations_none_action_becomes_check_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            mgr._manager.manage_translations = MagicMock(return_value=MagicMock())
            mgr.manage_translations(None)
            mgr._manager.manage_translations.assert_called_once_with(
                TranslationAction.CHECK_STATUS, None
            )

    def test_getattr_delegates_unknown_attributes_to_inner_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = I18NManager(tmpdir, project_type=ProjectType.RUBY)
            mgr._manager._custom_attr = "hello"
            self.assertEqual(mgr._custom_attr, "hello")


if __name__ == "__main__":
    unittest.main()
