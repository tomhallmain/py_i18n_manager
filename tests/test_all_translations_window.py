"""Tests for ui.translation_windows.all_translations_window.AllTranslationsWindow.

No broader test suite exists yet for this window; scoped to two specific features rather than
backfilling full coverage: "Replace Key" wiring (open_replace_key_window/_on_key_replaced) and
the msgctxt context filter combo (_populate_context_filter_combo / _context_for_row, and its
integration into filter_table / _apply_status_filter_only).
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
from utils.translations import I18N

_ = I18N._


def _make_group(msgid, values, is_in_base=True, context=None):
    from i18n.translation_group import TranslationGroup

    g = TranslationGroup(msgid, is_in_base=is_in_base, context=context)
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


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestContextFilter:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_all_translations_context_filter_")
        self._env_ctx.__enter__()

        from ui.translation_windows.all_translations_window import AllTranslationsWindow

        self.window = AllTranslationsWindow(parent=None, project_path=None)

    def teardown_method(self):
        self.window.deleteLater()
        self._env_ctx.__exit__(None, None, None)

    def _combo_entries(self):
        combo = self.window.context_filter_combo
        return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]

    def _select_context(self, context_value):
        combo = self.window.context_filter_combo
        for i in range(combo.count()):
            if combo.itemData(i) == context_value:
                combo.setCurrentIndex(i)
                return
        raise AssertionError(f"context {context_value!r} not found in combo: {self._combo_entries()}")

    def _visible_rows(self):
        return [row for row in range(self.window.table.rowCount()) if not self.window.table.isRowHidden(row)]

    def test_combo_lists_all_no_context_and_distinct_contexts(self):
        plain = _make_group("plain.key", {"en": "Plain"})
        greeting = _make_group("hi", {"en": "Hi"}, context="greeting")
        farewell = _make_group("bye", {"en": "Bye"}, context="farewell")
        translations = {plain.key: plain, greeting.key: greeting, farewell.key: farewell}
        self.window.load_data(translations, ["en"])

        entries = self._combo_entries()
        assert entries[0] == (_("All"), None)
        assert (_("(No Context)"), "") in entries
        # Distinct non-empty contexts are sorted.
        contexts_in_order = [data for _text, data in entries if data not in (None, "")]
        assert contexts_in_order == ["farewell", "greeting"]

    def test_no_context_option_omitted_when_catalog_is_uniform(self):
        a = _make_group("a", {"en": "A"})
        b = _make_group("b", {"en": "B"})
        translations = {a.key: a, b.key: b}
        self.window.load_data(translations, ["en"])

        entries = self._combo_entries()
        # Every key lacks context -- "(No Context)" would just duplicate "All".
        assert entries == [(_("All"), None)]

    def test_selecting_a_context_filters_visible_rows_without_search(self):
        greeting = _make_group("hi", {"en": "Hi"}, context="greeting")
        farewell = _make_group("bye", {"en": "Bye"}, context="farewell")
        translations = {greeting.key: greeting, farewell.key: farewell}
        self.window.load_data(translations, ["en"])

        self._select_context("greeting")
        self.window.filter_table()

        visible_keys = {self.window.get_key_from_row(row) for row in self._visible_rows()}
        assert visible_keys == {greeting.key}

    def test_no_context_option_shows_only_context_free_keys(self):
        plain = _make_group("plain.key", {"en": "Plain"})
        greeting = _make_group("hi", {"en": "Hi"}, context="greeting")
        translations = {plain.key: plain, greeting.key: greeting}
        self.window.load_data(translations, ["en"])

        self._select_context("")
        self.window.filter_table()

        visible_keys = {self.window.get_key_from_row(row) for row in self._visible_rows()}
        assert visible_keys == {plain.key}

    def test_context_filter_combines_with_search_text(self):
        """Search text alone matches all three keys (all start with "hi"); the context filter
        must further narrow that down -- exercises filter_table()'s own row loop, not just
        _apply_status_filter_only() (which is all the "no search text" tests below go through,
        since filter_table() delegates to clear_search() when the search box is empty)."""
        greeting_hi = _make_group("hi.formal", {"en": "Hi"}, context="greeting")
        greeting_yo = _make_group("hi.casual", {"en": "Yo"}, context="greeting")
        farewell_hi = _make_group("hi.leaving", {"en": "See ya"}, context="farewell")
        translations = {
            greeting_hi.key: greeting_hi,
            greeting_yo.key: greeting_yo,
            farewell_hi.key: farewell_hi,
        }
        self.window.load_data(translations, ["en"])

        self._select_context("greeting")
        self.window.search_box.setText("hi")
        self.window.filter_table()

        visible_keys = {self.window.get_key_from_row(row) for row in self._visible_rows()}
        assert visible_keys == {greeting_hi.key, greeting_yo.key}

    def test_context_selection_is_preserved_across_reload(self):
        greeting = _make_group("hi", {"en": "Hi"}, context="greeting")
        translations = {greeting.key: greeting}
        self.window.load_data(translations, ["en"])
        self._select_context("greeting")

        # Simulate a refresh (e.g. after Save) with the same context still present.
        self.window.load_data(translations, ["en"])

        assert self.window.context_filter_combo.currentData() == "greeting"

    def test_context_selection_resets_to_all_when_context_no_longer_exists(self):
        greeting = _make_group("hi", {"en": "Hi"}, context="greeting")
        translations = {greeting.key: greeting}
        self.window.load_data(translations, ["en"])
        self._select_context("greeting")

        plain = _make_group("plain.key", {"en": "Plain"})
        translations2 = {plain.key: plain}
        self.window.load_data(translations2, ["en"])

        assert self.window.context_filter_combo.currentData() is None

    def test_navigate_to_translation_key_resets_context_filter(self):
        greeting = _make_group("hi", {"en": "Hi"}, context="greeting")
        plain = _make_group("plain.key", {"en": "Plain"})
        translations = {greeting.key: greeting, plain.key: plain}
        self.window.load_data(translations, ["en"])

        self._select_context("greeting")
        self.window.filter_table()
        assert self.window.table.isRowHidden(self.window._row_for_translation_key(plain.key))

        assert self.window.navigate_to_translation_key(plain.key) is True
        assert self.window.context_filter_combo.currentData() is None
        assert not self.window.table.isRowHidden(self.window._row_for_translation_key(plain.key))
