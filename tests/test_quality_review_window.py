"""Tests for ui.translation_quality_review_window.TranslationQualityReviewWindow.

Covers the heuristic-findings table shape (columns collapsed onto grouped findings, see
i18n.translation_quality_review._grouped_locale_finding) and a regression for column widths
shifting after filtering: the "Signal" column used to be QHeaderView.ResizeMode.ResizeToContents,
which recomputes width from whatever rows are currently in the model, so filtering to a narrower
set of signal names visibly reflowed every column after it.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_PYQT6 = True
except Exception:
    QApplication = None
    _HAS_PYQT6 = False

from test_utils import isolated_settings_and_cache_env
from utils.globals import QualityHeuristicKind
from utils.translations import I18N

_ = I18N._


class _FakeI18nManager:
    def __init__(self, translations: dict, default_locale: str = "en"):
        self.translations = translations
        self.default_locale = default_locale


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed in this environment")
class TestTranslationQualityReviewWindow:
    @classmethod
    def setup_class(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_quality_review_window_")
        self._env_ctx.__enter__()

        from ui.translation_quality_review_window import TranslationQualityReviewWindow

        self.window = TranslationQualityReviewWindow(
            parent=None,
            project_path=None,
            settings_manager=None,
            i18n_manager=None,
        )

    def teardown_method(self):
        self.window.deleteLater()
        self._env_ctx.__exit__(None, None, None)

    # -- helpers --------------------------------------------------------------

    def _make_group(self, msgid: str, values: dict):
        from i18n.translation_group import TranslationGroup

        g = TranslationGroup(msgid, is_in_base=True)
        g.default_locale = "en"
        for locale, text in values.items():
            g.add_translation(locale, text)
        return g

    def _findings_from_groups(self, groups: list, locales: list):
        from i18n.translation_quality_review import collect_findings_for_group
        from i18n.invalid_translation_groups import TranslationQualityFindings

        rows = []
        for g in groups:
            rows.extend(collect_findings_for_group(g, "en", locales))
        return TranslationQualityFindings(findings=rows)

    # -- table shape ------------------------------------------------------------

    def test_heuristic_table_has_six_columns(self):
        assert self.window._heuristic_table.columnCount() == 6

    def test_heuristic_table_headers_use_locales_not_locale_and_notes(self):
        # Headers are gettext-translated (see ui/translation_quality_review_window.py's `_ = I18N._`),
        # so compare against the same translation call rather than hardcoded English literals --
        # the active locale in the test environment may not be English.
        table = self.window._heuristic_table
        headers = [
            table.horizontalHeaderItem(i).text() for i in range(table.columnCount())
        ]
        assert headers == [
            _("Key"),
            _("Locales"),
            _("Default locale value"),
            _("Locale value"),
            _("Signal"),
            _("Detail"),
        ]

    # -- grouped-finding rendering ------------------------------------------------

    def test_grouped_latin_in_cjk_finding_renders_one_row_with_locales_listed(self):
        group = self._make_group(
            "shared.term",
            {
                "en": "Enable LoRA",
                "ja": "LoRA を有効にする Extra",
                "ko": "LoRA 활성화 Extra",
                "zh": "启用 LoRA Extra",
            },
        )
        self.window._i18n_manager = _FakeI18nManager({group.key: group})
        qf = self._findings_from_groups([group], ["en", "ja", "ko", "zh"])
        self.window._heuristic_rows = self.window._build_heuristic_rows(qf)
        self.window._apply_heuristic_filters()

        table = self.window._heuristic_table
        assert table.rowCount() == 1
        locales_text = table.item(0, 1).text()
        assert set(locales_text.split(", ")) == {"ja", "ko", "zh"}

    def test_heuristic_row_key_and_locale_uses_first_listed_locale(self):
        group = self._make_group(
            "shared.term",
            {
                "en": "Enable LoRA",
                "ja": "LoRA を有効にする Extra",
                "ko": "LoRA 활성화 Extra",
                "zh": "启用 LoRA Extra",
            },
        )
        self.window._i18n_manager = _FakeI18nManager({group.key: group})
        qf = self._findings_from_groups([group], ["en", "ja", "ko", "zh"])
        self.window._heuristic_rows = self.window._build_heuristic_rows(qf)
        self.window._apply_heuristic_filters()

        key, locale = self.window._heuristic_row_key_and_locale(0)
        assert key is not None
        assert locale == "ja"

    # -- column-width stability across filtering (regression) --------------------

    def test_column_widths_stable_after_filtering_to_a_narrower_signal_set(self):
        latin_group = self._make_group(
            "shared.term",
            {
                "en": "Enable LoRA",
                "ja": "LoRA を有効にする Extra",
                "ko": "LoRA 활성화 Extra",
            },
        )
        stop_char_group = self._make_group(
            "ui.save",
            {
                "en": "Save",
                "de": "Speichern.",
            },
        )
        self.window._i18n_manager = _FakeI18nManager(
            {latin_group.key: latin_group, stop_char_group.key: stop_char_group}
        )
        qf = self._findings_from_groups(
            [latin_group, stop_char_group], ["en", "ja", "ko", "de"]
        )
        self.window._heuristic_rows = self.window._build_heuristic_rows(qf)
        self.window._apply_heuristic_filters()
        signal_names = {r["signal_name"] for r in self.window._heuristic_rows}
        assert len(signal_names) >= 2  # a narrower filtered subset must exist to be meaningful

        table = self.window._heuristic_table
        widths_before = [table.columnWidth(i) for i in range(table.columnCount())]

        # Re-render with only the narrower subset of rows/signal names, simulating what
        # _apply_heuristic_filters does once the user picks a single "Signal" filter value.
        # signal_name is QualityHeuristicKind.get_display_name(), also gettext-translated.
        latin_display_name = QualityHeuristicKind.LATIN_IN_CJK_LOCALE.get_display_name()
        latin_only_rows = [
            r for r in self.window._heuristic_rows if r["signal_name"] == latin_display_name
        ]
        assert latin_only_rows
        assert len(latin_only_rows) < len(self.window._heuristic_rows)
        self.window._render_heuristic_rows(latin_only_rows)

        widths_after = [table.columnWidth(i) for i in range(table.columnCount())]
        # Columns 0-4 are all fixed-width Interactive now (see _build_heuristic_tab); only the
        # trailing Stretch "Detail" column (index 5) is allowed to change size.
        assert widths_before[:5] == widths_after[:5]

    def test_no_finding_ever_sets_a_single_locale_directly(self):
        # All built-in heuristics are group-scoped (see _grouped_locale_finding /
        # _finding_identical_to_default_for_group / _finding_identical_to_nondefault_for_group),
        # so the "Locale" column was removed entirely in favor of "Locales". If a future
        # heuristic reintroduces per-locale findings, this test will fail as a prompt to
        # reconsider whether the column should come back.
        latin_group = self._make_group(
            "shared.term",
            {"en": "Enable LoRA", "ja": "LoRA を有効にする Extra"},
        )
        qf = self._findings_from_groups([latin_group], ["en", "ja"])
        assert qf.findings
        assert all(f.locale == "" for f in qf.findings)
