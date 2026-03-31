from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from lib.multi_display import SmartDialog
from utils.settings_manager import SettingsManager
from utils.translations import I18N

_ = I18N._


class QualityReviewExclusionsDialog(SmartDialog):
    """Manage per-project msgid exclusions and regex ignore patterns."""

    settings_saved = pyqtSignal()

    def __init__(
        self,
        project_path: Optional[str],
        settings_manager: Optional[SettingsManager] = None,
        parent=None,
    ):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=_("Heuristic Exclusions"),
            geometry="760x560",
            offset_x=45,
            offset_y=45,
        )
        self.project_path = project_path or ""
        self.settings_manager = settings_manager or SettingsManager()
        self._excluded_msgids: set[str] = set()
        self._latin_ignore_patterns: set[str] = set()
        self._setup_ui()
        self._refresh_from_settings()
        self._update_buttons()

    def _can_edit_settings(self) -> bool:
        return bool(self.project_path and self.settings_manager)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            _(
                "Configure per-project exclusions used by quality review and invalid character-set checks. "
                "Regex patterns are applied after placeholder scrubbing."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        msgids_group = QGroupBox(_("Excluded translation keys (msgids)"))
        msgids_layout = QVBoxLayout(msgids_group)
        self._exclusions_list = QListWidget()
        self._exclusions_list.itemSelectionChanged.connect(self._update_buttons)
        msgids_layout.addWidget(self._exclusions_list)
        msgid_row = QHBoxLayout()
        self._add_exclusion_btn = QPushButton(_("Add key..."))
        self._remove_exclusion_btn = QPushButton(_("Remove key"))
        self._add_exclusion_btn.clicked.connect(self._on_add_exclusion)
        self._remove_exclusion_btn.clicked.connect(self._on_remove_exclusion)
        msgid_row.addWidget(self._add_exclusion_btn)
        msgid_row.addWidget(self._remove_exclusion_btn)
        msgid_row.addStretch()
        msgids_layout.addLayout(msgid_row)
        layout.addWidget(msgids_group, stretch=1)

        patterns_group = QGroupBox(_("Regex ignore patterns"))
        patterns_layout = QVBoxLayout(patterns_group)
        patt_info = QLabel(
            _(
                "Default patterns are seeded for common technical tokens (CSV, HTML, JSON, etc.). "
                "You can remove or replace any of them."
            )
        )
        patt_info.setWordWrap(True)
        patterns_layout.addWidget(patt_info)
        self._patterns_list = QListWidget()
        self._patterns_list.itemSelectionChanged.connect(self._update_buttons)
        patterns_layout.addWidget(self._patterns_list)
        patt_row = QHBoxLayout()
        self._add_pattern_btn = QPushButton(_("Add pattern..."))
        self._remove_pattern_btn = QPushButton(_("Remove pattern"))
        self._reset_defaults_btn = QPushButton(_("Restore default patterns"))
        self._add_pattern_btn.clicked.connect(self._on_add_pattern)
        self._remove_pattern_btn.clicked.connect(self._on_remove_pattern)
        self._reset_defaults_btn.clicked.connect(self._on_restore_default_patterns)
        patt_row.addWidget(self._add_pattern_btn)
        patt_row.addWidget(self._remove_pattern_btn)
        patt_row.addWidget(self._reset_defaults_btn)
        patt_row.addStretch()
        patterns_layout.addLayout(patt_row)
        layout.addWidget(patterns_group, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _refresh_from_settings(self) -> None:
        self._excluded_msgids = set(
            self.settings_manager.get_quality_review_excluded_msgids(self.project_path)
        )
        self._latin_ignore_patterns = set(
            self.settings_manager.get_quality_review_script_ignore_patterns(
                self.project_path
            )
        )
        self._populate_list_widgets()

    def _populate_list_widgets(self) -> None:
        self._exclusions_list.clear()
        for msgid in sorted(self._excluded_msgids):
            self._exclusions_list.addItem(msgid)
        self._patterns_list.clear()
        for pattern in sorted(self._latin_ignore_patterns):
            self._patterns_list.addItem(pattern)

    def _save_exclusions(self) -> bool:
        return self.settings_manager.save_quality_review_excluded_msgids(
            self.project_path,
            sorted(self._excluded_msgids),
        )

    def _save_patterns(self) -> bool:
        return self.settings_manager.save_quality_review_script_ignore_patterns(
            self.project_path,
            sorted(self._latin_ignore_patterns),
        )

    def _emit_saved(self) -> None:
        self.settings_saved.emit()
        self._update_buttons()

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
        msgid = (text or "").strip()
        if not msgid:
            return
        if msgid in self._excluded_msgids:
            QMessageBox.information(
                self,
                _("Already excluded"),
                _("This msgid is already in the exclusion list."),
            )
            return
        self._excluded_msgids.add(msgid)
        if not self._save_exclusions():
            self._excluded_msgids.discard(msgid)
            QMessageBox.warning(self, _("Error"), _("Could not save exclusions."))
            return
        self._populate_list_widgets()
        self._emit_saved()

    def _on_remove_exclusion(self) -> None:
        if not self._can_edit_settings():
            return
        item = self._exclusions_list.currentItem()
        if not item:
            return
        msgid = item.text().strip()
        reply = QMessageBox.question(
            self,
            _("Remove exclusion"),
            _("Stop excluding this msgid?\n\n{mid}").format(mid=msgid),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._excluded_msgids.discard(msgid)
        if not self._save_exclusions():
            self._excluded_msgids.add(msgid)
            QMessageBox.warning(self, _("Error"), _("Could not save exclusions."))
            return
        self._populate_list_widgets()
        self._emit_saved()

    def _on_add_pattern(self) -> None:
        if not self._can_edit_settings():
            return
        text, ok = QInputDialog.getText(
            self,
            _("Add ignore pattern"),
            _("Regex pattern to remove before script checks:"),
        )
        if not ok:
            return
        pattern = (text or "").strip()
        if not pattern:
            return
        try:
            re.compile(pattern)
        except re.error as e:
            QMessageBox.warning(
                self,
                _("Invalid pattern"),
                _("Regex error: {err}").format(err=str(e)),
            )
            return
        if pattern in self._latin_ignore_patterns:
            QMessageBox.information(
                self,
                _("Already added"),
                _("This pattern is already in the ignore list."),
            )
            return
        self._latin_ignore_patterns.add(pattern)
        if not self._save_patterns():
            self._latin_ignore_patterns.discard(pattern)
            QMessageBox.warning(self, _("Error"), _("Could not save patterns."))
            return
        self._populate_list_widgets()
        self._emit_saved()

    def _on_remove_pattern(self) -> None:
        if not self._can_edit_settings():
            return
        item = self._patterns_list.currentItem()
        if not item:
            return
        pattern = item.text().strip()
        reply = QMessageBox.question(
            self,
            _("Remove pattern"),
            _("Stop ignoring this regex pattern?\n\n{pat}").format(pat=pattern),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._latin_ignore_patterns.discard(pattern)
        if not self._save_patterns():
            self._latin_ignore_patterns.add(pattern)
            QMessageBox.warning(self, _("Error"), _("Could not save patterns."))
            return
        self._populate_list_widgets()
        self._emit_saved()

    def _on_restore_default_patterns(self) -> None:
        if not self._can_edit_settings():
            return
        reply = QMessageBox.question(
            self,
            _("Restore defaults"),
            _("Replace current ignore patterns with the default set?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self.settings_manager.reset_quality_review_script_ignore_patterns_to_defaults(
            self.project_path
        ):
            QMessageBox.warning(self, _("Error"), _("Could not restore default patterns."))
            return
        self._refresh_from_settings()
        self._emit_saved()

    def _update_buttons(self) -> None:
        can_edit = self._can_edit_settings()
        self._add_exclusion_btn.setEnabled(can_edit)
        self._remove_exclusion_btn.setEnabled(
            can_edit and self._exclusions_list.currentItem() is not None
        )
        self._add_pattern_btn.setEnabled(can_edit)
        self._remove_pattern_btn.setEnabled(
            can_edit and self._patterns_list.currentItem() is not None
        )
        self._reset_defaults_btn.setEnabled(can_edit)
