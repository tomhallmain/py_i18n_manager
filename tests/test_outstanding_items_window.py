"""Tests for ui.translation_windows.outstanding_items.window.OutstandingItemsWindow.

Characterizes behavior carried over unchanged from the pre-extraction
ui/outstanding_items_window.py (see docs/background-llm-outstanding-items-spec.md for the
extraction this window was split out of): load_data's missing/invalid detection and
duplicate-combine flow, save_changes' locale-batched persistence, row deletion,
fill-missing-with-default, and the translate-all button wiring now delegated to
BackgroundTranslationController.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget
    _HAS_PYQT6 = True
except Exception:
    QApplication = None
    QMessageBox = None
    QWidget = None
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
class _OutstandingItemsWindowTestBase:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_outstanding_items_window_")
        self._env_ctx.__enter__()

        from ui.translation_windows.outstanding_items.window import OutstandingItemsWindow

        self.window = OutstandingItemsWindow(parent=None, project_path=None)

    def teardown_method(self):
        self.window.deleteLater()
        self._env_ctx.__exit__(None, None, None)

    def _col_for_locale(self, locale):
        for col in range(1, self.window.table.columnCount()):
            if self.window.table.horizontalHeaderItem(col).text() == locale:
                return col
        raise AssertionError(f"locale {locale!r} not found in table header")


class TestLoadData(_OutstandingItemsWindowTestBase):
    def test_returns_false_and_empty_table_when_nothing_outstanding(self):
        group = _make_group("greeting", {"en": "Hello", "es": "Hola"})
        translations = {group.key: group}

        has_items = self.window.load_data(translations, ["en", "es"])

        assert has_items is False
        assert self.window.table.rowCount() == 0

    def test_populates_one_row_per_outstanding_key(self):
        complete = _make_group("greeting", {"en": "Hello", "es": "Hola"})
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {complete.key: complete, missing.key: missing}

        has_items = self.window.load_data(translations, ["en", "es"])

        assert has_items is True
        assert self.window.table.rowCount() == 1
        assert self.window._get_key_from_row(0) == missing.key

    def test_skips_groups_not_in_base(self):
        orphan = _make_group("orphan", {"en": "Bye", "es": ""}, is_in_base=False)
        translations = {orphan.key: orphan}

        has_items = self.window.load_data(translations, ["en", "es"])

        assert has_items is False

    def test_headers_exclude_the_default_locale_column(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}

        self.window.load_data(translations, ["en", "es"])

        headers = [
            self.window.table.horizontalHeaderItem(i).text()
            for i in range(self.window.table.columnCount())
        ]
        assert headers == ["Translation Key", "es"]

    def test_combine_yes_prefills_outstanding_from_existing_and_resolves_it(self):
        existing = _make_group("existing.key", {"en": "Save", "es": "Guardar"})
        outstanding = _make_group("outstanding.key", {"en": "Save", "es": ""})
        translations = {existing.key: existing, outstanding.key: outstanding}

        with patch(
            "ui.translation_windows.outstanding_items.window.ask_combine_duplicates",
            return_value="yes",
        ), patch.object(QMessageBox, "information") as mock_info:
            has_items = self.window.load_data(translations, ["en", "es"])

        # Prefilling resolved the only outstanding key, so nothing is left to show.
        assert has_items is False
        mock_info.assert_called_once()
        assert outstanding.get_translation("es") == "Guardar"
        assert self.window._prefill.pending_prefill_update_count() == 1

    def test_combine_yes_groups_outstanding_duplicates_into_one_row(self):
        dup1 = _make_group("dup.one", {"en": "Hello", "es": ""})
        dup2 = _make_group("dup.two", {"en": "Hello", "es": ""})
        translations = {dup1.key: dup1, dup2.key: dup2}

        with patch(
            "ui.translation_windows.outstanding_items.window.ask_combine_duplicates",
            return_value="yes",
        ):
            has_items = self.window.load_data(translations, ["en", "es"])

        assert has_items is True
        assert self.window.table.rowCount() == 1
        rep_key = self.window._get_key_from_row(0)
        assert rep_key == dup1.key
        assert self.window._prefill.outstanding_duplicate_groups[rep_key] == [dup1.key, dup2.key]

    def test_combine_cancel_leaves_window_unopened(self):
        dup1 = _make_group("dup.one", {"en": "Hello", "es": ""})
        dup2 = _make_group("dup.two", {"en": "Hello", "es": ""})
        translations = {dup1.key: dup1, dup2.key: dup2}

        with patch(
            "ui.translation_windows.outstanding_items.window.ask_combine_duplicates",
            return_value="cancel",
        ):
            has_items = self.window.load_data(translations, ["en", "es"])

        assert has_items is False

    def test_skip_duplicate_prompt_reuses_last_combine_choice(self):
        dup1 = _make_group("dup.one", {"en": "Hello", "es": ""})
        dup2 = _make_group("dup.two", {"en": "Hello", "es": ""})
        translations = {dup1.key: dup1, dup2.key: dup2}
        self.window._prefill.last_combine_choice = "yes"

        with patch(
            "ui.translation_windows.outstanding_items.window.ask_combine_duplicates"
        ) as mock_ask:
            self.window.load_data(translations, ["en", "es"], skip_duplicate_prompt=True)

        mock_ask.assert_not_called()
        assert self.window.table.rowCount() == 1  # combined per the reused "yes" choice


class TestSaveChanges(_OutstandingItemsWindowTestBase):
    def test_emits_translation_updated_with_edited_cell_value(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")
        self.window.table.item(0, es_col).setText("Adiós")

        received = []
        self.window.translation_updated.connect(lambda locale, changes: received.append((locale, changes)))

        self.window.save_changes()

        assert received == [("es", [(missing.key, "Adiós")])]

    def test_duplicate_group_edit_fans_out_to_every_matched_key(self):
        dup1 = _make_group("dup.one", {"en": "Hello", "es": ""})
        dup2 = _make_group("dup.two", {"en": "Hello", "es": ""})
        translations = {dup1.key: dup1, dup2.key: dup2}
        with patch(
            "ui.translation_windows.outstanding_items.window.ask_combine_duplicates",
            return_value="yes",
        ):
            self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")
        self.window.table.item(0, es_col).setText("Hola")

        received = []
        self.window.translation_updated.connect(lambda locale, changes: received.append((locale, changes)))

        self.window.save_changes()

        assert len(received) == 1
        locale, changes = received[0]
        assert locale == "es"
        assert dict(changes) == {dup1.key: "Hola", dup2.key: "Hola"}

    def test_without_parent_reloads_and_closes_once_all_items_resolved(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")
        self.window.table.item(0, es_col).setText("Adiós")

        def apply_update(locale, changes):
            # Mimics app.py's handle_translation_update, which isn't exercised by this
            # standalone window test: applies the emitted batch back onto the in-memory group.
            for key, value in changes:
                translations[key].add_translation(locale, value)

        self.window.translation_updated.connect(apply_update)

        with patch.object(self.window, "close") as mock_close:
            self.window.save_changes()

        mock_close.assert_called_once()

    def test_without_parent_stays_open_when_items_remain_unresolved(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])
        # No edits made, and nothing applies the (empty) emitted batch back onto the group, so
        # the fallback reload should still find "es" missing.

        with patch.object(self.window, "close") as mock_close:
            self.window.save_changes()

        mock_close.assert_not_called()
        assert self.window.table.rowCount() == 1

    def test_with_parent_always_closes_and_defers_to_parent_batch_processing(self):
        from ui.translation_windows.outstanding_items.window import OutstandingItemsWindow

        class _FakeMainWindow(QWidget):
            def __init__(self):
                super().__init__()
                self.batched_calls = 0

            def process_batched_updates(self):
                self.batched_calls += 1

        parent = _FakeMainWindow()
        window = OutstandingItemsWindow(parent=parent, project_path=None)
        try:
            missing = _make_group("farewell", {"en": "Bye", "es": ""})
            translations = {missing.key: missing}
            window.load_data(translations, ["en", "es"])

            with patch.object(window, "close") as mock_close:
                window.save_changes()

            mock_close.assert_called_once()
        finally:
            window.deleteLater()
            parent.deleteLater()


class TestDeleteTranslationGroup(_OutstandingItemsWindowTestBase):
    def test_confirmed_delete_removes_key_and_emits_signal(self):
        keep = _make_group("keep.me", {"en": "Bye", "es": ""})
        remove = _make_group("remove.me", {"en": "Hi", "es": ""})
        translations = {keep.key: keep, remove.key: remove}
        self.window.load_data(translations, ["en", "es"])
        assert self.window.table.rowCount() == 2
        row_to_delete = next(
            row
            for row in range(self.window.table.rowCount())
            if self.window._get_key_from_row(row) == remove.key
        )

        deleted = []
        self.window.translation_group_deleted.connect(lambda key: deleted.append(key))

        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            self.window.delete_translation_group_for_row(row_to_delete)

        assert deleted == [remove.key]
        assert remove.key not in translations
        assert self.window.table.rowCount() == 1

    def test_declined_confirmation_keeps_key(self):
        only = _make_group("only.one", {"en": "Hi", "es": ""})
        translations = {only.key: only}
        self.window.load_data(translations, ["en", "es"])

        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
            self.window.delete_translation_group_for_row(0)

        assert only.key in translations
        assert self.window.table.rowCount() == 1

    def test_deleting_last_remaining_row_closes_window(self):
        only = _make_group("only.one", {"en": "Hi", "es": ""})
        translations = {only.key: only}
        self.window.load_data(translations, ["en", "es"])

        with patch.object(
            QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes
        ), patch.object(self.window, "close") as mock_close:
            self.window.delete_translation_group_for_row(0)

        mock_close.assert_called_once()


class TestFillRowMissingWithDefaultTranslation(_OutstandingItemsWindowTestBase):
    def test_fills_only_empty_cells_with_default_locale_text(self):
        group = _make_group("greeting", {"en": "Hello", "es": "", "fr": "Bonjour"})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es", "fr"])
        es_col = self._col_for_locale("es")
        fr_col = self._col_for_locale("fr")

        self.window.fill_row_missing_with_default_translation(0)

        assert self.window.table.item(0, es_col).text() == "Hello"
        assert self.window.table.item(0, fr_col).text() == "Bonjour"  # untouched, already filled

    def test_shows_message_when_default_locale_translation_is_itself_empty(self):
        group = _make_group("greeting", {"en": "", "es": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])

        with patch.object(QMessageBox, "information") as mock_info:
            self.window.fill_row_missing_with_default_translation(0)

        mock_info.assert_called_once()


class TestTranslateAllMissingWiring(_OutstandingItemsWindowTestBase):
    """translate_all_missing/_on_translation_finished/_cancel_translation_worker delegate the
    QThread/TranslationWorker lifecycle to BackgroundTranslationController (see
    translation_orchestrator.py); these patch that controller out entirely so no real
    Argos/LLM translation call runs, and only check the window's own wiring/state."""

    def test_shows_info_and_does_nothing_when_nothing_is_missing(self):
        complete = _make_group("greeting", {"en": "Hello", "es": "Hola"})
        translations = {complete.key: complete}
        self.window.load_data(translations, ["en", "es"])

        with patch.object(QMessageBox, "information") as mock_info:
            self.window.translate_all_missing(use_llm=False)

        mock_info.assert_called_once()
        assert self.window.is_translating is False

    def test_confirmed_batch_disables_buttons_and_starts_controller_with_expected_queue(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ) as mock_controller_cls, patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            mock_controller = mock_controller_cls.return_value
            self.window.translate_all_missing(use_llm=False)

        assert self.window.is_translating is True
        assert self.window.translate_all_argos_btn.isEnabled() is False
        assert self.window.translate_all_llm_btn.isEnabled() is False
        mock_controller.start.assert_called_once()
        args, kwargs = mock_controller.start.call_args
        translation_queue = args[1]
        assert translation_queue == [(0, 1, missing.key, "es", "Bye")]
        assert kwargs["use_llm"] is False
        assert kwargs["total"] == 1

    def test_declined_confirmation_does_not_start_a_batch(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ) as mock_controller_cls, patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ):
            self.window.translate_all_missing(use_llm=False)

        mock_controller_cls.assert_not_called()
        assert self.window.is_translating is False
        assert self.window.translate_all_argos_btn.isEnabled() is True

    def test_finishing_reenables_buttons_and_cleans_up_the_controller(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ) as mock_controller_cls, patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            mock_controller = mock_controller_cls.return_value
            self.window.translate_all_missing(use_llm=False)
            self.window._on_translation_finished()

        assert self.window.is_translating is False
        assert self.window.translate_all_argos_btn.isEnabled() is True
        assert self.window.translate_all_llm_btn.isEnabled() is True
        mock_controller.cleanup.assert_called_once()
        assert self.window._translation_controller is None

    def test_cancel_delegates_to_the_controller(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ) as mock_controller_cls, patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            mock_controller = mock_controller_cls.return_value
            self.window.translate_all_missing(use_llm=False)
            self.window._cancel_translation_worker()

        mock_controller.cancel.assert_called_once()
