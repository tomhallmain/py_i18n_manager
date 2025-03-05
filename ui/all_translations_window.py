from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QLineEdit, QComboBox)
from PyQt6.QtCore import Qt, pyqtSignal

class AllTranslationsWindow(QDialog):
    translation_updated = pyqtSignal(str, str, str)  # msgid, locale, new_value
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("All Translations")
        self.setMinimumSize(1000, 700)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Search and filter controls
        controls_layout = QHBoxLayout()
        
        # Search box
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search translation keys...")
        self.search_box.textChanged.connect(self.filter_table)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
        controls_layout.addLayout(search_layout)
        
        # Status filter
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Missing", "Invalid Unicode", "Invalid Indices"])
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
        save_btn = QPushButton("Save Changes")
        save_btn.clicked.connect(self.save_changes)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        # Store original data
        self.all_translations = None
        self.all_locales = None
        
    def load_data(self, translations, locales):
        """Load translation data into the table.
        
        Args:
            translations: Dict of msgid -> TranslationGroup
            locales: List of locale codes
        """
        # Store original data for filtering
        self.all_translations = translations
        self.all_locales = locales
        
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
            
            # Add translations for each locale
            for col, locale in enumerate(locales, 1):
                value = group.get_translation(locale)
                item = QTableWidgetItem(value)
                
                # Highlight problematic cells
                if locale in group.get_missing_locales(locales):
                    item.setBackground(Qt.GlobalColor.red)
                elif locale in group.get_invalid_unicode_locales():
                    item.setBackground(Qt.GlobalColor.yellow)
                elif locale in group.get_invalid_index_locales():
                    item.setBackground(Qt.GlobalColor.cyan)
                
                self.table.setItem(row, col, item)
        
        # Adjust column widths
        self.table.resizeColumnsToContents()
        
    def filter_table(self):
        """Filter the table based on search text and status filter."""
        if not self.all_translations or not self.all_locales:
            return
            
        search_text = self.search_box.text().lower()
        status_filter = self.status_filter.currentText()
        
        for row in range(self.table.rowCount()):
            show_row = True
            
            # Apply search filter
            if search_text:
                msgid = self.table.item(row, 0).text().lower()
                if search_text not in msgid:
                    show_row = False
            
            # Apply status filter
            if show_row and status_filter != "All":
                has_status = False
                for col in range(1, self.table.columnCount()):
                    item = self.table.item(row, col)
                    if status_filter == "Missing" and item.background().color() == Qt.GlobalColor.red:
                        has_status = True
                        break
                    elif status_filter == "Invalid Unicode" and item.background().color() == Qt.GlobalColor.yellow:
                        has_status = True
                        break
                    elif status_filter == "Invalid Indices" and item.background().color() == Qt.GlobalColor.cyan:
                        has_status = True
                        break
                if not has_status:
                    show_row = False
            
            self.table.setRowHidden(row, not show_row)
        
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
            QMessageBox.information(self, "Info", "No changes to save.")
            return
        
        # Emit changes
        for msgid, locale, new_value in changes:
            self.translation_updated.emit(msgid, locale, new_value)
        
        QMessageBox.information(self, "Success", f"Saved {len(changes)} changes successfully!") 