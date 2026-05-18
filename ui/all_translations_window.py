from __future__ import annotations

import re
from typing import Any, Dict, Optional

from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QLineEdit, QComboBox, QCheckBox, QMenu,
                            QAbstractItemView, QDialog, QFormLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QAction

from i18n.translation_group import TranslationGroup, TranslationKey
from ui.app_style import AppStyle
from ui.base_translation_window import BaseTranslationWindow
from ui.quality_review_exclusions_dialog import QualityReviewExclusionsDialog
from utils.config import config_manager
from utils.globals import TranslationStatus, TranslationFilter
from utils.translations import I18N

_ = I18N._

# Minimum column widths: key column fits keys like "en.views.projects.created_at"; others slightly less
KEY_COLUMN_MIN_WIDTH = 200
OTHER_COLUMN_MIN_WIDTH = 140

class AllTranslationsWindow(BaseTranslationWindow):
    translation_updated = pyqtSignal(str, list)  # locale, [(msgid, new_value), ...]
    translation_group_deleted = pyqtSignal(object)  # key object (TranslationKey or str)

    def __init__(self, parent=None, project_path: Optional[str] = None):
        super().__init__(parent, title=_("All Translations"), geometry="1200x800")
        # Screen-relative min size; position already set by SmartWindow on parent's display
        screen = QApplication.primaryScreen().geometry()
        self.setMinimumSize(int(screen.width() * 0.8), int(screen.height() * 0.8))
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))

        self.show_escaped = False  # By default it should be encoded, not escaped
        self.setup_ui()
        self.setup_translation_service(project_path)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Search and filter controls
        controls_layout = QHBoxLayout()
        
        # Search box
        search_layout = QHBoxLayout()
        search_label = QLabel(_("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(_("Search translation keys... (Press Enter to search)"))
        self.search_box.returnPressed.connect(self.filter_table)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
        
        # Search button
        self.search_button = QPushButton(_("Search"))
        self.search_button.clicked.connect(self.filter_table)
        search_layout.addWidget(self.search_button)
        
        # Clear search button
        self.clear_search_button = QPushButton(_("Clear"))
        self.clear_search_button.clicked.connect(self.clear_search)
        search_layout.addWidget(self.clear_search_button)
        
        controls_layout.addLayout(search_layout)
        
        # Status filter
        filter_layout = QHBoxLayout()
        filter_label = QLabel(_("Filter:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems([filter.get_translated_value() for filter in TranslationFilter])
        self.status_filter.currentTextChanged.connect(self.filter_table)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.status_filter)
        controls_layout.addLayout(filter_layout)
        
        layout.addLayout(controls_layout)
        
        # Table for translations
        self.table = self.setup_table()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        if hasattr(self.table, "_frozen_table"):
            self.table._frozen_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table._frozen_table.customContextMenuRequested.connect(self.show_frozen_context_menu)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        if hasattr(self.table, "_frozen_table"):
            self.table._frozen_table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table._frozen_table.horizontalHeader().customContextMenuRequested.connect(self.show_frozen_header_context_menu)
        layout.addWidget(self.table)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton(_("Save Changes"))
        save_btn.clicked.connect(self.save_changes)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        
        # Add Unicode display toggle
        self.unicode_toggle = QCheckBox(_("Show Escaped Unicode"))
        self.unicode_toggle.setChecked(self.show_escaped)
        self.unicode_toggle.stateChanged.connect(self.toggle_unicode_display)

        self.exclusions_btn = QPushButton(_("Heuristic Exclusions"))
        self.exclusions_btn.clicked.connect(self.open_quality_exclusions)
        self.exclusions_btn.setToolTip(
            _("Manage msgid exclusions and ignore regex patterns for this project.")
        )
        
        self.find_replace_btn = QPushButton(_("Find && Replace"))
        self.find_replace_btn.clicked.connect(self.open_find_replace_dialog)
        self.find_replace_btn.setToolTip(_("Search and replace text within translation values"))

        self.revert_btn = QPushButton(_("Revert Changes"))
        self.revert_btn.clicked.connect(self.revert_changes)
        self.revert_btn.setToolTip(_("Restore all translations to their last saved state, discarding any unsaved edits"))

        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        button_layout.addWidget(self.exclusions_btn)
        button_layout.addWidget(self.find_replace_btn)
        button_layout.addWidget(self.revert_btn)
        button_layout.addWidget(self.unicode_toggle)
        layout.addLayout(button_layout)
        
        # Store original data
        self.all_translations = None
        self.all_locales = None
        self.status_cache = {}  # (row, col) -> set[TranslationStatus]

        AppStyle.sync_theme_from_widget(self)
        highlight_colors = AppStyle.get_translation_highlight_colors()
        self.missing_color = highlight_colors["missing"]
        self.critical_color = highlight_colors["critical"]
        self.style_color = highlight_colors["style"]

    def _get_translations_catalog(self) -> Optional[Dict[Any, TranslationGroup]]:
        return self.all_translations

    def closeEvent(self, event) -> None:
        if hasattr(self, "translation_service") and self.translation_service is not None:
            del self.translation_service
        super().closeEvent(event)

    def set_dynamic_column_widths(self, num_locales: int):
        """Override: key column and locale columns start at minimum width, resizable to higher."""
        super().set_dynamic_column_widths(num_locales)
        self.table.setColumnWidth(0, KEY_COLUMN_MIN_WIDTH)
        self.table.horizontalHeader().setMinimumSectionSize(OTHER_COLUMN_MIN_WIDTH)
        self.table.horizontalHeader().setMaximumSectionSize(800)

    def load_data(self, translations, locales):
        """Load translation data into the table."""
        # Store original data for filtering
        self.all_translations = translations
        self.all_locales = locales
        self.status_cache.clear()  # Clear any existing cache
        
        # Set up columns (first column is msgid, then one for each locale)
        self.table.setColumnCount(len(locales) + 1)
        headers = ["Translation Key"] + locales
        self.table.setHorizontalHeaderLabels(headers)
        
        # Set dynamic column widths based on number of locales
        self.set_dynamic_column_widths(len(locales))
        
        # Set up rows
        self.table.setRowCount(len(translations))
        
        # Fill in data (key is always TranslationKey)
        ignore_patterns = tuple(
            self.settings_manager.get_quality_review_script_ignore_patterns(
                self.project_path
            )
            if getattr(self, "project_path", None)
            else ()
        )
        for row, (key, group) in enumerate(translations.items()):
            msgid_item = QTableWidgetItem(group.key.msgid)
            msgid_item.setData(Qt.ItemDataRole.UserRole, key)
            msgid_item.setFlags(msgid_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, msgid_item)

            # Get invalid translations once per row
            invalid_locales = group.get_invalid_translations(
                locales, ignore_patterns=ignore_patterns
            )

            # Add translations for each locale
            for col, locale in enumerate(locales, 1):
                display_text = (
                    group.get_translation_escaped_as_text(locale)
                    if self.show_escaped
                    else group.get_translation_unescaped_as_text(locale)
                )
                item = QTableWidgetItem(display_text)

                # Determine cell status
                cell_statuses = set()
                if locale in invalid_locales.missing_locales:
                    cell_statuses.add(TranslationStatus.MISSING)
                if locale in invalid_locales.invalid_unicode_locales:
                    cell_statuses.add(TranslationStatus.INVALID_UNICODE)
                if locale in invalid_locales.invalid_index_locales:
                    cell_statuses.add(TranslationStatus.INVALID_INDICES)
                if locale in invalid_locales.invalid_brace_locales:
                    cell_statuses.add(TranslationStatus.INVALID_BRACES)
                if locale in invalid_locales.invalid_leading_space_locales:
                    cell_statuses.add(TranslationStatus.INVALID_LEADING_SPACE)
                if locale in invalid_locales.invalid_newline_locales:
                    cell_statuses.add(TranslationStatus.INVALID_NEWLINE)
                if locale in invalid_locales.invalid_character_set_locales:
                    cell_statuses.add(TranslationStatus.INVALID_CHARACTER_SET)

                # Store status in cache
                self.status_cache[(row, col)] = cell_statuses

                item.setToolTip("\n".join(
                    [status.get_translated_value() for status in cell_statuses]))

                # Highlight problematic cells with custom colors based on severity
                if TranslationStatus.MISSING in cell_statuses:
                    item.setBackground(self.missing_color)
                elif (TranslationStatus.INVALID_UNICODE in cell_statuses or 
                      TranslationStatus.INVALID_INDICES in cell_statuses):
                    item.setBackground(self.critical_color)
                elif cell_statuses:  # Any style issues
                    item.setBackground(self.style_color)

                self.table.setItem(row, col, item)

        # Start every column at its minimum width; user can resize to make them wider
        self.table.setColumnWidth(0, KEY_COLUMN_MIN_WIDTH)
        for col in range(1, self.table.columnCount()):
            self.table.setColumnWidth(col, OTHER_COLUMN_MIN_WIDTH)

    def filter_table(self):
        """Filter the table based on search text and status filter."""
        if not self.all_translations or not self.all_locales:
            return

        search_text = self.search_box.text().lower()
        filter_value = TranslationFilter.from_translated_value(self.status_filter.currentText())
        status_filter = filter_value.to_status()

        # First, apply status filter and collect row data with priorities
        visible_rows = []
        for row in range(self.table.rowCount()):
            show_row = True
            priority = 3  # Default priority (no match)

            msgid = self.table.item(row, 0).text()
            msgid_lower = msgid.lower()

            # Determine search match priority
            if search_text:
                if msgid_lower.startswith(search_text):
                    priority = 0  # Highest priority - starts with search text
                elif any(word.startswith(search_text) for word in msgid_lower.split()):
                    priority = 1  # Medium priority - word starts with search text
                elif search_text in msgid_lower:
                    priority = 2  # Low priority - contains search text
                else:
                    show_row = False

            # Apply status filter
            if show_row and filter_value != TranslationFilter.ALL:
                has_status = False
                for col in range(1, self.table.columnCount()):
                    if status_filter in self.status_cache.get((row, col), set()):
                        has_status = True
                        break
                if not has_status:
                    show_row = False

            if show_row:
                visible_rows.append((priority, row))

        # Sort rows by priority
        visible_rows.sort()  # Sort by priority (first element of tuple)

        # Reorder and show/hide rows
        for display_index, (priority, original_row) in enumerate(visible_rows):
            self.table.setRowHidden(original_row, False)
            self.table.verticalHeader().moveSection(
                self.table.verticalHeader().visualIndex(original_row),
                display_index
            )

        # Hide all rows that didn't match
        for row in range(self.table.rowCount()):
            if row not in [r for _, r in visible_rows]:
                self.table.setRowHidden(row, True)

    def show_context_menu(self, position):
        """Show context menu for copy/delete actions."""
        item = self.table.itemAt(position)
        if not item:
            return
        self._show_context_menu_for_item(item, self.table.mapToGlobal(position))

    def show_frozen_context_menu(self, position):
        """Show context menu for first-column cells in frozen view."""
        frozen = self.table._frozen_table
        index = frozen.indexAt(position)
        if not index.isValid():
            return
        item = self.table.item(index.row(), index.column())
        if not item:
            return
        self._show_context_menu_for_item(item, frozen.viewport().mapToGlobal(position))

    def _show_context_menu_for_item(self, item, global_position):
        """Build and show context menu for a specific table item."""
        menu = QMenu()
        copy_action = QAction(_("Copy Text"), self)
        copy_action.triggered.connect(lambda: self.copy_cell_text(item))
        menu.addAction(copy_action)

        default_locale = config_manager.get("translation.default_locale", "en")
        copy_default = QAction(_("Copy Default Translation"), self)
        copy_default.triggered.connect(
            lambda: self.copy_default_translation(item, default_locale)
        )
        menu.addAction(copy_default)

        menu.addSeparator()
        delete_action = QAction(_("Delete Translation Key"), self)
        delete_action.triggered.connect(lambda: self.delete_translation_group_for_row(item.row()))
        menu.addAction(delete_action)

        if item.column() > 0:
            menu.addSeparator()
            argos = QAction(_("Translate with Argos Translate"), self)
            argos.triggered.connect(lambda: self.translate_selected_item(item, use_llm=False))
            menu.addAction(argos)
            llm = QAction(_("Translate with LLM"), self)
            llm.triggered.connect(lambda: self.translate_selected_item(item, use_llm=True))
            menu.addAction(llm)

        menu.exec(global_position)

    def show_header_context_menu(self, position):
        """Show context menu for header cells."""
        column = self.table.horizontalHeader().logicalIndexAt(position)
        if column < 0:
            return

        menu = QMenu()
        copy_action = QAction(_("Copy Text"), self)
        header_item = self.table.horizontalHeaderItem(column)
        header_text = header_item.text() if header_item else ""
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(header_text))
        menu.addAction(copy_action)
        menu.exec(self.table.horizontalHeader().mapToGlobal(position))

    def show_frozen_header_context_menu(self, position):
        """Show context menu for frozen first-column header."""
        header = self.table._frozen_table.horizontalHeader()
        menu = QMenu()
        copy_action = QAction(_("Copy Text"), self)
        header_item = self.table.horizontalHeaderItem(0)
        header_text = header_item.text() if header_item else ""
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(header_text))
        menu.addAction(copy_action)
        menu.exec(header.mapToGlobal(position))

    def delete_translation_group_for_row(self, row: int):
        """Delete translation group represented by a table row."""
        key = self.get_key_from_row(row)
        item = self.table.item(row, 0)
        key_display = item.text() if item else str(key)

        if not self.confirm_delete_translation_group(key_display):
            return

        if key in self.all_translations:
            del self.all_translations[key]
            self.translation_group_deleted.emit(key)
            self.load_data(self.all_translations, self.all_locales)

    def save_changes(self):
        """Save all changes made in the table."""
        if not self.all_translations or not self.all_locales:
            return
            
        # Group changes by locale
        changes_by_locale = {}
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            key = item.data(Qt.ItemDataRole.UserRole) if item else None
            if key is None:
                key = item.text() if item else ""
            group = self.all_translations.get(key)
            if not group:
                continue
                
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                item = self.table.item(row, col)
                if not item:
                    continue
                    
                new_value = item.text()
                original_text = (
                    group.get_translation_escaped_as_text(locale)
                    if self.show_escaped
                    else group.get_translation_unescaped_as_text(locale)
                )

                # Only include if the value has changed and is non-empty
                if new_value != original_text and len(new_value) > 0:
                    if locale not in changes_by_locale:
                        changes_by_locale[locale] = []
                    changes_by_locale[locale].append((key, new_value))
        
        if not changes_by_locale:
            parent = self.parent()
            if (
                parent
                and hasattr(parent, "pending_deletions")
                and parent.pending_deletions
                and hasattr(parent, "process_batched_updates")
            ):
                parent.process_batched_updates()
                QMessageBox.information(self, _("Success"), _("Saved key deletions successfully!"))
                return

            QMessageBox.information(self, _("Info"), _("No changes to save."))
            return
        
        # Emit changes grouped by locale
        total_changes = sum(len(changes) for changes in changes_by_locale.values())
        for locale, changes in changes_by_locale.items():
            self.translation_updated.emit(locale, changes)
        
        QMessageBox.information(self, _("Success"), _("Saved {} changes successfully!").format(total_changes))

    def update_table_display(self):
        """Update the table display based on current Unicode display mode."""
        if not self.all_translations or not self.all_locales:
            return
            
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            key = item.data(Qt.ItemDataRole.UserRole) if item else None
            if key is None:
                key = item.text() if item else ""
            group = self.all_translations.get(key)
            if not group:
                continue
                
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                item = self.table.item(row, col)
                if item:
                    txt = (
                        group.get_translation_escaped_as_text(locale)
                        if self.show_escaped
                        else group.get_translation_unescaped_as_text(locale)
                    )
                    item.setText(txt)

    def clear_search(self):
        """Clear the search box and reset the filter to show all items."""
        self.search_box.clear()
        self.filter_table()

    def open_quality_exclusions(self):
        dialog = QualityReviewExclusionsDialog(
            project_path=getattr(self, "project_path", None),
            settings_manager=self.settings_manager,
            parent=self,
        )
        dialog.settings_saved.connect(self._reload_after_exclusions_saved)
        dialog.exec()

    def _reload_after_exclusions_saved(self):
        if self.all_translations is not None and self.all_locales is not None:
            self.load_data(self.all_translations, self.all_locales)

    def _row_for_translation_key(self, key: TranslationKey) -> int:
        """Logical row index whose first column carries ``key`` in UserRole, or ``-1``."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            k = item.data(Qt.ItemDataRole.UserRole)
            if k == key:
                return row
        return -1

    def navigate_to_translation_key(
        self, key: TranslationKey, locale: Optional[str] = None
    ) -> bool:
        """Make ``key`` visible (reset search/status filters), select the row, and scroll into view.

        If ``locale`` is a project locale code, scroll focus to that column; otherwise column 0.
        Returns ``False`` if the key is not in the loaded catalog or no matching row exists.
        """
        if not self.all_translations or key not in self.all_translations:
            return False

        self.search_box.blockSignals(True)
        self.status_filter.blockSignals(True)
        try:
            self.search_box.clear()
            self.status_filter.setCurrentIndex(0)
        finally:
            self.search_box.blockSignals(False)
            self.status_filter.blockSignals(False)
        self.filter_table()

        row = self._row_for_translation_key(key)
        if row < 0:
            return False

        col = 0
        if locale and self.all_locales:
            try:
                col = 1 + self.all_locales.index(locale)
            except ValueError:
                col = 0

        self.table.clearSelection()
        self.table.selectRow(row)
        item = self.table.item(row, col)
        if item is None:
            item = self.table.item(row, 0)
        if item is not None:
            self.table.setCurrentItem(item)
            self.table.scrollToItem(
                item, QAbstractItemView.ScrollHint.PositionAtCenter
            )
        if hasattr(self.table, "updateFrozenColumn"):
            self.table.updateFrozenColumn()
        return True

    def toggle_unicode_display(self):
        """Toggle the Unicode display mode."""
        self.show_escaped = not self.show_escaped
        self.update_table_display()
        # Force UI update
        QTimer.singleShot(0, lambda: self.table.viewport().update())

    def _has_unsaved_changes(self) -> bool:
        """Return True if any table cell differs from the underlying translation model value."""
        if not self.all_translations or not self.all_locales:
            return False
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            key = key_item.data(Qt.ItemDataRole.UserRole) if key_item else None
            if key is None:
                key = key_item.text() if key_item else ""
            group = self.all_translations.get(key)
            if not group:
                continue
            for col in range(1, self.table.columnCount()):
                locale_header = self.table.horizontalHeaderItem(col)
                if not locale_header:
                    continue
                locale = locale_header.text()
                cell = self.table.item(row, col)
                if not cell:
                    continue
                original = (
                    group.get_translation_escaped_as_text(locale)
                    if self.show_escaped
                    else group.get_translation_unescaped_as_text(locale)
                )
                if cell.text() != original:
                    return True
        return False

    def revert_changes(self):
        """Reload the table from the translation model, discarding any unsaved cell edits."""
        if not self.all_translations or not self.all_locales:
            return
        if self._has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                _("Revert Changes"),
                _(
                    "You have unsaved changes that will be lost.\n\n"
                    "Restore all translations to their last saved state?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.load_data(self.all_translations, self.all_locales)

    def open_find_replace_dialog(self):
        if not self.all_translations or not self.all_locales:
            QMessageBox.information(self, _("Find & Replace"), _("No translation data loaded."))
            return
        dialog = FindReplaceDialog(self)
        dialog.exec()

    @staticmethod
    def _apply_replacement(
        text: str,
        find_text: str,
        replace_text: str,
        use_regex: bool,
        case_sensitive: bool,
    ) -> str:
        """Return ``text`` with all occurrences of ``find_text`` replaced."""
        if not find_text:
            return text
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = find_text if use_regex else re.escape(find_text)
            return re.sub(pattern, replace_text, text, flags=flags)
        except re.error:
            return text

    def collect_replace_targets(
        self,
        find_text: str,
        replace_text: str,
        use_regex: bool,
        case_sensitive: bool,
        scope_index: int,
    ) -> list:
        """Return (row, col, old_text, new_text) for every visible cell that would change.

        scope_index=0 means all locale columns; any other value is the column index directly
        (the scope combo is populated as [All locales, locale1, locale2, ...] matching column order).
        """
        if not find_text or not self.all_locales:
            return []
        col_range = (
            range(1, self.table.columnCount())
            if scope_index == 0
            else range(scope_index, scope_index + 1)
        )
        targets = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            for col in col_range:
                item = self.table.item(row, col)
                if not item:
                    continue
                old_text = item.text()
                new_text = self._apply_replacement(
                    old_text, find_text, replace_text, use_regex, case_sensitive
                )
                if new_text != old_text:
                    targets.append((row, col, old_text, new_text))
        return targets

    def apply_replace_targets(self, targets: list) -> int:
        """Write new_text into each targeted table cell and trigger a repaint."""
        for row, col, _old, new_text in targets:
            item = self.table.item(row, col)
            if item is not None:
                item.setText(new_text)
        QTimer.singleShot(0, lambda: self.table.viewport().update())
        return len(targets)


class FindReplaceDialog(QDialog):
    """Modal dialog for finding and replacing text within translation values.

    The dialog previews the match count before applying any changes, and defers
    persistence to the parent window's existing Save Changes flow.
    """

    def __init__(self, parent: "AllTranslationsWindow"):
        super().__init__(parent)
        self._window = parent
        self.setWindowTitle(_("Find & Replace"))
        self.setMinimumWidth(480)
        self._setup_ui()
        self._populate_scope_combo()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Find / Replace inputs (form layout keeps labels aligned)
        form = QFormLayout()
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText(_("Text or pattern to find"))
        self.find_box.textChanged.connect(self._reset_status)
        form.addRow(_("Find:"), self.find_box)

        self.replace_box = QLineEdit()
        self.replace_box.setPlaceholderText(_("Replacement text (may be empty)"))
        form.addRow(_("Replace:"), self.replace_box)
        layout.addLayout(form)

        # Options row
        options_row = QHBoxLayout()
        self.regex_checkbox = QCheckBox(_("Regex"))
        self.regex_checkbox.setToolTip(_("Treat the find text as a regular expression"))
        self.regex_checkbox.stateChanged.connect(self._reset_status)
        options_row.addWidget(self.regex_checkbox)

        self.match_case_checkbox = QCheckBox(_("Match Case"))
        self.match_case_checkbox.setToolTip(_("Use case-sensitive matching"))
        self.match_case_checkbox.stateChanged.connect(self._reset_status)
        options_row.addWidget(self.match_case_checkbox)

        options_row.addSpacing(16)
        options_row.addWidget(QLabel(_("Scope:")))
        self.scope_combo = QComboBox()
        self.scope_combo.setToolTip(
            _("Apply to all locale columns, or restrict to a single locale")
        )
        self.scope_combo.currentIndexChanged.connect(self._reset_status)
        options_row.addWidget(self.scope_combo)
        options_row.addStretch()
        layout.addLayout(options_row)

        # Informational note about visible-row scoping
        scope_note = QLabel(
            _(
                "Only visible rows are searched and replaced. Use the Search box "
                "and Status Filter in the main window to narrow the scope before replacing."
            )
        )
        scope_note.setWordWrap(True)
        scope_note.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(scope_note)

        # Status label — shows match count, errors, or post-replace confirmation
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.replace_btn = QPushButton(_("Replace All"))
        self.replace_btn.setDefault(True)
        self.replace_btn.clicked.connect(self._on_replace_all)
        btn_row.addWidget(self.replace_btn)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _populate_scope_combo(self) -> None:
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self.scope_combo.addItem(_("All locales"))
        if self._window.all_locales:
            for loc in self._window.all_locales:
                self.scope_combo.addItem(loc)
        self.scope_combo.blockSignals(False)

    def _reset_status(self) -> None:
        self.status_label.setText("")

    def _on_replace_all(self) -> None:
        find_text = self.find_box.text()
        if not find_text:
            self.status_label.setText(_("Please enter text to find."))
            return

        use_regex = self.regex_checkbox.isChecked()
        case_sensitive = self.match_case_checkbox.isChecked()

        if use_regex:
            try:
                re.compile(find_text, 0 if case_sensitive else re.IGNORECASE)
            except re.error as exc:
                self.status_label.setText(
                    _("Invalid regex: {error}").format(error=str(exc))
                )
                return

        scope_index = self.scope_combo.currentIndex()
        replace_text = self.replace_box.text()

        targets = self._window.collect_replace_targets(
            find_text, replace_text, use_regex, case_sensitive, scope_index
        )

        if not targets:
            self.status_label.setText(_("No matches found."))
            return

        affected_rows = len({t[0] for t in targets})
        scope_label = self.scope_combo.currentText()

        reply = QMessageBox.question(
            self,
            _("Confirm Replacement"),
            _(
                "Found {cell_count} match(es) across {row_count} row(s) ({scope}).\n\n"
                "Changes are held in memory — use Save Changes to persist.\n\nProceed?"
            ).format(
                cell_count=len(targets),
                row_count=affected_rows,
                scope=scope_label,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        count = self._window.apply_replace_targets(targets)
        self.status_label.setText(
            _("Replaced {count} cell(s). Use Save Changes to persist.").format(count=count)
        )