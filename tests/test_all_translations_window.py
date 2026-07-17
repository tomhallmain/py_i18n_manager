"""Tests for the "Replace Key" wiring on ui.translation_windows.all_translations_window.AllTranslationsWindow.

No broader test suite exists yet for this window; scoped to the new
open_replace_key_window/_on_key_replaced feature rather than backfilling full coverage.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    _HAS_PYQT6 = True
except Exception:
    QApplication = None
    QMessageBox = None
    _HAS_PYQT6 = False

from unittest.mock import patch

from test_utils import isolated_settings_and_cache_env


def _make_group(msgid, values, is_in_base=True):
    from i18n.translation_group import TranslationGroup

    g = TranslationGroup(msgid, is_in_base=is_in_base)
    for locale, text in values.items():
        g.add_translation(locale, text)
    return g


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestReplaceKeyWiring:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_all_translations_window_")
        self._env_ctx.__enter__()

        from ui.translation_windows.all_translations_window import AllTranslationsWindow

        self.window = AllTranslationsWindow(parent=None, project_path=None)

    def teardown_method(self):
        self.window.deleteLater()
        self._env_ctx.__exit__(None, None, None)

    def test_open_with_no_selection_shows_info_message(self):
        with patch(
            "ui.translation_windows.all_translations_window.ReplaceKeyWindow"
        ) as mock_dialog_cls, patch.object(QMessageBox, "information") as mock_info:
            self.window.open_replace_key_window()

        mock_info.assert_called_once()
        mock_dialog_cls.assert_not_called()

    def test_open_with_selected_row_constructs_dialog_with_current_context(self):
        group = _make_group("greeting", {"en": "Hello", "es": "Hola"})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])
        self.window.table.setCurrentCell(0, 0)

        with patch(
            "ui.translation_windows.all_translations_window.ReplaceKeyWindow"
        ) as mock_dialog_cls:
            mock_dialog = mock_dialog_cls.return_value
            self.window.open_replace_key_window()

        mock_dialog_cls.assert_called_once_with(
            self.window, self.window.project_path, group.key, group, ["en", "es"], translations
        )
        mock_dialog.key_replaced.connect.assert_called_once_with(self.window._on_key_replaced)
        mock_dialog.show.assert_called_once()

    def test_open_with_explicit_row_ignores_current_selection(self):
        """The context-menu path passes item.row() explicitly rather than relying on
        table.currentRow(), which right-clicking a row doesn't necessarily change."""
        first = _make_group("aaa", {"en": "Hello", "es": "Hola"})
        second = _make_group("bbb", {"en": "Bye", "es": "Adios"})
        translations = {first.key: first, second.key: second}
        self.window.load_data(translations, ["en", "es"])
        self.window.table.setCurrentCell(0, 0)  # selection stays on row 0

        with patch(
            "ui.translation_windows.all_translations_window.ReplaceKeyWindow"
        ) as mock_dialog_cls:
            self.window.open_replace_key_window(row=1)

        args = mock_dialog_cls.call_args[0]
        assert args[2] == second.key

    def test_key_replaced_swaps_keys_and_emits_signals(self):
        from i18n.translation_group import TranslationGroup

        old = _make_group("greeting", {"en": "Hello", "es": "Hola"})
        translations = {old.key: old}
        self.window.load_data(translations, ["en", "es"])

        new_group = TranslationGroup("Hello there", is_in_base=True)
        new_group.add_translation("en", "Hello there")
        new_group.add_translation("es", "Hola alli")

        deleted = []
        updated = []
        self.window.translation_group_deleted.connect(lambda key: deleted.append(key))
        self.window.translation_updated.connect(
            lambda locale, changes: updated.append((locale, changes))
        )

        self.window._on_key_replaced(old.key, new_group)

        assert old.key not in translations
        assert translations[new_group.key] is new_group
        assert deleted == [old.key]
        assert ("es", [(new_group.key, "Hola alli")]) in updated
        assert ("en", [(new_group.key, "Hello there")]) in updated
        assert self.window.table.rowCount() == 1
        assert self.window.get_key_from_row(0) == new_group.key

    def test_key_replaced_with_unchanged_key_does_not_emit_delete(self):
        from i18n.translation_group import TranslationGroup

        old = _make_group("greeting", {"en": "Hello", "es": "Hola"})
        translations = {old.key: old}
        self.window.load_data(translations, ["en", "es"])

        new_group = TranslationGroup("greeting", is_in_base=True)
        new_group.add_translation("en", "Hello")
        new_group.add_translation("es", "Hola de nuevo")

        deleted = []
        self.window.translation_group_deleted.connect(lambda key: deleted.append(key))

        self.window._on_key_replaced(old.key, new_group)

        assert deleted == []
        assert translations[new_group.key] is new_group
        assert translations[new_group.key].get_translation_as_text("es") == "Hola de nuevo"
