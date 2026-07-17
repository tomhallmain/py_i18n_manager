"""Tests for ui.translation_windows.outstanding_items.tsv_export.

Characterizes behavior carried over unchanged from the pre-extraction
ui/outstanding_items_window.py (OutstandingItemsWindow.export_outstanding_to_tsv and its
_sanitize_export_text/_truncate_export_text/_escape_markdown/_format_locale_list/
_format_locale_value_pairs helpers).
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


class TestSanitizeExportText:
    def test_replaces_tabs_newlines_and_carriage_returns_with_spaces(self):
        from ui.translation_windows.outstanding_items.tsv_export import sanitize_export_text

        assert sanitize_export_text("a\tb\nc\rd") == "a b c d"

    def test_none_becomes_empty_string(self):
        from ui.translation_windows.outstanding_items.tsv_export import sanitize_export_text

        assert sanitize_export_text(None) == ""


class TestTruncateExportText:
    def test_short_text_is_unchanged(self):
        from ui.translation_windows.outstanding_items.tsv_export import truncate_export_text

        assert truncate_export_text("hello", max_len=280) == "hello"

    def test_text_at_exact_limit_is_unchanged(self):
        from ui.translation_windows.outstanding_items.tsv_export import truncate_export_text

        text = "x" * 10
        assert truncate_export_text(text, max_len=10) == text

    def test_long_text_is_truncated_with_ellipsis_and_total_length_preserved(self):
        from ui.translation_windows.outstanding_items.tsv_export import truncate_export_text

        text = "x" * 20
        result = truncate_export_text(text, max_len=10)
        assert result == "x" * 7 + "..."
        assert len(result) == 10


class TestEscapeMarkdown:
    def test_escapes_backslash_and_pipe_and_strips_newlines(self):
        from ui.translation_windows.outstanding_items.tsv_export import escape_markdown

        assert escape_markdown("a\\b|c\nd\re") == "a\\\\b\\|c d e"


class TestFormatLocaleList:
    def test_empty_set_is_empty_string(self):
        from ui.translation_windows.outstanding_items.tsv_export import format_locale_list

        assert format_locale_list(set(), ["en", "es", "fr"]) == ""

    def test_preserves_locales_order(self):
        from ui.translation_windows.outstanding_items.tsv_export import format_locale_list

        assert format_locale_list({"fr", "es"}, ["en", "es", "fr"]) == "es, fr"

    def test_appends_unknown_locales_sorted_after_ordered_ones(self):
        from ui.translation_windows.outstanding_items.tsv_export import format_locale_list

        result = format_locale_list({"es", "zz", "aa"}, ["en", "es", "fr"])
        assert result == "es, aa, zz"


class TestFormatLocaleValuePairs:
    def test_empty_set_is_empty_string(self):
        from ui.translation_windows.outstanding_items.tsv_export import format_locale_value_pairs
        from i18n.translation_group import TranslationGroup

        group = TranslationGroup("greeting", is_in_base=True)
        assert format_locale_value_pairs(group, set(), ["en", "es"]) == ""

    def test_pairs_are_ordered_and_sanitized(self):
        from ui.translation_windows.outstanding_items.tsv_export import format_locale_value_pairs
        from i18n.translation_group import TranslationGroup

        group = TranslationGroup("greeting", is_in_base=True)
        group.add_translation("es", "Hola\tque tal")
        group.add_translation("fr", "Bonjour")

        result = format_locale_value_pairs(group, {"fr", "es"}, ["en", "es", "fr"])
        assert result == "es=Hola que tal | fr=Bonjour"


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestExportOutstandingToTsv:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_tsv_export_")
        self._env_ctx.__enter__()

    def teardown_method(self):
        self._env_ctx.__exit__(None, None, None)

    def _make_current_invalid_groups(self, locales):
        from i18n.translation_group import TranslationGroup

        group = TranslationGroup("farewell", is_in_base=True)
        group.add_translation("en", "Bye")
        group.add_translation("es", "")  # missing
        invalid_locales = group.get_invalid_translations(locales, ignore_patterns=())
        return {group.key: (invalid_locales, group)}

    def test_shows_info_dialog_and_skips_file_dialog_when_nothing_to_export(self):
        from ui.translation_windows.outstanding_items import tsv_export

        with patch.object(QMessageBox, "information") as mock_info, patch(
            "ui.translation_windows.outstanding_items.tsv_export.QFileDialog"
        ) as mock_dialog:
            tsv_export.export_outstanding_to_tsv(None, {}, None, ["en", "es"])

        mock_info.assert_called_once()
        mock_dialog.getSaveFileName.assert_not_called()

    def test_writes_tsv_and_markdown_companion_files(self, tmp_path):
        from ui.translation_windows.outstanding_items import tsv_export

        locales = ["en", "es"]
        current_invalid_groups = self._make_current_invalid_groups(locales)
        out_path = tmp_path / "outstanding.tsv"

        with patch(
            "ui.translation_windows.outstanding_items.tsv_export.QFileDialog"
        ) as mock_dialog, patch.object(QMessageBox, "information") as mock_info:
            mock_dialog.getSaveFileName.return_value = (str(out_path), "TSV Files (*.tsv)")
            tsv_export.export_outstanding_to_tsv(None, current_invalid_groups, str(tmp_path), locales)

        assert mock_info.called
        assert out_path.exists()
        md_path = out_path.with_suffix(".md")
        assert md_path.exists()

        tsv_lines = out_path.read_text(encoding="utf-8").splitlines()
        headers = tsv_lines[0].split("\t")
        assert headers[0] == "Translation Key"
        assert headers[3] == "Missing"
        row = tsv_lines[1].split("\t")
        assert row[0] == "farewell"
        assert row[1] == "Bye"
        assert row[3] == "es"  # Missing column lists the "es" locale

        md_text = md_path.read_text(encoding="utf-8")
        assert "farewell" in md_text
        assert "Missing locales: es" in md_text

    def test_default_save_path_is_under_the_project_directory(self, tmp_path):
        from ui.translation_windows.outstanding_items import tsv_export

        locales = ["en", "es"]
        current_invalid_groups = self._make_current_invalid_groups(locales)

        with patch(
            "ui.translation_windows.outstanding_items.tsv_export.QFileDialog"
        ) as mock_dialog, patch.object(QMessageBox, "information"):
            mock_dialog.getSaveFileName.return_value = ("", "")
            tsv_export.export_outstanding_to_tsv(
                None, current_invalid_groups, str(tmp_path), locales
            )

        default_name = mock_dialog.getSaveFileName.call_args[0][2]
        assert default_name == os.path.join(str(tmp_path), "outstanding_translation_keys.tsv")
