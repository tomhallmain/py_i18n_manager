from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QLineEdit, QComboBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from utils.translations import I18N
from utils.globals import TranslationStatus, TranslationFilter

_ = I18N._

class AllTranslationsWindow(QDialog):
    translation_updated = pyqtSignal(str, str, str)  # msgid, locale, new_value
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("All Translations"))
        
        # Get screen dimensions and set window size
        screen = QApplication.primaryScreen().geometry()
        self.setMinimumSize(int(screen.width() * 0.8), int(screen.height() * 0.8))  # 80% of screen size
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))  # 90% of screen size
        
        self.show_escaped = True  # Set to True by default
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Search and filter controls
        controls_layout = QHBoxLayout()
        
        # Search box
        search_layout = QHBoxLayout()
        search_label = QLabel(_("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(_("Search translation keys..."))
        self.search_box.textChanged.connect(self.filter_table)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
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
        self.table = QTableWidget()
        self.table.setColumnCount(0)  # Will be set when data is loaded
        self.table.setRowCount(0)     # Will be set when data is loaded
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton(_("Save Changes"))
        save_btn.clicked.connect(self.save_changes)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        
        # Add Unicode display toggle
        self.unicode_toggle = QCheckBox(_("Show Escaped Unicode"))
        self.unicode_toggle.setChecked(True)  # Set to checked by default
        self.unicode_toggle.stateChanged.connect(self.toggle_unicode_display)
        
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        button_layout.addWidget(self.unicode_toggle)
        layout.addLayout(button_layout)
        
        # Store original data
        self.all_translations = None
        self.all_locales = None
        self.status_cache = {}  # (row, col) -> set[TranslationStatus]

        # Define custom colors
        self.missing_color = QColor(255, 255, 200)    # Light yellow for missing translations
        self.critical_color = QColor(255, 200, 200)   # Light red for critical issues (unicode/indices)
        self.style_color = QColor(255, 220, 180)      # Light orange for style issues

    def load_data(self, translations, locales):
        """Load translation data into the table.
        
        Args:
            translations: Dict of msgid -> TranslationGroup
            locales: List of locale codes
        """
        # Store original data for filtering
        self.all_translations = translations
        self.all_locales = locales
        self.status_cache.clear()  # Clear any existing cache
        
        # Set up columns (first column is msgid, then one for each locale)
        self.table.setColumnCount(len(locales) + 1)
        headers = ["Translation Key"] + locales
        self.table.setHorizontalHeaderLabels(headers)
        
        # Set up rows
        self.table.setRowCount(len(translations))        

        # Fill in data
        for row, (msgid, group) in enumerate(translations.items()):
            # Add msgid
            msgid_item = QTableWidgetItem(msgid)
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

                # Highlight problematic cells with custom colors based on severity
                if TranslationStatus.MISSING in cell_statuses:
                    item.setBackground(self.missing_color)
                elif (TranslationStatus.INVALID_UNICODE in cell_statuses or 
                      TranslationStatus.INVALID_INDICES in cell_statuses):
                    item.setBackground(self.critical_color)
                elif cell_statuses:  # Any style issues
                    item.setBackground(self.style_color)

                self.table.setItem(row, col, item)

        # Adjust column widths
        self.table.resizeColumnsToContents()

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
            
        changes = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
                
            msgid = self.table.item(row, 0).text()
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                new_value = self.table.item(row, col).text()
                changes.append((msgid, locale, new_value))
        
        if not changes:
            QMessageBox.information(self, _("Info"), _("No changes to save."))
            return
        
        # Emit changes
        for msgid, locale, new_value in changes:
            self.translation_updated.emit(msgid, locale, new_value)
        
        QMessageBox.information(self, _("Success"), _("Saved {} changes successfully!").format(len(changes)))

    def update_table_display(self):
        """Update the table display based on current Unicode display mode."""
        if not self.all_translations or not self.all_locales:
            return
            
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
                
            msgid = self.table.item(row, 0).text()
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                group = self.all_translations.get(msgid)
                if group:
                    value = group.get_translation(locale)
                    if value:
                        item = self.table.item(row, col)
                        if item:
                            if self.show_escaped:
                                item.setText(group.get_translation_escaped(locale))
                            else:
                                item.setText(group.get_translation_unescaped(locale))

    def toggle_unicode_display(self):
        """Toggle the Unicode display mode."""
        self.show_escaped = not self.show_escaped
        self.update_table_display()
        # Force UI update
        QTimer.singleShot(0, lambda: self.table.viewport().update()) 