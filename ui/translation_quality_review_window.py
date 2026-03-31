"""
Translation quality review (single entry point for two related feature areas):

1. **Possible issues** — lower-severity signals (built-in heuristics via ``QUALITY_REVIEW``).

2. **Business rules** — per-project rules stored in settings; evaluation hooks in
   :mod:`i18n.translation_quality_review` (engine may still return no findings until extended).

3. **LLM-assisted review** — batched catalog review with rolling state in :mod:`i18n.llm_catalog_review`.

The heuristic tab reuses :func:`ui.base_translation_window.create_frozen_translation_table`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional, Set

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QStandardItem
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from i18n.invalid_translation_groups import TranslationQualityFindings
from i18n.llm_catalog_review import CatalogLlmReviewResult
from i18n.translation_group import TranslationKey
from i18n.translation_manager_results import TranslationAction, TranslationManagerResults
from ui.base_translation_window import BaseTranslationWindow, create_frozen_translation_table
from utils.translations import I18N
from workers.translation_worker import TranslationWorker

if TYPE_CHECKING:
    from i18n.i18n_manager import I18NManager

_ = I18N._


class _CatalogLlmWorker(QObject):
    """Runs :func:`i18n.llm_catalog_review.run_catalog_llm_review` off the UI thread."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(
        self,
        translations,
        locales: list,
        default_locale: str,
        settings_manager,
        project_path: str,
    ):
        super().__init__()
        self._translations = translations
        self._locales = locales
        self._default_locale = default_locale
        self._settings_manager = settings_manager
        self._project_path = project_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        from i18n.llm_catalog_review import run_catalog_llm_review
        from lib.llm import LLM

        llm = LLM()
        try:
            result = run_catalog_llm_review(
                llm,
                self._translations,
                self._locales,
                self._default_locale,
                self._settings_manager,
                self._project_path,
                on_progress=lambda m: self.progress.emit(m),
                should_cancel=lambda: self._cancel,
            )
        except Exception as e:
            result = CatalogLlmReviewResult(
                final_report="",
                rolling_summary="",
                error_message=str(e),
            )
        self.finished.emit(result)


class TranslationQualityReviewWindow(BaseTranslationWindow):
    """Advisory translation checks, custom rules, and optional LLM catalog review."""

    #: Request main window to open :class:`~ui.all_translations_window.AllTranslationsWindow`
    #: and scroll to this key; second argument is locale code or ``None``.
    navigate_to_all_translations_requested = pyqtSignal(object, object)

    def __init__(
        self,
        parent=None,
        project_path: Optional[str] = None,
        settings_manager=None,
        i18n_manager: Optional["I18NManager"] = None,
    ):
        super().__init__(
            parent=parent,
            title=_("Translation Quality Review"),
            geometry="920x620",
            offset_x=40,
            offset_y=40,
        )
        self.project_path = project_path
        self.settings_manager = settings_manager
        self._i18n_manager = i18n_manager
        self._excluded_msgids: Set[str] = set()
        self._latin_ignore_patterns: Set[str] = set()
        self._custom_rules: list[dict[str, Any]] = []
        self._heuristic_rows: list[dict[str, Any]] = []
        self._heuristic_worker: Optional[TranslationWorker] = None
        self._llm_thread: Optional[QThread] = None
        self._llm_worker: Optional[_CatalogLlmWorker] = None

        self._setup_ui()
        self._refresh_lists_from_settings()
        self._update_settings_dependent_controls()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)

        intro = QLabel(
            _(
                "Review possible issues (lower severity than Outstanding Items), manage "
                "exclusions and business rules per project, and use the LLM tab when "
                "catalog review is enabled. Findings may be false positives—verify before changing translations."
            )
        )
        intro.setWordWrap(True)
        intro.setObjectName("translationQualityIntro")
        root.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, stretch=1)

        self._tabs = QTabWidget()
        splitter.addWidget(self._tabs)

        self._tabs.addTab(self._build_heuristic_tab(), _("Possible issues"))
        self._tabs.addTab(self._build_rules_tab(), _("Business rules"))
        self._tabs.addTab(self._build_exclusions_tab(), _("Exclusions"))
        self._tabs.addTab(self._build_llm_tab(), _("LLM review"))

    def _build_heuristic_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(
                _(
                    "Built-in checks: non-Latin-script locales with long Latin runs and a separate mixed-script Latin-leakage signal; translations identical "
                    "to the default locale. Respects exclusions from the Exclusions tab. "
                    "(English-ratio heuristic reserved.)"
                )
            )
        )
        filter_box = QGroupBox(_("Filters"))
        filter_layout = QGridLayout(filter_box)
        filter_layout.addWidget(QLabel(_("Key contains:")), 0, 0)
        self._filter_key_edit = QLineEdit()
        self._filter_key_edit.setPlaceholderText(_("e.g. home.index"))
        self._filter_key_edit.textChanged.connect(self._apply_heuristic_filters)
        filter_layout.addWidget(self._filter_key_edit, 0, 1)

        filter_layout.addWidget(QLabel(_("Default value contains:")), 0, 2)
        self._filter_default_edit = QLineEdit()
        self._filter_default_edit.textChanged.connect(self._apply_heuristic_filters)
        filter_layout.addWidget(self._filter_default_edit, 0, 3)

        filter_layout.addWidget(QLabel(_("Locale value contains:")), 1, 0)
        self._filter_locale_value_edit = QLineEdit()
        self._filter_locale_value_edit.textChanged.connect(self._apply_heuristic_filters)
        filter_layout.addWidget(self._filter_locale_value_edit, 1, 1)

        filter_layout.addWidget(QLabel(_("Detail contains:")), 1, 2)
        self._filter_detail_edit = QLineEdit()
        self._filter_detail_edit.textChanged.connect(self._apply_heuristic_filters)
        filter_layout.addWidget(self._filter_detail_edit, 1, 3)

        filter_layout.addWidget(QLabel(_("Target locale:")), 2, 0)
        self._filter_locale_combo = self._create_multi_select_combo(_("All locales"))
        filter_layout.addWidget(self._filter_locale_combo, 2, 1)

        filter_layout.addWidget(QLabel(_("Signal:")), 2, 2)
        self._filter_signal_combo = self._create_multi_select_combo(_("All signals"))
        filter_layout.addWidget(self._filter_signal_combo, 2, 3)
        layout.addWidget(filter_box)

        self._heuristic_table = create_frozen_translation_table()
        self._heuristic_table.setColumnCount(6)
        self._heuristic_table.setHorizontalHeaderLabels(
            [
                _("Key"),
                _("Locale"),
                _("Default locale value"),
                _("Locale value"),
                _("Signal"),
                _("Detail"),
            ]
        )
        hdr = self._heuristic_table.horizontalHeader()
        # Avoid Stretch on column 0: it would consume ~all width after tiny Locale/Signal cells,
        # hiding Detail. Key is Interactive (user-resizable); Detail stretches for readability.
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        self._heuristic_table.setColumnWidth(0, 240)
        self._heuristic_table.setColumnWidth(2, 200)
        self._heuristic_table.setColumnWidth(3, 200)
        self._heuristic_table.setSortingEnabled(True)
        self._heuristic_table.cellDoubleClicked.connect(self._on_heuristic_cell_double_clicked)
        self._heuristic_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._heuristic_table.customContextMenuRequested.connect(self._on_heuristic_context_menu)
        if hasattr(self._heuristic_table, "_frozen_table"):
            frozen = self._heuristic_table._frozen_table
            frozen.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            frozen.customContextMenuRequested.connect(self._on_heuristic_frozen_context_menu)
        layout.addWidget(self._heuristic_table, stretch=1)

        row = QHBoxLayout()
        self._run_heuristic_btn = QPushButton(_("Run heuristic analysis"))
        self._run_heuristic_btn.setToolTip(
            _("Reloads from disk and scans for advisory signals (may take a moment).")
        )
        self._run_heuristic_btn.clicked.connect(self._on_run_heuristic_analysis)
        row.addWidget(self._run_heuristic_btn)
        self._export_filtered_btn = QPushButton(_("Export filtered TSV…"))
        self._export_filtered_btn.setToolTip(
            _("Export the currently filtered rows from this table to a TSV file.")
        )
        self._export_filtered_btn.clicked.connect(self._on_export_filtered_tsv)
        row.addWidget(self._export_filtered_btn)
        row.addStretch()
        layout.addLayout(row)

        return page

    def _build_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(
                _(
                    "Per-project rules saved in application settings. The rule engine may "
                    "still be extended; use “Run custom rules” to evaluate when implemented."
                )
            )
        )

        rules_box = QGroupBox(_("Custom rules"))
        rules_layout = QVBoxLayout(rules_box)

        self._rules_list = QListWidget()
        self._rules_list.itemSelectionChanged.connect(self._update_rules_buttons)
        rules_layout.addWidget(self._rules_list)

        btn_row = QHBoxLayout()
        self._add_rule_btn = QPushButton(_("Add rule…"))
        self._edit_rule_btn = QPushButton(_("Edit…"))
        self._remove_rule_btn = QPushButton(_("Remove"))
        self._add_rule_btn.clicked.connect(self._on_add_rule)
        self._edit_rule_btn.clicked.connect(self._on_edit_rule)
        self._remove_rule_btn.clicked.connect(self._on_remove_rule)
        btn_row.addWidget(self._add_rule_btn)
        btn_row.addWidget(self._edit_rule_btn)
        btn_row.addWidget(self._remove_rule_btn)
        btn_row.addStretch()
        rules_layout.addLayout(btn_row)

        layout.addWidget(rules_box)

        self._run_rules_btn = QPushButton(_("Run custom rules"))
        self._run_rules_btn.setToolTip(
            _("Evaluate saved rules against the loaded catalog (when the engine reports findings).")
        )
        self._run_rules_btn.clicked.connect(self._on_run_custom_rules)
        layout.addWidget(self._run_rules_btn)

        return page

    def _build_exclusions_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(
                _(
                    "Msgids excluded from heuristic and custom-rule checks (saved per project). "
                    "Re-run heuristic analysis to refresh the Possible issues table after changes."
                )
            )
        )

        self._exclusions_list = QListWidget()
        self._exclusions_list.itemSelectionChanged.connect(self._update_exclusions_buttons)
        layout.addWidget(self._exclusions_list, stretch=1)

        ex_row = QHBoxLayout()
        self._add_exclusion_btn = QPushButton(_("Add key…"))
        self._remove_exclusion_btn = QPushButton(_("Remove"))
        self._add_exclusion_btn.clicked.connect(self._on_add_exclusion)
        self._remove_exclusion_btn.clicked.connect(self._on_remove_exclusion)
        ex_row.addWidget(self._add_exclusion_btn)
        ex_row.addWidget(self._remove_exclusion_btn)
        ex_row.addStretch()
        layout.addLayout(ex_row)

        layout.addWidget(
            QLabel(
                _(
                    "Regex patterns ignored by the Latin-in-CJK heuristic (matched text is removed before checking)."
                )
            )
        )
        self._latin_patterns_list = QListWidget()
        self._latin_patterns_list.itemSelectionChanged.connect(self._update_exclusions_buttons)
        layout.addWidget(self._latin_patterns_list, stretch=1)

        pat_row = QHBoxLayout()
        self._add_latin_pattern_btn = QPushButton(_("Add pattern…"))
        self._remove_latin_pattern_btn = QPushButton(_("Remove pattern"))
        self._add_latin_pattern_btn.clicked.connect(self._on_add_latin_pattern)
        self._remove_latin_pattern_btn.clicked.connect(self._on_remove_latin_pattern)
        pat_row.addWidget(self._add_latin_pattern_btn)
        pat_row.addWidget(self._remove_latin_pattern_btn)
        pat_row.addStretch()
        layout.addLayout(pat_row)

        return page

    def _build_llm_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(
                _(
                    "Optional catalog-wide LLM review sends token-batched TSV slices to your local "
                    "Ollama model, updates a rolling summary between batches, then requests a "
                    "final report. Requires loaded translations (e.g. Check Status). Cancel stops "
                    "between batches; the current request may still finish."
                )
            )
        )
        self._llm_output = QTextEdit()
        self._llm_output.setReadOnly(True)
        self._llm_output.setPlaceholderText(
            _("Progress lines and the final report appear here after you run the analysis.")
        )
        layout.addWidget(self._llm_output, stretch=1)

        llm_row = QHBoxLayout()
        self._run_llm_btn = QPushButton(_("Run LLM analysis"))
        self._run_llm_btn.setToolTip(
            _("Uses lib.llm.LLM against localhost:11434 (Ollama). May take several minutes.")
        )
        self._run_llm_btn.clicked.connect(self._on_run_llm_analysis)
        llm_row.addWidget(self._run_llm_btn)
        self._cancel_llm_btn = QPushButton(_("Cancel"))
        self._cancel_llm_btn.setEnabled(False)
        self._cancel_llm_btn.setToolTip(_("Request stop after the current batch completes."))
        self._cancel_llm_btn.clicked.connect(self._on_cancel_llm_analysis)
        llm_row.addWidget(self._cancel_llm_btn)
        llm_row.addStretch()
        layout.addLayout(llm_row)

        return page

    def _can_edit_settings(self) -> bool:
        return bool(self.project_path and self.settings_manager)

    def _update_settings_dependent_controls(self) -> None:
        can = self._can_edit_settings()
        for b in (
            self._add_rule_btn,
            self._edit_rule_btn,
            self._remove_rule_btn,
            self._add_exclusion_btn,
            self._remove_exclusion_btn,
            self._add_latin_pattern_btn,
            self._remove_latin_pattern_btn,
        ):
            b.setEnabled(can)
        if not can:
            tip = _("Select a project with settings support.")
            for b in (
                self._add_rule_btn,
                self._add_exclusion_btn,
                self._add_latin_pattern_btn,
            ):
                b.setToolTip(tip)
        else:
            self._add_rule_btn.setToolTip("")
            self._add_exclusion_btn.setToolTip("")
            self._add_latin_pattern_btn.setToolTip("")
        self._update_rules_buttons()
        self._update_exclusions_buttons()
        has_mgr = self._i18n_manager is not None
        self._run_rules_btn.setEnabled(has_mgr and bool(self._custom_rules))
        has_catalog = has_mgr and bool(self._i18n_manager.translations)
        llm_running = self._llm_thread is not None and self._llm_thread.isRunning()
        self._run_llm_btn.setEnabled(has_catalog and not llm_running)
        self._cancel_llm_btn.setEnabled(llm_running)
        self._export_filtered_btn.setEnabled(bool(self._heuristic_rows))

    def _update_rules_buttons(self) -> None:
        if not self._can_edit_settings():
            self._edit_rule_btn.setEnabled(False)
            self._remove_rule_btn.setEnabled(False)
            return
        sel = self._rules_list.currentItem() is not None
        self._edit_rule_btn.setEnabled(sel)
        self._remove_rule_btn.setEnabled(sel)

    def _update_exclusions_buttons(self) -> None:
        if not self._can_edit_settings():
            self._remove_exclusion_btn.setEnabled(False)
            self._remove_latin_pattern_btn.setEnabled(False)
            return
        self._remove_exclusion_btn.setEnabled(self._exclusions_list.currentItem() is not None)
        self._remove_latin_pattern_btn.setEnabled(self._latin_patterns_list.currentItem() is not None)

    def set_project_path(self, project_path: Optional[str]) -> None:
        self.project_path = project_path
        self._refresh_lists_from_settings()
        self._update_settings_dependent_controls()

    def set_i18n_manager(self, manager: Optional["I18NManager"]) -> None:
        self._i18n_manager = manager
        self._update_settings_dependent_controls()

    def load_exclusions(self, msgids: Set[str]) -> None:
        """Legacy: merge with stored settings via refresh instead."""
        self._excluded_msgids = set(msgids)

    def refresh_placeholder_lists(self) -> None:
        self._refresh_lists_from_settings()
        self._update_settings_dependent_controls()

    def _refresh_lists_from_settings(self) -> None:
        self._excluded_msgids = set()
        self._latin_ignore_patterns = set()
        self._custom_rules = []
        if not self.project_path or not self.settings_manager:
            self._populate_exclusions_list_widget()
            self._populate_latin_patterns_list_widget()
            self._populate_rules_list_widget()
            return

        self._excluded_msgids = set(
            self.settings_manager.get_quality_review_excluded_msgids(self.project_path)
        )
        self._latin_ignore_patterns = set(
            self.settings_manager.get_quality_review_latin_ignore_patterns(self.project_path)
        )
        raw_rules = self.settings_manager.get_quality_review_custom_rules(self.project_path)
        self._custom_rules = [dict(r) for r in raw_rules if isinstance(r, dict)]
        self._populate_exclusions_list_widget()
        self._populate_latin_patterns_list_widget()
        self._populate_rules_list_widget()

    def _populate_exclusions_list_widget(self) -> None:
        self._exclusions_list.clear()
        for mid in sorted(self._excluded_msgids):
            self._exclusions_list.addItem(mid)

    def _populate_latin_patterns_list_widget(self) -> None:
        self._latin_patterns_list.clear()
        for pat in sorted(self._latin_ignore_patterns):
            self._latin_patterns_list.addItem(pat)

    def _populate_rules_list_widget(self) -> None:
        self._rules_list.clear()
        for rule in self._custom_rules:
            name = str(rule.get("name") or rule.get("label") or _("(unnamed rule)"))
            desc = str(rule.get("description") or rule.get("note") or "")
            display = name if not desc else f"{name} — {desc[:80]}{'…' if len(desc) > 80 else ''}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, rule)
            item.setToolTip(desc or name)
            self._rules_list.addItem(item)

    def _save_exclusions(self) -> bool:
        if not self._can_edit_settings():
            return False
        ordered = sorted(self._excluded_msgids)
        return self.settings_manager.save_quality_review_excluded_msgids(
            self.project_path, ordered
        )

    def _save_custom_rules(self) -> bool:
        if not self._can_edit_settings():
            return False
        return self.settings_manager.save_quality_review_custom_rules(
            self.project_path, list(self._custom_rules)
        )

    def _save_latin_ignore_patterns(self) -> bool:
        if not self._can_edit_settings():
            return False
        return self.settings_manager.save_quality_review_latin_ignore_patterns(
            self.project_path, sorted(self._latin_ignore_patterns)
        )

    def _on_add_exclusion(self) -> None:
        if not self._can_edit_settings():
            return
        text, ok = QInputDialog.getText(
            self,
            _("Add exclusion"),
            _("Translation msgid to exclude:"),
        )
        if not ok:
            return
        mid = (text or "").strip()
        if not mid:
            return
        if mid in self._excluded_msgids:
            QMessageBox.information(
                self,
                _("Already excluded"),
                _("This msgid is already in the exclusion list."),
            )
            return
        self._excluded_msgids.add(mid)
        if not self._save_exclusions():
            self._excluded_msgids.discard(mid)
            QMessageBox.warning(self, _("Error"), _("Could not save exclusions."))
            return
        self._populate_exclusions_list_widget()

    def _on_remove_exclusion(self) -> None:
        if not self._can_edit_settings():
            return
        item = self._exclusions_list.currentItem()
        if not item:
            return
        mid = item.text().strip()
        reply = QMessageBox.question(
            self,
            _("Remove exclusion"),
            _("Stop excluding this msgid?\n\n{mid}").format(mid=mid),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._excluded_msgids.discard(mid)
        if not self._save_exclusions():
            self._excluded_msgids.add(mid)
            QMessageBox.warning(self, _("Error"), _("Could not save exclusions."))
            return
        self._populate_exclusions_list_widget()

    def _on_add_latin_pattern(self) -> None:
        if not self._can_edit_settings():
            return
        text, ok = QInputDialog.getText(
            self,
            _("Add Latin-ignore pattern"),
            _("Regex pattern to ignore in Latin-in-CJK heuristic:"),
        )
        if not ok:
            return
        pat = (text or "").strip()
        if not pat:
            return
        try:
            re.compile(pat)
        except re.error as e:
            QMessageBox.warning(
                self,
                _("Invalid pattern"),
                _("Regex error: {err}").format(err=str(e)),
            )
            return
        if pat in self._latin_ignore_patterns:
            QMessageBox.information(
                self,
                _("Already added"),
                _("This pattern is already in the ignore list."),
            )
            return
        self._latin_ignore_patterns.add(pat)
        if not self._save_latin_ignore_patterns():
            self._latin_ignore_patterns.discard(pat)
            QMessageBox.warning(self, _("Error"), _("Could not save patterns."))
            return
        self._populate_latin_patterns_list_widget()

    def _on_remove_latin_pattern(self) -> None:
        if not self._can_edit_settings():
            return
        item = self._latin_patterns_list.currentItem()
        if not item:
            return
        pat = item.text().strip()
        reply = QMessageBox.question(
            self,
            _("Remove pattern"),
            _("Stop ignoring this regex pattern?\n\n{pat}").format(pat=pat),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._latin_ignore_patterns.discard(pat)
        if not self._save_latin_ignore_patterns():
            self._latin_ignore_patterns.add(pat)
            QMessageBox.warning(self, _("Error"), _("Could not save patterns."))
            return
        self._populate_latin_patterns_list_widget()

    def _prompt_rule_fields(
        self, title: str, name_default: str = "", desc_default: str = ""
    ) -> Optional[tuple[str, str]]:
        name, ok = QInputDialog.getText(
            self,
            title,
            _("Rule name:"),
            text=name_default,
        )
        if not ok:
            return None
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, _("Error"), _("Rule name cannot be empty."))
            return None
        desc, ok2 = QInputDialog.getMultiLineText(
            self,
            title,
            _("Description or notes (optional):"),
            desc_default,
        )
        if not ok2:
            return None
        return name, (desc or "").strip()

    def _on_add_rule(self) -> None:
        if not self._can_edit_settings():
            return
        fields = self._prompt_rule_fields(_("Add rule"))
        if fields is None:
            return
        name, desc = fields
        rule = {"name": name, "description": desc}
        self._custom_rules.append(rule)
        if not self._save_custom_rules():
            self._custom_rules.pop()
            QMessageBox.warning(self, _("Error"), _("Could not save custom rules."))
            return
        self._populate_rules_list_widget()
        self._update_settings_dependent_controls()

    def _on_edit_rule(self) -> None:
        if not self._can_edit_settings():
            return
        row = self._rules_list.currentRow()
        if row < 0 or row >= len(self._custom_rules):
            return
        rule = self._custom_rules[row]
        name0 = str(rule.get("name") or "")
        desc0 = str(rule.get("description") or rule.get("note") or "")
        fields = self._prompt_rule_fields(_("Edit rule"), name0, desc0)
        if fields is None:
            return
        name, desc = fields
        new_rule = {"name": name, "description": desc}
        old = self._custom_rules[row]
        self._custom_rules[row] = new_rule
        if not self._save_custom_rules():
            self._custom_rules[row] = old
            QMessageBox.warning(self, _("Error"), _("Could not save custom rules."))
            return
        self._populate_rules_list_widget()
        self._update_settings_dependent_controls()

    def _on_remove_rule(self) -> None:
        if not self._can_edit_settings():
            return
        row = self._rules_list.currentRow()
        if row < 0 or row >= len(self._custom_rules):
            return
        rule = self._custom_rules[row]
        name = str(rule.get("name") or "")
        reply = QMessageBox.question(
            self,
            _("Remove rule"),
            _("Remove this rule?\n\n{name}").format(name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = self._custom_rules.pop(row)
        if not self._save_custom_rules():
            self._custom_rules.insert(row, removed)
            QMessageBox.warning(self, _("Error"), _("Could not save custom rules."))
            return
        self._populate_rules_list_widget()
        self._update_settings_dependent_controls()

    def _on_run_custom_rules(self) -> None:
        if not self._i18n_manager or not self._i18n_manager.translations:
            QMessageBox.warning(
                self,
                _("Error"),
                _("Load translation data first (e.g. Check Status on the main window)."),
            )
            return
        if not self._custom_rules:
            QMessageBox.information(
                self,
                _("Custom rules"),
                _("Add at least one rule before running."),
            )
            return

        from i18n.translation_quality_review import run_custom_rules

        locales = list(self._i18n_manager.locales)
        default_locale = self._i18n_manager.default_locale
        findings = run_custom_rules(
            self._i18n_manager.translations,
            locales,
            default_locale,
            self._custom_rules,
            frozenset(self._excluded_msgids),
        )
        n = len(findings.findings) if findings else 0
        if n == 0:
            QMessageBox.information(
                self,
                _("Custom rules"),
                _(
                    "No findings reported. Rules are saved for this project; extend the "
                    "rule engine in i18n.translation_quality_review when you add evaluators."
                ),
            )
        else:
            QMessageBox.information(
                self,
                _("Custom rules"),
                _("Reported {n} finding(s). (Detailed table UI can be added later.)").format(n=n),
            )

    def _disconnect_heuristic_worker(self) -> None:
        w = self._heuristic_worker
        if w is None:
            return
        try:
            w.finished.disconnect(self._on_heuristic_worker_finished)
        except (TypeError, RuntimeError):
            pass
        self._heuristic_worker = None

    def _cleanup_llm_thread(self) -> None:
        self._llm_worker = None
        self._llm_thread = None
        self._update_settings_dependent_controls()

    def _on_llm_progress(self, line: str) -> None:
        self._llm_output.append(line)

    def _on_llm_finished(self, result: object) -> None:
        self._run_llm_btn.setText(_("Run LLM analysis"))
        if isinstance(result, CatalogLlmReviewResult):
            cr = result
            if cr.final_report.strip():
                self._llm_output.append("")
                self._llm_output.append(_("--- Final report ---"))
                self._llm_output.append(cr.final_report)
            if cr.error_message:
                if cr.cancelled:
                    QMessageBox.information(
                        self,
                        _("LLM review"),
                        cr.error_message,
                    )
                else:
                    QMessageBox.warning(
                        self,
                        _("LLM review"),
                        cr.error_message,
                    )
        self._cleanup_llm_thread()

    def _on_cancel_llm_analysis(self) -> None:
        if self._llm_worker:
            self._llm_worker.cancel()

    def _on_run_llm_analysis(self) -> None:
        if not self._i18n_manager or not self._i18n_manager.translations:
            QMessageBox.warning(
                self,
                _("Error"),
                _("Load translation data first (e.g. Check Status on the main window)."),
            )
            return
        if self._llm_thread and self._llm_thread.isRunning():
            return

        self._llm_output.clear()
        self._llm_output.append(_("Starting catalog LLM review…"))

        project_path = self.project_path or ""
        worker = _CatalogLlmWorker(
            self._i18n_manager.translations,
            list(self._i18n_manager.locales),
            self._i18n_manager.default_locale,
            self.settings_manager,
            project_path,
        )
        thread = QThread()
        worker.moveToThread(thread)
        self._llm_worker = worker
        self._llm_thread = thread

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(self._on_llm_finished)
        worker.progress.connect(self._on_llm_progress)

        self._run_llm_btn.setText(_("Running…"))
        self._update_settings_dependent_controls()
        thread.start()

    def _on_run_heuristic_analysis(self) -> None:
        if not self.project_path or not self._i18n_manager:
            QMessageBox.warning(self, _("Error"), _("No project or translation manager available."))
            return

        self._disconnect_heuristic_worker()

        intro = (
            self.settings_manager.get_intro_details()
            if self.settings_manager
            else None
        )
        self._run_heuristic_btn.setEnabled(False)
        self._run_heuristic_btn.setText(_("Running…"))

        worker = TranslationWorker(
            self.project_path,
            TranslationAction.QUALITY_REVIEW,
            intro_details=intro,
            manager=self._i18n_manager,
        )
        self._heuristic_worker = worker
        worker.finished.connect(self._on_heuristic_worker_finished)
        worker.start()

    def _on_heuristic_worker_finished(self, results: TranslationManagerResults) -> None:
        self._run_heuristic_btn.setEnabled(True)
        self._run_heuristic_btn.setText(_("Run heuristic analysis"))
        self._disconnect_heuristic_worker()

        if not results.action_successful:
            QMessageBox.warning(
                self,
                _("Error"),
                results.error_message or _("Quality review failed."),
            )
            return

        qf = results.quality_findings
        if not qf or not qf.findings:
            self._heuristic_rows = []
            self._heuristic_table.setRowCount(0)
            self._set_multi_select_items(self._filter_locale_combo, [])
            self._set_multi_select_items(self._filter_signal_combo, [])
            self._update_settings_dependent_controls()
            QMessageBox.information(
                self,
                _("Quality review"),
                _("No advisory findings for the current built-in heuristics."),
            )
            return

        self._heuristic_rows = self._build_heuristic_rows(qf)
        self._sync_filter_options_from_rows()
        self._apply_heuristic_filters()
        self._update_settings_dependent_controls()

    def closeEvent(self, event) -> None:
        self._disconnect_heuristic_worker()
        if self._llm_worker:
            self._llm_worker.cancel()
        if self._llm_thread and self._llm_thread.isRunning():
            self._llm_thread.wait(30000)
        super().closeEvent(event)

    def _heuristic_row_key_and_locale(self, row: int) -> tuple[Optional[TranslationKey], Optional[str]]:
        key_item = self._heuristic_table.item(row, 0)
        loc_item = self._heuristic_table.item(row, 1)
        if not key_item:
            return None, None
        key = key_item.data(Qt.ItemDataRole.UserRole)
        if key is None:
            return None, None
        locale = loc_item.text().strip() if loc_item else ""
        return key, locale or None

    def _on_heuristic_cell_double_clicked(self, row: int, _col: int) -> None:
        key, locale = self._heuristic_row_key_and_locale(row)
        if key is not None:
            self.navigate_to_all_translations_requested.emit(key, locale)

    def _on_heuristic_context_menu(self, position) -> None:
        item = self._heuristic_table.itemAt(position)
        if not item:
            return
        self._show_heuristic_row_context_menu(
            item.row(), self._heuristic_table.mapToGlobal(position)
        )

    def _on_heuristic_frozen_context_menu(self, position) -> None:
        frozen = self._heuristic_table._frozen_table
        index = frozen.indexAt(position)
        if not index.isValid():
            return
        self._show_heuristic_row_context_menu(
            index.row(), frozen.viewport().mapToGlobal(position)
        )

    def _show_heuristic_row_context_menu(self, row: int, global_pos) -> None:
        key, locale = self._heuristic_row_key_and_locale(row)
        if key is None:
            return
        menu = QMenu(self)
        act = QAction(_("Open in All Translations"), self)
        act.triggered.connect(
            lambda checked=False, k=key, loc=locale: self.navigate_to_all_translations_requested.emit(
                k, loc
            )
        )
        menu.addAction(act)
        menu.exec(global_pos)

    def _build_heuristic_rows(self, qf: TranslationQualityFindings) -> list[dict[str, Any]]:
        rows = qf.findings
        out: list[dict[str, Any]] = []
        catalog = (
            self._i18n_manager.translations
            if self._i18n_manager
            else {}
        )
        default_loc = (
            self._i18n_manager.default_locale
            if self._i18n_manager
            else ""
        )
        for f in rows:
            key = TranslationKey(f.key_msgid, context=f.key_context or "")
            group = catalog.get(key)
            default_text = ""
            locale_text = ""
            if group is not None:
                default_text = group.get_translation(default_loc) or ""
                locale_text = group.get_translation(f.locale) or ""
            kind = f.signal
            det = kind.get_display_details()
            out.append(
                {
                    "key_obj": key,
                    "key_msgid": f.key_msgid,
                    "locale": f.locale,
                    "default_text": default_text,
                    "locale_text": locale_text,
                    "signal_name": kind.get_display_name(),
                    "detail": det,
                }
            )
        return out

    def _render_heuristic_rows(self, rows: list[dict[str, Any]]) -> None:
        hdr = self._heuristic_table.horizontalHeader()
        sort_col = hdr.sortIndicatorSection()
        sort_order = hdr.sortIndicatorOrder()
        self._heuristic_table.setSortingEnabled(False)
        self._heuristic_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            k_item = QTableWidgetItem(r["key_msgid"])
            k_item.setData(Qt.ItemDataRole.UserRole, r["key_obj"])
            k_item.setToolTip(r["key_msgid"])
            self._heuristic_table.setItem(i, 0, k_item)
            self._heuristic_table.setItem(i, 1, QTableWidgetItem(r["locale"]))
            def_item = QTableWidgetItem(r["default_text"])
            def_item.setToolTip(r["default_text"])
            self._heuristic_table.setItem(i, 2, def_item)
            loc_item = QTableWidgetItem(r["locale_text"])
            loc_item.setToolTip(r["locale_text"])
            self._heuristic_table.setItem(i, 3, loc_item)
            self._heuristic_table.setItem(i, 4, QTableWidgetItem(r["signal_name"]))
            det_item = QTableWidgetItem(r["detail"])
            det_item.setToolTip(r["detail"])
            self._heuristic_table.setItem(i, 5, det_item)
        self._heuristic_table.setSortingEnabled(True)
        if sort_col >= 0:
            self._heuristic_table.sortItems(sort_col, sort_order)
        if hasattr(self._heuristic_table, "updateFrozenColumn"):
            self._heuristic_table.updateFrozenColumn()

    def _create_multi_select_combo(self, placeholder: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setEditable(True)
        line = combo.lineEdit()
        if line:
            line.setReadOnly(True)
            line.setPlaceholderText(placeholder)
        model = combo.model()
        if model is not None:
            model.itemChanged.connect(lambda _item=None, c=combo: self._on_multi_select_changed(c))
        return combo

    def _on_multi_select_changed(self, combo: QComboBox) -> None:
        self._update_multi_select_combo_text(combo)
        self._apply_heuristic_filters()

    def _set_multi_select_items(self, combo: QComboBox, values: list[str]) -> None:
        selected = self._selected_multi_select_values(combo)
        model = combo.model()
        if model is None:
            return
        model.blockSignals(True)
        combo.clear()
        for value in values:
            item = QStandardItem(value)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(
                Qt.CheckState.Checked if value in selected else Qt.CheckState.Unchecked,
                Qt.ItemDataRole.CheckStateRole,
            )
            model.appendRow(item)
        model.blockSignals(False)
        self._update_multi_select_combo_text(combo)

    def _selected_multi_select_values(self, combo: QComboBox) -> set[str]:
        out: set[str] = set()
        model = combo.model()
        if model is None:
            return out
        for i in range(model.rowCount()):
            item = model.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                out.add(item.text())
        return out

    def _update_multi_select_combo_text(self, combo: QComboBox) -> None:
        selected = sorted(self._selected_multi_select_values(combo))
        line = combo.lineEdit()
        if line is None:
            return
        if not selected:
            line.setText(_("All"))
            return
        if len(selected) <= 2:
            line.setText(", ".join(selected))
            return
        line.setText(_("{n} selected").format(n=len(selected)))

    def _sync_filter_options_from_rows(self) -> None:
        locales = sorted({r["locale"] for r in self._heuristic_rows})
        signals = sorted({r["signal_name"] for r in self._heuristic_rows})
        self._set_multi_select_items(self._filter_locale_combo, locales)
        self._set_multi_select_items(self._filter_signal_combo, signals)

    @staticmethod
    def _matches_filter(value: str, needle: str) -> bool:
        if not needle:
            return True
        return needle.casefold() in (value or "").casefold()

    def _apply_heuristic_filters(self) -> None:
        rows = self._heuristic_rows
        key_filter = (self._filter_key_edit.text() or "").strip()
        default_filter = (self._filter_default_edit.text() or "").strip()
        locale_val_filter = (self._filter_locale_value_edit.text() or "").strip()
        detail_filter = (self._filter_detail_edit.text() or "").strip()
        locale_selected = self._selected_multi_select_values(self._filter_locale_combo)
        signal_selected = self._selected_multi_select_values(self._filter_signal_combo)

        filtered = []
        for r in rows:
            if locale_selected and r["locale"] not in locale_selected:
                continue
            if signal_selected and r["signal_name"] not in signal_selected:
                continue
            if not self._matches_filter(r["key_msgid"], key_filter):
                continue
            if not self._matches_filter(r["default_text"], default_filter):
                continue
            if not self._matches_filter(r["locale_text"], locale_val_filter):
                continue
            if not self._matches_filter(r["detail"], detail_filter):
                continue
            filtered.append(r)
        self._render_heuristic_rows(filtered)

    def _on_export_filtered_tsv(self) -> None:
        if self._heuristic_table.rowCount() == 0:
            QMessageBox.information(self, _("Export TSV"), _("No filtered rows to export."))
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            _("Export filtered findings as TSV"),
            "quality_review_findings.tsv",
            _("TSV files (*.tsv);;All files (*.*)"),
        )
        if not selected_filter:
            selected_filter = ""
        if not path:
            return
        headers = ["Key", "Locale", "Default locale value", "Locale value", "Signal", "Detail"]
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\t".join(headers) + "\n")
                for row in range(self._heuristic_table.rowCount()):
                    cols = []
                    for col in range(self._heuristic_table.columnCount()):
                        item = self._heuristic_table.item(row, col)
                        txt = item.text() if item else ""
                        txt = txt.replace("\t", " ").replace("\r", " ").replace("\n", " ")
                        cols.append(txt)
                    f.write("\t".join(cols) + "\n")
            QMessageBox.information(
                self,
                _("Export TSV"),
                _("Exported {n} row(s) to:\n{path}").format(
                    n=self._heuristic_table.rowCount(), path=path
                ),
            )
        except Exception as e:
            QMessageBox.warning(self, _("Export TSV"), _("Could not export TSV:\n{err}").format(err=str(e)))
