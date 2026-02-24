from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QLineEdit, QComboBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication

from ui.app_style import AppStyle
from ui.base_translation_window import BaseTranslationWindow
from utils.globals import TranslationStatus, TranslationFilter
from utils.translations import I18N

_ = I18N._

# Minimum column widths: key column fits keys like "en.views.projects.created_at"; others slightly less
KEY_COLUMN_MIN_WIDTH = 200
OTHER_COLUMN_MIN_WIDTH = 140

class AllTranslationsWindow(BaseTranslationWindow):
    translation_updated = pyqtSignal(str, list)  # locale, [(msgid, new_value), ...]

    def __init__(self, parent=None):
        super().__init__(parent, title=_("All Translations"), geometry="1200x800")
        # Screen-relative min size; position already set by SmartDialog on parent's display
        screen = QApplication.primaryScreen().geometry()
        self.setMinimumSize(int(screen.width() * 0.8), int(screen.height() * 0.8))
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))
        
        self.show_escaped = False  # By default it should be encoded, not escaped
        self.setup_ui()
        
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
        
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
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
        for row, (key, group) in enumerate(translations.items()):
            msgid_item = QTableWidgetItem(group.key.msgid)
            msgid_item.setData(Qt.ItemDataRole.UserRole, key)
            msgid_item.setFlags(msgid_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, msgid_item)

            # Get invalid translations once per row
            invalid_locales = group.get_invalid_translations(locales)

            # Add translations for each locale
            for col, locale in enumerate(locales, 1):
                value = group.get_translation(locale)
                item = QTableWidgetItem(value)

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
                # Get original value in the same format as displayed
                original_value = group.get_translation_escaped(locale) if self.show_escaped else group.get_translation_unescaped(locale)
                
                # Only include if the value has changed and is non-empty
                if new_value != original_value and len(new_value) > 0:
                    if locale not in changes_by_locale:
                        changes_by_locale[locale] = []
                    changes_by_locale[locale].append((key, new_value))
        
        if not changes_by_locale:
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
                    if self.show_escaped:
                        item.setText(group.get_translation_escaped(locale))
                    else:
                        item.setText(group.get_translation_unescaped(locale))

    def clear_search(self):
        """Clear the search box and reset the filter to show all items."""
        self.search_box.clear()
        self.filter_table()

    def toggle_unicode_display(self):
        """Toggle the Unicode display mode."""
        self.show_escaped = not self.show_escaped
        self.update_table_display()
        # Force UI update
        QTimer.singleShot(0, lambda: self.table.viewport().update()) 