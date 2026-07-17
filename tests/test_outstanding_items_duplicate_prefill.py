"""Tests for ui.translation_windows.outstanding_items.duplicate_prefill.

Characterizes behavior carried over unchanged from the pre-extraction
ui/outstanding_items_window.py (OutstandingItemsWindow._detect_duplicate_values /
_ask_combine_duplicates / the outstanding_duplicate_groups + pending-prefill bookkeeping).
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
class TestDetectDuplicateValues:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_dup_prefill_")
        self._env_ctx.__enter__()

    def teardown_method(self):
        self._env_ctx.__exit__(None, None, None)

    def test_matches_an_outstanding_key_to_an_existing_key_with_same_default_value(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import detect_duplicate_values

        existing = _make_group("existing.key", {"en": "Save", "es": "Guardar"})
        outstanding = _make_group("outstanding.key", {"en": "Save", "es": ""})
        translations = {existing.key: existing, outstanding.key: outstanding}

        existing_to_outstanding, outstanding_dupes = detect_duplicate_values(
            translations, ["en", "es"]
        )

        assert existing_to_outstanding == {"Save": [(existing.key, outstanding.key)]}
        assert outstanding_dupes == {}

    def test_groups_two_outstanding_keys_sharing_a_default_value(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import detect_duplicate_values

        dup1 = _make_group("dup.one", {"en": "Hello", "es": ""})
        dup2 = _make_group("dup.two", {"en": "Hello", "es": ""})
        translations = {dup1.key: dup1, dup2.key: dup2}

        existing_to_outstanding, outstanding_dupes = detect_duplicate_values(
            translations, ["en", "es"]
        )

        assert existing_to_outstanding == {}
        assert outstanding_dupes == {"Hello": [dup1.key, dup2.key]}

    def test_no_matches_when_default_values_differ(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import detect_duplicate_values

        a = _make_group("a.key", {"en": "Hello", "es": ""})
        b = _make_group("b.key", {"en": "Goodbye", "es": ""})
        translations = {a.key: a, b.key: b}

        existing_to_outstanding, outstanding_dupes = detect_duplicate_values(
            translations, ["en", "es"]
        )

        assert existing_to_outstanding == {}
        assert outstanding_dupes == {}

    def test_groups_not_in_base_are_ignored(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import detect_duplicate_values

        existing = _make_group("existing.key", {"en": "Save", "es": "Guardar"})
        orphan = _make_group("orphan.key", {"en": "Save", "es": ""}, is_in_base=False)
        translations = {existing.key: existing, orphan.key: orphan}

        existing_to_outstanding, outstanding_dupes = detect_duplicate_values(
            translations, ["en", "es"]
        )

        assert existing_to_outstanding == {}
        assert outstanding_dupes == {}


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestAskCombineDuplicates:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_returns_no_without_showing_a_dialog_when_there_are_no_matches(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import ask_combine_duplicates

        with patch.object(QMessageBox, "exec") as mock_exec:
            result = ask_combine_duplicates(None, 0, 0)

        assert result == "no"
        mock_exec.assert_not_called()

    def test_yes_reply_maps_to_yes(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import ask_combine_duplicates

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            result = ask_combine_duplicates(None, 2, 0)

        assert result == "yes"

    def test_no_reply_maps_to_no(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import ask_combine_duplicates

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No):
            result = ask_combine_duplicates(None, 1, 1)

        assert result == "no"

    def test_escape_or_cancel_maps_to_cancel(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import ask_combine_duplicates

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            result = ask_combine_duplicates(None, 1, 1)

        assert result == "cancel"


class _FakeLabel:
    """Stand-in for the window's QLabel prefill notice -- avoids needing a QApplication."""

    def __init__(self):
        self.hidden = False
        self.shown = False
        self.text = None

    def hide(self):
        self.hidden = True
        self.shown = False

    def show(self):
        self.shown = True
        self.hidden = False

    def setText(self, text):
        self.text = text


class TestDuplicatePrefillState:
    def test_starts_empty(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import DuplicatePrefillState

        state = DuplicatePrefillState()

        assert state.outstanding_duplicate_groups == {}
        assert state.last_combine_choice == "no"
        assert state.pending_prefill_update_count() == 0
        assert list(state.iter_pending_prefill_changes()) == []

    def test_record_and_iterate_pending_prefill_changes(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import DuplicatePrefillState

        state = DuplicatePrefillState()
        state.record_prefill_change("es", "key1", "Hola")
        state.record_prefill_change("es", "key2", "Adiós")
        state.record_prefill_change("fr", "key1", "Bonjour")

        assert state.pending_prefill_update_count() == 3
        changes = dict(state.iter_pending_prefill_changes())
        assert set(changes["es"]) == {("key1", "Hola"), ("key2", "Adiós")}
        assert changes["fr"] == [("key1", "Bonjour")]

    def test_clear_pending_prefill_changes(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import DuplicatePrefillState

        state = DuplicatePrefillState()
        state.record_prefill_change("es", "key1", "Hola")
        state.clear_pending_prefill_changes()

        assert state.pending_prefill_update_count() == 0

    def test_reset_for_load_clears_groups_and_pending_but_keeps_last_combine_choice(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import DuplicatePrefillState

        state = DuplicatePrefillState()
        state.outstanding_duplicate_groups["rep"] = ["rep", "dupe"]
        state.record_prefill_change("es", "key1", "Hola")
        state.last_combine_choice = "yes"

        state.reset_for_load()

        assert state.outstanding_duplicate_groups == {}
        assert state.pending_prefill_update_count() == 0
        assert state.last_combine_choice == "yes"

    def test_update_notice_hides_label_when_nothing_pending(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import DuplicatePrefillState

        state = DuplicatePrefillState()
        label = _FakeLabel()

        state.update_notice(label)

        assert label.hidden is True

    def test_update_notice_shows_label_with_count_when_pending(self):
        from ui.translation_windows.outstanding_items.duplicate_prefill import DuplicatePrefillState

        state = DuplicatePrefillState()
        state.record_prefill_change("es", "key1", "Hola")
        state.record_prefill_change("fr", "key1", "Bonjour")
        label = _FakeLabel()

        state.update_notice(label)

        assert label.shown is True
        assert "2" in label.text
