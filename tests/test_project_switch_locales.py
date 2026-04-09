from pathlib import Path

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

    def get_quality_review_excluded_msgids(self, _project_path: str):
        return []

    def get_quality_review_script_ignore_patterns(self, _project_path: str):
        return []


class TestProjectSwitchLocaleRegression:
    def setup_method(self):
        base = Path(__file__).parent / "assets"
        self.ruby_project = str((base / "mock_ruby_project").resolve())
        self.python_project = str((base / "mock_python_project").resolve())

        self.settings = _FakeSettingsManager()

    def test_switching_from_ruby_to_python_does_not_keep_extra_locales(self):
        manager = I18NManager(self.ruby_project, settings_manager=self.settings)

        ruby_results = manager.manage_translations(TranslationAction.CHECK_STATUS)
        assert ruby_results.action_successful
        assert set(manager.locales) == {"en", "es", "ja"}

        manager.set_directory(self.python_project)
        python_results = manager.manage_translations(TranslationAction.CHECK_STATUS)

        assert python_results.action_successful
        assert set(manager.locales) == {"en", "es"}
        assert "ja" not in manager.locales

        # Guard the user-facing symptom: stale locale should not appear missing.
        missing_locales = {
            locale
            for _, locales in python_results.invalid_groups.missing_locale_groups
            for locale in locales
        }
        assert "ja" not in missing_locales
