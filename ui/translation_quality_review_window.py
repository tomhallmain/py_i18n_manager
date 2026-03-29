"""
Translation quality review (single entry point for two related feature areas):

1. **Possible issues** — lower-severity signals (built-in heuristics via ``QUALITY_REVIEW``).

2. **Business rules** — per-project rules stored in settings; evaluation hooks in
   :mod:`i18n.translation_quality_review` (engine may still return no findings until extended).

3. **LLM-assisted review** — reserved; batching helpers exist, run loop not wired here.

The heuristic tab reuses :func:`ui.base_translation_window.create_frozen_translation_table`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Set

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
from i18n.translation_group import TranslationKey
from i18n.translation_manager_results import TranslationAction, TranslationManagerResults
from lib.multi_display import SmartDialog
from ui.base_translation_window import create_frozen_translation_table
from utils.translations import I18N
from workers.translation_worker import TranslationWorker

if TYPE_CHECKING:
    from i18n.i18n_manager import I18NManager

_ = I18N._


class TranslationQualityReviewWindow(SmartDialog):
    """Advisory translation checks, custom rules, and optional LLM catalog review (future)."""

    def __init__(
        self,
        parent=None,
        project_path: Optional[str] = None,
        settings_manager=None,
        i18n_manager: Optional["I18NManager"] = None,
    ):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=_("Translation Quality Review"),
            geometry="920x620",
            offset_x=40,
            offset_y=40,
        )
        self.setModal(True)
        self.project_path = project_path
        self.settings_manager = settings_manager
        self._i18n_manager = i18n_manager
        self._excluded_msgids: Set[str] = set()
        self._custom_rules: list[dict[str, Any]] = []
        self._heuristic_worker: Optional[TranslationWorker] = None

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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_heuristic_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(
                _(
                    "Built-in checks: CJK locales with long Latin runs; translations identical "
                    "to the default locale. Respects exclusions from the Exclusions tab. "
                    "(English-ratio heuristic reserved.)"
                )
            )
        )
        self._heuristic_table = create_frozen_translation_table()
        self._heuristic_table.setColumnCount(4)
        self._heuristic_table.setHorizontalHeaderLabels(
            [_("Key"), _("Locale"), _("Signal"), _("Detail")]
        )
        self._heuristic_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for c in (1, 2, 3):
            self._heuristic_table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents
            )
        layout.addWidget(self._heuristic_table, stretch=1)

        row = QHBoxLayout()
        self._run_heuristic_btn = QPushButton(_("Run heuristic analysis"))
        self._run_heuristic_btn.setToolTip(
            _("Reloads from disk and scans for advisory signals (may take a moment).")
        )
        self._run_heuristic_btn.clicked.connect(self._on_run_heuristic_analysis)
        row.addWidget(self._run_heuristic_btn)
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

        return page

    def _build_llm_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(
                _(
                    "Optional catalog-wide LLM review will use token-batched TSV snippets from "
                    "i18n.translation_quality_review. This tab is not wired to the LLM yet."
                )
            )
        )
        self._llm_output = QTextEdit()
        self._llm_output.setReadOnly(True)
        self._llm_output.setPlaceholderText(
            _("LLM analysis will appear here when the catalog review run is implemented.")
        )
        layout.addWidget(self._llm_output, stretch=1)

        llm_row = QHBoxLayout()
        self._run_llm_btn = QPushButton(_("Run LLM analysis"))
        self._run_llm_btn.setEnabled(False)
        self._run_llm_btn.setToolTip(_("Not implemented yet."))
        llm_row.addWidget(self._run_llm_btn)
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
        ):
            b.setEnabled(can)
        if not can:
            tip = _("Select a project with settings support.")
            for b in (
                self._add_rule_btn,
                self._add_exclusion_btn,
            ):
                b.setToolTip(tip)
        else:
            self._add_rule_btn.setToolTip("")
            self._add_exclusion_btn.setToolTip("")
        self._update_rules_buttons()
        self._update_exclusions_buttons()
        has_mgr = self._i18n_manager is not None
        self._run_rules_btn.setEnabled(has_mgr and bool(self._custom_rules))

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
            return
        self._remove_exclusion_btn.setEnabled(self._exclusions_list.currentItem() is not None)

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
        self._custom_rules = []
        if not self.project_path or not self.settings_manager:
            self._populate_exclusions_list_widget()
            self._populate_rules_list_widget()
            return

        self._excluded_msgids = set(
            self.settings_manager.get_quality_review_excluded_msgids(self.project_path)
        )
        raw_rules = self.settings_manager.get_quality_review_custom_rules(self.project_path)
        self._custom_rules = [dict(r) for r in raw_rules if isinstance(r, dict)]
        self._populate_exclusions_list_widget()
        self._populate_rules_list_widget()

    def _populate_exclusions_list_widget(self) -> None:
        self._exclusions_list.clear()
        for mid in sorted(self._excluded_msgids):
            self._exclusions_list.addItem(mid)

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
            self._heuristic_table.setRowCount(0)
            QMessageBox.information(
                self,
                _("Quality review"),
                _("No advisory findings for the current built-in heuristics."),
            )
            return

        self._populate_heuristic_table(qf)

    def closeEvent(self, event) -> None:
        self._disconnect_heuristic_worker()
        super().closeEvent(event)

    def _populate_heuristic_table(self, qf: TranslationQualityFindings) -> None:
        rows = qf.findings
        self._heuristic_table.setRowCount(len(rows))
        for i, f in enumerate(rows):
            key = TranslationKey(f.key_msgid, context=f.key_context or "")
            k_item = QTableWidgetItem(f.key_msgid)
            k_item.setData(Qt.ItemDataRole.UserRole, key)
            k_item.setToolTip(f.key_msgid)
            self._heuristic_table.setItem(i, 0, k_item)
            self._heuristic_table.setItem(i, 1, QTableWidgetItem(f.locale))
            self._heuristic_table.setItem(i, 2, QTableWidgetItem(f.signal))
            d_item = QTableWidgetItem(f.detail)
            d_item.setToolTip(f.detail)
            self._heuristic_table.setItem(i, 3, d_item)
        if hasattr(self._heuristic_table, "updateFrozenColumn"):
            self._heuristic_table.updateFrozenColumn()
