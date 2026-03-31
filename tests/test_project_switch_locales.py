import sys
import types
import unittest
from pathlib import Path

if "polib" not in sys.modules:
    fake_polib = types.ModuleType("polib")

    class _POEntry:
        pass

    class _POFile(list):
        metadata = {}

        def save(self, *args, **kwargs):
            return None

        def save_as_mofile(self, *args, **kwargs):
            return None

    def _pofile(*args, **kwargs):
        return _POFile()

    fake_polib.POEntry = _POEntry
    fake_polib.POFile = _POFile
    fake_polib.pofile = _pofile
    sys.modules["polib"] = fake_polib

from i18n.i18n_manager import I18NManager
from i18n.translation_manager_results import TranslationAction


class _FakeSettingsManager:
    """In-memory settings for deterministic tests without user-side effects."""

    def __init__(self):
        self.project_types = {}

    def get_project_type(self, project_path: str):
        return self.project_types.get(project_path)

    def save_project_type(self, project_path: str, project_type: str):
        self.project_types[project_path] = project_type
        return True

    def get_project_default_locale(self, _project_path: str) -> str:
        return "en"


class TestProjectSwitchLocaleRegression(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).parent / "assets"
        self.ruby_project = str((base / "mock_ruby_project").resolve())
        self.python_project = str((base / "mock_python_project").resolve())

        self.settings = _FakeSettingsManager()

    def test_switching_from_ruby_to_python_does_not_keep_extra_locales(self):
        manager = I18NManager(self.ruby_project, settings_manager=self.settings)

        ruby_results = manager.manage_translations(TranslationAction.CHECK_STATUS)
        self.assertTrue(ruby_results.action_successful)
        self.assertSetEqual(set(manager.locales), {"en", "es", "ja"})

        manager.set_directory(self.python_project)
        python_results = manager.manage_translations(TranslationAction.CHECK_STATUS)

        self.assertTrue(python_results.action_successful)
        self.assertSetEqual(set(manager.locales), {"en", "es"})
        self.assertNotIn("ja", manager.locales)

        # Guard the user-facing symptom: stale locale should not appear missing.
        missing_locales = {
            locale
            for _, locales in python_results.invalid_groups.missing_locale_groups
            for locale in locales
        }
        self.assertNotIn("ja", missing_locales)


if __name__ == "__main__":
    unittest.main()
