"""MainWindow user-facing messages go through ``_()``.

Runs under the ``fr`` catalog: under ``en`` an untranslated msgid comes back unchanged, so a
hardcoded English string would compare equal to its ``_()`` form and these tests could not
catch it.
"""

import gettext
import importlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    _HAS_PYQT6 = True
except Exception:
    QApplication = None
    QFileDialog = None
    QMessageBox = None
    _HAS_PYQT6 = False

from i18n.translation_manager_results import TranslationAction
from test_utils import isolated_settings_and_cache_env
from utils.translations import I18N, _

TEST_LOCALE = "fr"

# Every msgid asserted on below; each must differ from its English text under TEST_LOCALE.
ASSERTED_MSGIDS = (
    "Error",
    "Warning",
    "Please select a project first",
    "No translation data available",
    "No project selected",
    "Select Project Directory",
    "Loading project: {path}",
    "Project loaded successfully!",
    "Found {translation_count} translations in {locale_count} locales.",
    "Task completed with warnings or errors:\n\n{details}",
    "Writing translation file for default locale ({locale})...",
    "Default locale translation file written successfully!",
    "Failed to write translation file for default locale ({locale})",
    "Default locale ({locale}) not found in project",
    "Failed to write default locale translation file: {error}",
    "Failed to update base translation files.",
    "Searching for untranslated strings...",
    "No untranslated strings found in UI components.",
    "Potential untranslated strings found:",
    "In {file_path}:",
    "Error finding untranslated strings: {error}",
)


def _as_status_text(text: str) -> str:
    """``text`` as read back from the status pane: ``QTextEdit.toPlainText()`` returns U+00A0
    (no-break space, used in French before ``!`` and ``:``) as a plain space."""
    return text.replace("\xa0", " ")


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestMainWindowMessages:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(
            prefix=".tmp_main_window_messages_",
            base_dir=Path(__file__).parent,
            keep_tmp=False,
        )
        env_paths = self._env_ctx.__enter__()
        self.project_dir = Path(env_paths["root"]) / "project"
        self.project_dir.mkdir()

        # Assign I18N.translate directly: install_locale() would also install ``_`` into builtins.
        self._saved_translate = I18N.translate
        I18N.translate = gettext.translation("base", I18N.localedir, languages=[TEST_LOCALE])

        # app_info_cache is a module-level singleton; reload it so it picks up the isolated path.
        import utils.app_info_cache as app_info_cache_module
        import app as app_module

        importlib.reload(app_info_cache_module)
        self.app_module = app_module
        self.window = app_module.MainWindow()

    def teardown_method(self):
        try:
            self.window.close()
            self.window.deleteLater()
        finally:
            I18N.translate = self._saved_translate
            self._env_ctx.__exit__(None, None, None)

    def _status(self) -> str:
        return self.window.status_text.toPlainText()

    def _with_loaded_project(self):
        self.window.current_project = str(self.project_dir)
        self.window.i18n_manager = MagicMock(translations={"key": object()})
        self.window.locales = ["en", "fr"]

    def test_asserted_msgids_are_translated_in_test_locale(self):
        untranslated = [m for m in ASSERTED_MSGIDS if _(m) == m]
        assert not untranslated, (
            f"Missing {TEST_LOCALE} translations make the tests in this module unable to detect "
            f"hardcoded English: {untranslated}"
        )

    def test_project_load_status_messages(self):
        with patch.object(self.window, "run_translation_task"):
            self.window.handle_project_selection(str(self.project_dir))

        assert _as_status_text(
            _("Loading project: {path}").format(path=str(self.project_dir))
        ) in self._status()

        self.window.handle_translations_ready({"a": object(), "b": object()}, ["en", "fr", "de"])

        status = self._status()
        assert _as_status_text(_("Project loaded successfully!")) in status
        assert _as_status_text(
            _("Found {translation_count} translations in {locale_count} locales.").format(
                translation_count=2, locale_count=3
            )
        ) in status

    def test_no_load_message_after_project_removal(self):
        with patch.object(self.window, "run_translation_task"):
            self.window.handle_project_selection(str(self.project_dir))
        self.window.handle_project_removal(str(self.project_dir))

        assert self.window.project_label.text() == _("No project selected")

        self.window.handle_translations_ready({"a": object()}, ["en"])

        assert _as_status_text(_("Project loaded successfully!")) not in self._status()

    def test_select_project_dialog_title(self):
        with patch.object(QFileDialog, "getExistingDirectory", return_value="") as mock_dialog:
            self.window.select_project()

        assert mock_dialog.call_args.args[1] == _("Select Project Directory")

    def test_run_translation_task_without_project_warns(self):
        self.window.current_project = None
        with patch.object(QMessageBox, "warning") as mock_warning:
            self.window.run_translation_task()

        mock_warning.assert_called_once_with(
            self.window, _("Error"), _("Please select a project first")
        )

    def test_show_outstanding_items_without_data_warns(self):
        self.window.i18n_manager = None
        with patch.object(QMessageBox, "warning") as mock_warning:
            self.window.show_outstanding_items()

        mock_warning.assert_called_once_with(
            self.window, _("Error"), _("No translation data available")
        )

    def test_task_finished_with_errors_warns_with_details(self):
        results = MagicMock(
            action=TranslationAction.CHECK_STATUS,
            action_successful=False,
            error_message="boom",
        )
        with patch.object(self.window, "needs_project_setup", return_value=True), \
                patch.object(self.window, "show_project_setup"), \
                patch.object(QMessageBox, "warning") as mock_warning:
            self.window.handle_task_finished(results)

        mock_warning.assert_called_once_with(
            self.window,
            _("Warning"),
            _("Task completed with warnings or errors:\n\n{details}").format(details="boom"),
        )

    def test_write_default_locale_not_in_project_warns(self):
        self._with_loaded_project()
        with patch.object(
            self.window.settings_manager, "get_project_default_locale", return_value="de"
        ), patch.object(QMessageBox, "warning") as mock_warning:
            self.window.write_default_locale()

        mock_warning.assert_called_once_with(
            self.window,
            _("Error"),
            _("Default locale ({locale}) not found in project").format(locale="de"),
        )

    def test_write_default_locale_success_status(self):
        self._with_loaded_project()
        self.window.i18n_manager.write_locale_po_file.return_value = True
        with patch.object(
            self.window.settings_manager, "get_project_default_locale", return_value="en"
        ):
            self.window.write_default_locale()

        status = self._status()
        assert _as_status_text(
            _("Writing translation file for default locale ({locale})...").format(locale="en")
        ) in status
        assert _as_status_text(_("Default locale translation file written successfully!")) in status

    def test_write_default_locale_write_failure_warns(self):
        self._with_loaded_project()
        self.window.i18n_manager.write_locale_po_file.return_value = False
        with patch.object(
            self.window.settings_manager, "get_project_default_locale", return_value="en"
        ), patch.object(QMessageBox, "warning") as mock_warning:
            self.window.write_default_locale()

        mock_warning.assert_called_once_with(
            self.window,
            _("Error"),
            _("Failed to write translation file for default locale ({locale})").format(locale="en"),
        )

    def test_write_default_locale_exception_shows_critical(self):
        self._with_loaded_project()
        self.window.i18n_manager.write_locale_po_file.side_effect = RuntimeError("disk full")
        with patch.object(
            self.window.settings_manager, "get_project_default_locale", return_value="en"
        ), patch.object(QMessageBox, "critical") as mock_critical:
            self.window.write_default_locale()

        mock_critical.assert_called_once_with(
            self.window,
            _("Error"),
            _("Failed to write default locale translation file: {error}").format(error="disk full"),
        )

    def test_generate_base_file_failure_warns(self):
        self._with_loaded_project()
        self.window.i18n_manager.generate_pot_file.return_value = False
        self.window.i18n_manager.get_last_generate_base_error.return_value = None
        with patch.object(QMessageBox, "warning") as mock_warning:
            self.window.generate_base_file()

        mock_warning.assert_called_once_with(
            self.window, _("Error"), _("Failed to update base translation files.")
        )

    def test_find_untranslated_strings_none_found(self):
        self._with_loaded_project()
        self.window.i18n_manager.find_translatable_strings.return_value = {}
        self.window.find_untranslated_strings()

        status = self._status()
        assert _as_status_text(_("Searching for untranslated strings...")) in status
        assert _as_status_text(_("No untranslated strings found in UI components.")) in status

    def test_find_untranslated_strings_lists_results(self):
        self._with_loaded_project()
        self.window.i18n_manager.find_translatable_strings.return_value = {"ui/a.py": ["Hello"]}
        self.window.find_untranslated_strings()

        status = self._status()
        assert _as_status_text(_("Potential untranslated strings found:")) in status
        assert _as_status_text(_("In {file_path}:").format(file_path="ui/a.py")) in status

    def test_find_untranslated_strings_exception_shows_critical(self):
        self._with_loaded_project()
        self.window.i18n_manager.find_translatable_strings.side_effect = RuntimeError("bad parse")
        with patch.object(QMessageBox, "critical") as mock_critical:
            self.window.find_untranslated_strings()

        mock_critical.assert_called_once_with(
            self.window,
            _("Error"),
            _("Error finding untranslated strings: {error}").format(error="bad parse"),
        )
