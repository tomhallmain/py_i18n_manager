import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    _HAS_PYQT6 = True
except Exception:
    QApplication = None
    QMessageBox = None
    _HAS_PYQT6 = False

from test_utils import isolated_settings_and_cache_env
from utils.settings_manager import SettingsManager


@unittest.skipUnless(_HAS_PYQT6, "PyQt6 not installed in this environment")
class TestUiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._env_ctx = isolated_settings_and_cache_env(
            prefix=".tmp_ui_smoke_",
            base_dir=Path(__file__).parent,
            keep_tmp=False,
        )
        env_paths = self._env_ctx.__enter__()
        self.tmp_root = env_paths["root"]
        self.kept_tmp = env_paths.get("kept_tmp") == "1"
        self.settings_path = env_paths["settings_path"]
        self.app_cache_path = env_paths["app_cache_path"]

    def tearDown(self):
        self._env_ctx.__exit__(None, None, None)
        if self.kept_tmp:
            print(f"[ui-smoke] kept temp test directory: {self.tmp_root}")

    def test_main_window_uses_isolated_settings_and_cache_paths(self):
        import utils.app_info_cache as app_info_cache_module
        import app as app_module

        importlib.reload(app_info_cache_module)
        importlib.reload(app_module)

        window = app_module.MainWindow()
        try:
            self.assertEqual(str(window.settings_manager.settings_file), self.settings_path)
            self.assertEqual(
                app_info_cache_module.AppInfoCache.JSON_LOC,
                self.app_cache_path,
            )
            window.close()
            self.assertTrue(Path(self.app_cache_path).exists())
        finally:
            window.deleteLater()

    def test_exclusions_dialog_restores_defaults_without_user_cache_touch(self):
        from ui.quality_review_exclusions_dialog import QualityReviewExclusionsDialog

        mgr = SettingsManager()
        self.assertEqual(str(mgr.settings_file), self.settings_path)
        project_path = "C:/tmp/ui-smoke-project"
        mgr.save_quality_review_script_ignore_patterns(project_path, [r"(?i)\bSKU\b"])

        dialog = QualityReviewExclusionsDialog(
            project_path=project_path,
            settings_manager=mgr,
            parent=None,
        )
        try:
            with patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                dialog._on_restore_default_patterns()
            loaded = mgr.get_quality_review_script_ignore_patterns(project_path)
            self.assertIn(r"(?i)\bCSV\b", loaded)
            self.assertNotIn(r"(?i)\bSKU\b", loaded)
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
