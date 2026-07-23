"""Tests for ui.translation_windows.outstanding_items.window.OutstandingItemsWindow.

Characterizes behavior carried over unchanged from the pre-extraction
ui/outstanding_items_window.py: load_data's missing/invalid detection and
duplicate-combine flow, save_changes' locale-batched persistence, row deletion,
fill-missing-with-default, and the translate-all button wiring now delegated to
BackgroundTranslationController.
"""

import os
import time

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
from utils.globals import LLMTranslationMode
from utils.translations import I18N

_ = I18N._


def _make_group(msgid, values, is_in_base=True):
    from i18n.translation_group import TranslationGroup

    g = TranslationGroup(msgid, is_in_base=is_in_base)
    for locale, text in values.items():
        g.add_translation(locale, text)
    return g


class _SlowTranslationService:
    """Blocks the worker thread for `delay` seconds -- used by TestCloseEventWithRunningBatch to
    guarantee the QThread is still genuinely running when a test's assertions run, without a
    real network call underneath it."""

    def __init__(self, delay=1.0):
        self.delay = delay
        self.calls = []

    def translate(self, text, target_locale, context=None, use_llm=False):
        self.calls.append((text, target_locale))
        time.sleep(self.delay)
        return f"[{target_locale}] {text}"


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


class TestReplaceKeyWiring(_OutstandingItemsWindowTestBase):
    def test_open_with_no_selection_shows_info_message(self):
        with patch(
            "ui.translation_windows.outstanding_items.window.ReplaceKeyWindow"
        ) as mock_dialog_cls, patch.object(QMessageBox, "information") as mock_info:
            self.window.open_replace_key_window()

        mock_info.assert_called_once()
        mock_dialog_cls.assert_not_called()

    def test_open_with_selected_row_constructs_dialog_with_current_context(self):
        group = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])
        self.window.table.setCurrentCell(0, 0)

        with patch(
            "ui.translation_windows.outstanding_items.window.ReplaceKeyWindow"
        ) as mock_dialog_cls:
            mock_dialog = mock_dialog_cls.return_value
            self.window.open_replace_key_window()

        mock_dialog_cls.assert_called_once_with(
            self.window, self.window.project_path, group.key, group, ["en", "es"], translations
        )
        mock_dialog.key_replaced.connect.assert_called_once_with(self.window._on_key_replaced)
        mock_dialog.show.assert_called_once()

    def test_key_replaced_swaps_keys_and_emits_signals(self):
        from i18n.translation_group import TranslationGroup

        old = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {old.key: old}
        self.window.load_data(translations, ["en", "es"])

        new_group = TranslationGroup("Hello there", is_in_base=True)
        new_group.add_translation("en", "Hello there")
        new_group.add_translation("es", "Hola")

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
        assert ("es", [(new_group.key, "Hola")]) in updated
        assert ("en", [(new_group.key, "Hello there")]) in updated
        # The new key is now fully translated, so it's no longer outstanding.
        assert self.window.table.rowCount() == 0

    def test_key_replaced_removes_all_duplicate_group_siblings(self):
        from i18n.translation_group import TranslationGroup

        rep = _make_group("dup.one", {"en": "Hello", "es": ""})
        sibling = _make_group("dup.two", {"en": "Hello", "es": ""})
        translations = {rep.key: rep, sibling.key: sibling}
        self.window._prefill.outstanding_duplicate_groups[rep.key] = [rep.key, sibling.key]

        new_group = TranslationGroup("Hi", is_in_base=True)
        new_group.add_translation("en", "Hi")
        new_group.add_translation("es", "Hola")

        deleted = []
        self.window.translation_group_deleted.connect(lambda key: deleted.append(key))
        self.window.translations = translations
        self.window.locales = ["en", "es"]

        self.window._on_key_replaced(rep.key, new_group)

        assert rep.key not in translations
        assert sibling.key not in translations
        assert set(deleted) == {rep.key, sibling.key}
        assert translations[new_group.key] is new_group

    def test_key_replaced_with_unchanged_key_does_not_emit_delete(self):
        from i18n.translation_group import TranslationGroup

        old = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {old.key: old}
        self.window.load_data(translations, ["en", "es"])

        # Same msgid/context as old.key -- only the "es" value changes.
        new_group = TranslationGroup("greeting", is_in_base=True)
        new_group.add_translation("en", "Hello")
        new_group.add_translation("es", "Hola")

        deleted = []
        self.window.translation_group_deleted.connect(lambda key: deleted.append(key))

        self.window._on_key_replaced(old.key, new_group)

        assert deleted == []
        assert translations[new_group.key] is new_group

    def test_key_replaced_forces_immediate_persist_when_no_items_remain(self):
        from i18n.translation_group import TranslationGroup
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
            old = _make_group("greeting", {"en": "Hello", "es": ""})
            translations = {old.key: old}
            window.load_data(translations, ["en", "es"])

            new_group = TranslationGroup("Hello there", is_in_base=True)
            new_group.add_translation("en", "Hello there")
            new_group.add_translation("es", "Hola")

            with patch.object(window, "close") as mock_close:
                window._on_key_replaced(old.key, new_group)

            mock_close.assert_called_once()
        finally:
            window.deleteLater()
            parent.deleteLater()


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
        assert self.window.save_btn.isEnabled() is False
        assert self.window._cancel_batch_btn.isEnabled() is True
        mock_controller.start.assert_called_once()
        args, kwargs = mock_controller.start.call_args
        translation_queue = args[1]
        assert translation_queue == [(missing.key, 1, "es", "Bye")]
        assert kwargs["use_llm"] is False
        assert kwargs["total"] == 1
        # row_for_key resolves the key back to its current row rather than a row index baked
        # into the queue itself.
        assert kwargs["row_for_key"](missing.key) == 0
        assert kwargs["row_for_key"]("no-such-key") is None
        # is_stale (per-locale mode here, since use_llm=False): true once the target cell has
        # text, regardless of who/what put it there or when.
        es_col = self._col_for_locale("es")
        assert kwargs["is_stale"](0, es_col) is False
        self.window.table.item(0, es_col).setText("Adiós")
        assert kwargs["is_stale"](0, es_col) is True

    def test_llm_per_key_all_locales_mode_builds_a_per_cell_is_stale(self):
        """Regression test: the PER_KEY_ALL_LOCALES batch used to build `is_stale` as a
        row-level check ("does any locale in this row already have text"), which meant the
        batch's own just-written first locale made every other locale in the same multi-locale
        LLM response look stale and get silently dropped (see the doc's "Superseded: row-level
        granularity" note). `is_stale` must only ever look at the specific (row, col) a result
        targets, in every mode -- not just the per-locale ones -- so this covers the mode the
        per-locale test above doesn't."""
        self.window.settings_manager.save_llm_translation_mode(
            LLMTranslationMode.PER_KEY_ALL_LOCALES, self.window.project_path
        )
        missing = _make_group("greeting", {"en": "Hello", "es": "", "fr": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es", "fr"])
        es_col = self._col_for_locale("es")
        fr_col = self._col_for_locale("fr")

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ) as mock_controller_cls, patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            mock_controller = mock_controller_cls.return_value
            self.window.translate_all_missing(use_llm=True)

        mock_controller.start.assert_called_once()
        _, kwargs = mock_controller.start.call_args
        assert kwargs["mode"] == LLMTranslationMode.PER_KEY_ALL_LOCALES
        is_stale = kwargs["is_stale"]

        # Neither cell has text yet -- nothing is stale.
        assert is_stale(0, es_col) is False
        assert is_stale(0, fr_col) is False

        # Simulate the batch's own single multi-locale response landing "es" first, exactly as
        # BackgroundTranslationController._on_worker_translation_completed writes a result before
        # the next locale from that same response is checked. Only the "es" cell should now read
        # as stale -- "fr", in the same row, from the same still-in-flight response, must not be.
        self.window.table.item(0, es_col).setText("Hola")
        assert is_stale(0, es_col) is True
        assert is_stale(0, fr_col) is False

    def test_llm_per_key_all_locales_mode_never_queues_a_row_with_nothing_missing(self):
        """The row-level gate on the cloud LLM's token cost lives at queue-build time, not in
        is_stale: `translate_all_missing` only turns a row into a queue item -- and so only ever
        fires an LLM request for it -- if it still has at least one missing locale at the moment
        "Translate All (LLM)" is clicked. A row that had a missing locale when the table loaded
        but has since been filled in (manually, or via "Fill Missing in Row") never becomes a
        queue item, so it never costs a cloud LLM call. This is a different mechanism from
        is_stale (which only decides whether to keep a *result* after a request was already
        made) and is unaffected by is_stale's mode -- it applies just as much to PER_LOCALE."""
        filled_after_load = _make_group("greeting", {"en": "Hello", "es": ""})
        still_missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {filled_after_load.key: filled_after_load, still_missing.key: still_missing}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")

        # Simulate the user filling in "greeting"'s only missing cell after the table loaded but
        # before clicking "Translate All (LLM)" -- e.g. typed manually, or "Fill Missing in Row".
        filled_row = self.window._key_to_row[filled_after_load.key]
        self.window.table.item(filled_row, es_col).setText("Hola (manual)")

        self.window.settings_manager.save_llm_translation_mode(
            LLMTranslationMode.PER_KEY_ALL_LOCALES, self.window.project_path
        )

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ) as mock_controller_cls, patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            mock_controller = mock_controller_cls.return_value
            self.window.translate_all_missing(use_llm=True)

        mock_controller.start.assert_called_once()
        args, kwargs = mock_controller.start.call_args
        translation_queue = args[1]
        queued_keys = [key for key, _source_text, _locale_cols in translation_queue]
        # Only "farewell" (still missing "es") got a queue entry -- "greeting" (filled in before
        # the click) never did, so no LLM request is ever made for it.
        assert queued_keys == [still_missing.key]
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
        assert self.window.save_btn.isEnabled() is True

    def test_finishing_reenables_buttons_and_cleans_up_the_controller(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.translate_all_missing(use_llm=False)
            self.window._on_translation_finished()

        assert self.window.is_translating is False
        assert self.window.translate_all_argos_btn.isEnabled() is True
        assert self.window.translate_all_llm_btn.isEnabled() is True
        assert self.window.save_btn.isEnabled() is True
        # The controller cleans up its own QThread/worker once genuinely stopped (see
        # BackgroundTranslationController); the window's job is just to drop its own reference.
        assert self.window._translation_controller is None

    def test_progress_signal_updates_the_inline_status_label(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.translate_all_missing(use_llm=False)
            self.window._on_translation_progress(0, 1, "farewell -> es")
            mid_text = self.window._batch_status_label.text()
            self.window._on_translation_progress(1, 1, "")
            final_text = self.window._batch_status_label.text()

        assert "farewell -> es" in mid_text
        assert "0 / 1" in mid_text
        assert "1 / 1" in final_text
        assert self.window._batch_progress_bar.value() == 100

    def test_cancel_button_confirms_then_delegates_to_the_controller(self):
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
            self.window._on_cancel_batch_clicked()

        mock_controller.cancel.assert_called_once()
        assert self.window._cancel_batch_btn.isEnabled() is False

    def test_cancel_button_declined_confirmation_does_not_cancel(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ) as mock_controller_cls, patch.object(
            QMessageBox, "question"
        ) as mock_question:
            mock_controller = mock_controller_cls.return_value
            mock_question.side_effect = [
                QMessageBox.StandardButton.Yes,  # the initial "Confirm Translation" prompt
                QMessageBox.StandardButton.No,  # declining the cancel confirmation
            ]
            self.window.translate_all_missing(use_llm=False)
            self.window._on_cancel_batch_clicked()

        mock_controller.cancel.assert_not_called()
        assert self.window._cancel_batch_btn.isEnabled() is True

    def test_cancel_translation_worker_delegates_to_the_controller(self):
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

    def test_batch_stopped_error_shows_inline_and_survives_finish(self):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])

        with patch(
            "ui.translation_windows.outstanding_items.window.BackgroundTranslationController"
        ), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.translate_all_missing(use_llm=False)
            self.window._on_translation_batch_stopped_error("rate limited")
            self.window._on_translation_finished()

        assert "rate limited" in self.window._batch_error_label.text()


class TestContextMenuLlmGuard(_OutstandingItemsWindowTestBase):
    """The "Translate with LLM" context menu action must be disabled while a batch is running,
    since it would otherwise call into the same TranslationService/LLM instance concurrently --
    Argos has no such shared in-flight state, so it stays enabled either way."""

    def _build_menu(self, item):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu

        from ui.translation_windows.outstanding_items import context_menus

        captured = {}

        def fake_exec(menu_self, *args, **kwargs):
            captured["menu"] = menu_self
            return None

        with patch.object(QMenu, "exec", fake_exec):
            context_menus._show_context_menu_for_item(self.window, item, QPoint(0, 0))

        return {action.text(): action for action in captured["menu"].actions()}

    def test_translate_with_llm_enabled_when_not_translating(self):
        group = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")
        item = self.window.table.item(0, es_col)

        actions = self._build_menu(item)

        assert actions[_("Translate with LLM")].isEnabled() is True
        assert actions[_("Translate with Argos Translate")].isEnabled() is True

    def test_translate_with_llm_disabled_while_translating(self):
        group = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")
        item = self.window.table.item(0, es_col)

        self.window.is_translating = True
        actions = self._build_menu(item)

        assert actions[_("Translate with LLM")].isEnabled() is False


class TestBackgroundTranslationControllerLifecycle:
    """BackgroundTranslationController's own thread-lifecycle safety, independent of the window.

    Mirrors translation_quality_review_window.py's test_on_llm_finished_does_not_drop_thread_reference:
    a real regression this class guards against is "QThread: Destroyed while thread is still
    running", which aborts the whole process rather than raising a catchable Python exception.
    The fix is gating reference-drops on thread.finished (fires once the QThread has genuinely
    stopped) instead of worker.finished (fires the instant run() returns, before the QThread's
    own event loop has processed quit() and unwound -- isRunning() can still be true then).
    """

    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_cleanup_only_drops_references_when_called_directly_not_via_finished_signal(self):
        """Deliberately uses plain sentinel objects rather than a real QThread/worker -- see
        translation_quality_review_window.py's own version of this test for why: nothing here
        pumps the Qt event loop, so a real thread's queued quit() would never actually be
        delivered, and calling the cleanup method directly on a still-genuinely-running real
        QThread would reproduce the real crash rather than simulate it. The assertions only care
        about which method touches which attribute, so sentinels are enough."""
        from ui.translation_windows.outstanding_items.translation_orchestrator import (
            BackgroundTranslationController,
        )

        controller = BackgroundTranslationController()
        sentinel_thread = object()
        sentinel_worker = object()
        controller.thread = sentinel_thread
        controller.worker = sentinel_worker

        # Simulates the moment worker.finished fires: emitting the controller's own forwarded
        # `finished` (the only thing worker.finished is connected to besides thread.quit/
        # worker.deleteLater, neither of which this test exercises) must not touch these.
        controller.finished.emit()

        assert controller.thread is sentinel_thread
        assert controller.worker is sentinel_worker

        # Simulates thread.finished actually firing: only now is dropping references safe.
        controller._cleanup()

        assert controller.thread is None
        assert controller.worker is None


class TestTranslationResultRouting:
    """BackgroundTranslationController's key-based re-addressing and staleness check.

    Calls ``_on_worker_translation_completed`` directly, as if a worker's ``translation_completed``
    signal had just been delivered, rather than spinning up a real QThread: the decision logic
    (resolve the row, check staleness, emit-or-drop) is plain synchronous Python once a result
    reaches the main thread, so a real thread adds threading-lifecycle risk (see
    TestBackgroundTranslationControllerLifecycle and the class docstring on
    BackgroundTranslationController for a crash that real-thread testing here actually hit) without
    covering anything this simpler approach doesn't. TestCloseEventWithRunningBatch below is where
    real-thread behavior is deliberately exercised, since closeEvent's not-blocking guarantee can't
    be verified any other way.

    Staleness is checked live against the table's *current* text at apply-time -- not against a
    log of past edits -- so a cell that already has text is left alone regardless of who put it
    there or when relative to the batch starting. This is per-cell in every mode, including
    PER_KEY_ALL_LOCALES: results for a row-covering request are still applied one locale at a
    time, so a row-level check would mistake the batch's own just-written earlier locale for a
    conflicting edit and drop the rest of that same response (see
    BackgroundTranslationController.start's docstring)."""

    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_phase2_addressing_")
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

    def _cell_is_stale(self, row, col):
        """Per-locale-mode staleness: only the specific target cell matters."""
        item = self.window.table.item(row, col)
        return bool(item and item.text().strip())

    def _make_controller(self, row_for_key, is_stale):
        from ui.translation_windows.outstanding_items.translation_orchestrator import (
            BackgroundTranslationController,
        )

        controller = BackgroundTranslationController(self.window)
        controller._row_for_key = row_for_key
        controller._is_stale = is_stale
        return controller

    def test_a_result_for_an_already_filled_cell_is_dropped(self):
        group = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")
        row = self.window._key_to_row[group.key]

        # Simulates the cell having been filled (by the user, by "Fill Missing in Row", or
        # anything else) by the time the result comes back -- checked live, not via a log of
        # when/how it happened.
        self.window.table.item(row, es_col).setText("Hola (manual)")

        controller = self._make_controller(
            row_for_key=self.window._key_to_row.get, is_stale=self._cell_is_stale
        )
        received = []
        controller.translation_completed.connect(lambda row, col, text: received.append((row, col, text)))

        controller._on_worker_translation_completed(group.key, es_col, "es", "[es] Hello")

        assert received == []
        assert self.window.table.item(row, es_col).text() == "Hola (manual)"

    def test_a_result_for_a_key_with_no_current_row_is_dropped_without_writing(self):
        group = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")

        # Simulates the key no longer having a row by the time the result comes back (e.g. it
        # was deleted mid-batch, or the duplicate-combine representative changed) -- resolver
        # returns None for every key rather than looking anything up.
        controller = self._make_controller(row_for_key=lambda key: None, is_stale=self._cell_is_stale)
        received = []
        controller.translation_completed.connect(lambda row, col, text: received.append((row, col, text)))

        controller._on_worker_translation_completed(group.key, es_col, "es", "[es] Hello")

        assert received == []
        # The cell was never written to -- still empty, not "[es] Hello".
        assert self.window.table.item(0, es_col).text() == ""

    def test_normal_result_is_emitted_for_the_resolved_row(self):
        group = _make_group("greeting", {"en": "Hello", "es": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es"])
        es_col = self._col_for_locale("es")
        row = self.window._key_to_row[group.key]

        controller = self._make_controller(
            row_for_key=self.window._key_to_row.get, is_stale=self._cell_is_stale
        )
        received = []
        controller.translation_completed.connect(lambda row, col, text: received.append((row, col, text)))

        controller._on_worker_translation_completed(group.key, es_col, "es", "[es] Hello")

        assert received == [(row, es_col, "[es] Hello")]

    def test_per_key_all_locales_mode_only_drops_the_specific_filled_locale(self):
        """A PER_KEY_ALL_LOCALES request covers every missing locale in a row at once, but
        staleness is still checked per cell: if the user (or anything else, including an earlier
        result from this same response) fills in *one* locale before another result for that row
        comes back, only that one locale is dropped -- not the rest of the row."""
        group = _make_group("greeting", {"en": "Hello", "es": "", "fr": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es", "fr"])
        es_col = self._col_for_locale("es")
        fr_col = self._col_for_locale("fr")
        row = self.window._key_to_row[group.key]

        # The user fills in "fr" manually while the (single, row-covering) LLM request for both
        # "es" and "fr" is still in flight.
        self.window.table.item(row, fr_col).setText("Bonjour (manual)")

        controller = self._make_controller(
            row_for_key=self.window._key_to_row.get,
            is_stale=self._cell_is_stale,
        )
        received = []
        controller.translation_completed.connect(lambda row, col, text: received.append((row, col, text)))

        controller._on_worker_translation_completed(group.key, es_col, "es", "[es] Hello")
        controller._on_worker_translation_completed(group.key, fr_col, "fr", "[fr] Hola")

        assert received == [(row, es_col, "[es] Hello")]
        assert self.window.table.item(row, fr_col).text() == "Bonjour (manual)"

    def test_row_fully_filled_probe_answers_true_only_when_every_locale_has_text(self):
        """`_on_row_fully_filled_probe` is the main-thread side of the live row-level pre-check
        TranslationWorker consults (via a BlockingQueuedConnection, so this doesn't call the
        production round-trip -- that would deadlock outside a real QThread, see
        `_check_row_fully_filled`'s docstring) before firing a PER_KEY_ALL_LOCALES cloud LLM
        request. It should answer True only once *every* locale that request would have covered
        already has text -- reusing the same per-cell `is_stale` check as the post-response path,
        just ANDed across the whole row instead of checked one cell at a time."""
        group = _make_group("greeting", {"en": "Hello", "es": "", "fr": ""})
        translations = {group.key: group}
        self.window.load_data(translations, ["en", "es", "fr"])
        es_col = self._col_for_locale("es")
        fr_col = self._col_for_locale("fr")
        row = self.window._key_to_row[group.key]
        locale_cols = [(es_col, "es"), (fr_col, "fr")]

        controller = self._make_controller(
            row_for_key=self.window._key_to_row.get, is_stale=self._cell_is_stale
        )

        # Nothing filled in yet -- the request is still worth making.
        result_box = []
        controller._on_row_fully_filled_probe(group.key, locale_cols, result_box)
        assert result_box == [False]

        # Only "es" filled in (e.g. the user typed it manually) -- "fr" is still missing, so the
        # request (which would also ask for "fr") is still worth making.
        self.window.table.item(row, es_col).setText("Hola (manual)")
        result_box = []
        controller._on_row_fully_filled_probe(group.key, locale_cols, result_box)
        assert result_box == [False]

        # Both filled in now -- nothing left for this request to usefully ask the cloud LLM for.
        self.window.table.item(row, fr_col).setText("Bonjour (manual)")
        result_box = []
        controller._on_row_fully_filled_probe(group.key, locale_cols, result_box)
        assert result_box == [True]

    def test_row_fully_filled_probe_answers_false_when_key_has_no_current_row(self):
        """Mirrors `_on_worker_translation_completed`'s handling of a key with no current row
        (deleted, or no longer the duplicate-combine representative): fail open (don't skip the
        request) rather than guess, since dropping it here would silently swallow a translation
        that might still be wanted for whatever row now represents this key."""
        controller = self._make_controller(row_for_key=lambda key: None, is_stale=self._cell_is_stale)

        result_box = []
        controller._on_row_fully_filled_probe("no-such-key", [(1, "es")], result_box)

        assert result_box == [False]

    def test_row_precheck_skips_the_request_when_the_row_is_already_fully_filled(self):
        """End-to-end at the TranslationWorker level (no real QThread -- `run()` is called
        directly on the test thread, same pattern as
        TestTranslationWorkerStopsOnBatchStoppingErrors in test_rate_limit_propagation.py): a
        `row_precheck` that reports "already fully filled" for one key must stop that key's
        multi-locale request from ever reaching the translation service, while a key it reports
        False for proceeds normally."""
        from ui.translation_windows.outstanding_items.translation_orchestrator import TranslationWorker
        from utils.globals import LLMTranslationMode

        calls = []

        class _FakeTranslationService:
            def translate_with_llm_multi_locale(self, text, target_locales, context=None):
                calls.append(tuple(target_locales))
                return {locale: f"[{locale}] {text}" for locale in target_locales}

        queue = [
            ("already_filled_key", "Hello", [(1, "es"), (2, "fr")]),
            ("still_missing_key", "World", [(1, "es"), (2, "fr")]),
        ]
        precheck_calls = []

        def row_precheck(key, locale_cols):
            precheck_calls.append(key)
            return key == "already_filled_key"

        worker = TranslationWorker(
            _FakeTranslationService(),
            queue,
            use_llm=True,
            mode=LLMTranslationMode.PER_KEY_ALL_LOCALES,
            total=4,
            row_precheck=row_precheck,
        )
        completed_signals = []
        worker.translation_completed.connect(
            lambda key, col, locale, text: completed_signals.append((key, col, locale, text))
        )

        worker.run()

        assert precheck_calls == ["already_filled_key", "still_missing_key"]
        # Only "still_missing_key" ever reached the translation service -- the already-filled
        # key's request was skipped entirely, spending no cloud LLM call on it.
        assert calls == [("es", "fr")]
        assert [key for key, _col, _locale, _text in completed_signals] == [
            "still_missing_key", "still_missing_key"
        ]
        # Both keys still count toward progress even though one was skipped rather than sent.
        assert worker.completed == 4


class TestCloseEventWithRunningBatch:
    """Regression tests for the same class of close-event bugs
    translation_quality_review_window.py's TestLlmCatalogReviewThreading guards against:
    closeEvent() must not block waiting for the background thread (the in-flight Argos/LLM call
    can't be interrupted mid-request), and must disconnect the signals that touch this window so
    a late 'finished'/'translation_completed' emission after the window is gone doesn't try to
    update a closed widget.

    Uses a real QThread/TranslationWorker (via _SlowTranslationService, which blocks the worker
    thread for a bounded, known delay instead of making a real network call) so these are
    exercising real Qt threading behavior, not just a mocked controller.
    """

    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_close_event_batch_")
        self._env_ctx.__enter__()

        from ui.translation_windows.outstanding_items.window import OutstandingItemsWindow

        self.window = OutstandingItemsWindow(parent=None, project_path=None)

    def teardown_method(self):
        # Let any still-running background thread actually finish before tearing down, so we
        # don't leak a running QThread across tests.
        controller = getattr(self, "_leaked_controller", None)
        if controller is not None and controller.thread is not None:
            controller.thread.wait(5000)
        self.window.deleteLater()
        self._env_ctx.__exit__(None, None, None)

    def _start_slow_batch(self, delay=1.5):
        missing = _make_group("farewell", {"en": "Bye", "es": ""})
        translations = {missing.key: missing}
        self.window.load_data(translations, ["en", "es"])
        self.window.translation_service = _SlowTranslationService(delay=delay)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.translate_all_missing(use_llm=False)

        controller = self.window._translation_controller
        assert controller is not None
        assert controller.thread.isRunning()
        self._leaked_controller = controller  # for teardown, since closeEvent nulls the window's own pointer
        return controller

    def test_close_event_does_not_block_while_batch_is_running(self):
        from PyQt6.QtGui import QCloseEvent

        controller = self._start_slow_batch()

        start = time.monotonic()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.closeEvent(QCloseEvent())
        elapsed = time.monotonic() - start

        # The (hypothetical) old behavior of waiting on the thread here would block for
        # ~1 second (the _SlowTranslationService delay); this must return far sooner.
        assert elapsed < 0.5
        assert self.window._translation_controller is None
        # Detached, not killed: the background thread is still doing its (soon-to-be-ignored)
        # work independently.
        assert controller.thread.isRunning()

    def test_close_event_disconnects_controller_signals(self):
        from PyQt6.QtGui import QCloseEvent

        controller = self._start_slow_batch()

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.closeEvent(QCloseEvent())

        # Already disconnected by closeEvent(); disconnecting again must raise, proving the
        # window's slots are no longer attached (so a late emission after the window is closed
        # can't try to touch it).
        with pytest.raises((TypeError, RuntimeError)):
            controller.finished.disconnect(self.window._on_translation_finished)
        with pytest.raises((TypeError, RuntimeError)):
            controller.translation_completed.disconnect(self.window._on_translation_completed)
        with pytest.raises((TypeError, RuntimeError)):
            controller.progress_updated.disconnect(self.window._on_translation_progress)

    def test_close_event_resets_batch_controls_immediately(self):
        from PyQt6.QtGui import QCloseEvent

        self._start_slow_batch()
        assert self.window.is_translating is True

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.closeEvent(QCloseEvent())

        # A cached/reopened window (app.py reuses one instance) shouldn't come back with buttons
        # still disabled from a batch that was abandoned via close.
        assert self.window.is_translating is False
        assert self.window.translate_all_argos_btn.isEnabled() is True
        assert self.window.save_btn.isEnabled() is True

    def test_declining_the_close_confirmation_leaves_the_batch_attached(self):
        from PyQt6.QtGui import QCloseEvent

        controller = self._start_slow_batch()

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            event = QCloseEvent()
            self.window.closeEvent(event)

        assert event.isAccepted() is False
        assert self.window._translation_controller is controller
        assert self.window.is_translating is True
