"""Tests for ui.translation_windows.replace_key_window.ReplaceKeyWindow.

Covers the "Replace existing key" feature: editing the key text (and, for Python, the default-
locale text since the key *is* the source string there) while carrying over per-locale
translations as an editable starting point, with collision detection against the existing
catalog before the caller applies the result.
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


def _make_group(msgid, values, is_in_base=True, context=None):
    from i18n.translation_group import TranslationGroup

    g = TranslationGroup(msgid, is_in_base=is_in_base, context=context)
    for locale, text in values.items():
        g.add_translation(locale, text)
    return g


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestReplaceKeyWindow:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_replace_key_window_")
        self._env_ctx.__enter__()

    def teardown_method(self):
        self._env_ctx.__exit__(None, None, None)

    def _make_window(self, old_key, group, locales, translations):
        from ui.translation_windows.replace_key_window import ReplaceKeyWindow

        return ReplaceKeyWindow(None, None, old_key, group, locales, translations)

    def _col_for_locale(self, window, locale):
        for col in range(1, window.table.columnCount()):
            if window.table.horizontalHeaderItem(col).text() == locale:
                return col
        raise AssertionError(f"locale {locale!r} not found in table header")

    def test_table_prefilled_from_old_key_and_group(self):
        group = _make_group("Hello", {"en": "Hello", "es": "Hola", "fr": "Bonjour"})
        translations = {group.key: group}
        window = self._make_window(group.key, group, ["en", "es", "fr"], translations)
        try:
            assert window.table.rowCount() == 1
            assert window.table.item(0, 0).text() == "Hello"
            es_col = self._col_for_locale(window, "es")
            fr_col = self._col_for_locale(window, "fr")
            assert window.table.item(0, es_col).text() == "Hola"
            assert window.table.item(0, fr_col).text() == "Bonjour"
        finally:
            window.deleteLater()

    def test_replace_emits_new_group_with_edited_key_and_values(self):
        group = _make_group("Hello", {"en": "Hello", "es": "Hola"})
        translations = {group.key: group}
        window = self._make_window(group.key, group, ["en", "es"], translations)
        try:
            window.table.item(0, 0).setText("Hello there")
            es_col = self._col_for_locale(window, "es")
            window.table.item(0, es_col).setText("Hola ahi")

            received = []
            window.key_replaced.connect(lambda old, new: received.append((old, new)))

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window._on_replace_clicked()

            assert len(received) == 1
            old_key, new_group = received[0]
            assert old_key == group.key
            assert new_group.key.msgid == "Hello there"
            assert new_group.get_translation_as_text("es") == "Hola ahi"
            assert new_group.is_in_base == group.is_in_base
        finally:
            window.deleteLater()

    def test_replace_carries_over_is_in_base_and_metadata(self):
        group = _make_group("Hello", {"en": "Hello"}, is_in_base=False)
        group.usage_comment = "used in views/index"
        group.tcomment = "translator note"
        group.occurrences = [("app/views/index.html", "3")]
        translations = {group.key: group}
        window = self._make_window(group.key, group, ["en"], translations)
        try:
            window.table.item(0, 0).setText("Hello again")

            received = []
            window.key_replaced.connect(lambda old, new: received.append((old, new)))

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window._on_replace_clicked()

            _old_key, new_group = received[0]
            assert new_group.is_in_base is False
            assert new_group.usage_comment == "used in views/index"
            assert new_group.tcomment == "translator note"
            assert new_group.occurrences == [("app/views/index.html", "3")]
        finally:
            window.deleteLater()

    def test_declined_confirmation_does_not_emit(self):
        group = _make_group("Hello", {"en": "Hello"})
        translations = {group.key: group}
        window = self._make_window(group.key, group, ["en"], translations)
        try:
            window.table.item(0, 0).setText("Hello there")

            received = []
            window.key_replaced.connect(lambda old, new: received.append((old, new)))

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                window._on_replace_clicked()

            assert received == []
        finally:
            window.deleteLater()

    def test_empty_new_key_is_rejected_without_confirmation(self):
        group = _make_group("Hello", {"en": "Hello"})
        translations = {group.key: group}
        window = self._make_window(group.key, group, ["en"], translations)
        try:
            window.table.item(0, 0).setText("   ")

            received = []
            window.key_replaced.connect(lambda old, new: received.append((old, new)))

            with patch.object(QMessageBox, "warning") as mock_warning, patch.object(
                QMessageBox, "question"
            ) as mock_question:
                window._on_replace_clicked()

            mock_warning.assert_called_once()
            mock_question.assert_not_called()
            assert received == []
        finally:
            window.deleteLater()

    def test_colliding_new_key_is_rejected(self):
        group = _make_group("Hello", {"en": "Hello"})
        other = _make_group("Goodbye", {"en": "Goodbye"})
        translations = {group.key: group, other.key: other}
        window = self._make_window(group.key, group, ["en"], translations)
        try:
            # Renaming "Hello" to the text of an already-existing, different key.
            window.table.item(0, 0).setText("Goodbye")

            received = []
            window.key_replaced.connect(lambda old, new: received.append((old, new)))

            with patch.object(QMessageBox, "warning") as mock_warning, patch.object(
                QMessageBox, "question"
            ) as mock_question:
                window._on_replace_clicked()

            mock_warning.assert_called_once()
            mock_question.assert_not_called()
            assert received == []
        finally:
            window.deleteLater()

    def test_keeping_the_same_key_text_is_not_a_collision(self):
        """Editing only locale values (leaving the key text unchanged) must not trip the
        collision check against the key's own current entry in the catalog."""
        group = _make_group("Hello", {"en": "Hello", "es": ""})
        translations = {group.key: group}
        window = self._make_window(group.key, group, ["en", "es"], translations)
        try:
            es_col = self._col_for_locale(window, "es")
            window.table.item(0, es_col).setText("Hola")
            # Key cell (0, 0) left as "Hello" -- unchanged.

            received = []
            window.key_replaced.connect(lambda old, new: received.append((old, new)))

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window._on_replace_clicked()

            assert len(received) == 1
            old_key, new_group = received[0]
            assert old_key == group.key
            assert new_group.key == group.key
            assert new_group.get_translation_as_text("es") == "Hola"
        finally:
            window.deleteLater()

    def test_context_field_prefilled_and_applied(self):
        group = _make_group("Hello", {"en": "Hello"}, context="greeting")
        translations = {group.key: group}
        window = self._make_window(group.key, group, ["en"], translations)
        try:
            assert window.context_edit.text() == "greeting"

            window.context_edit.setText("farewell")
            window.table.item(0, 0).setText("Goodbye")

            received = []
            window.key_replaced.connect(lambda old, new: received.append((old, new)))

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window._on_replace_clicked()

            _old_key, new_group = received[0]
            assert new_group.key.context == "farewell"
        finally:
            window.deleteLater()
