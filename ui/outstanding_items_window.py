from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QAction
from utils.config import ConfigManager
from lib.translation_service import TranslationService
from utils.utils import Utils

class OutstandingItemsWindow(QDialog):
    translation_updated = pyqtSignal(str, str, str)  # msgid, locale, new_value
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Outstanding Translation Items")
        self.setMinimumSize(800, 600)
        self.config = ConfigManager()
        self.translation_service = TranslationService()
        self.setup_ui()
        
    def closeEvent(self, event):
        """Handle cleanup when the window is closed."""
        if hasattr(self, 'translation_service'):
            del self.translation_service
        super().closeEvent(event)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Table for translations
        self.table = QTableWidget()
        self.table.setColumnCount(0)  # Will be set when data is loaded
        self.table.setRowCount(0)     # Will be set when data is loaded
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.table)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Translation buttons
        translate_all_btn = QPushButton("Translate All Missing")
        translate_all_btn.clicked.connect(self.translate_all_missing)
        
        save_btn = QPushButton("Save Changes")
        save_btn.clicked.connect(self.save_changes)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        
        button_layout.addWidget(translate_all_btn)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
    def show_context_menu(self, position):
        """Show context menu for translation options."""
        item = self.table.itemAt(position)
        if not item:
            return
            
        menu = QMenu()
        translate_action = QAction("Translate This Item", self)
        translate_action.triggered.connect(lambda: self.translate_selected_item(item))
        menu.addAction(translate_action)
        menu.exec(self.table.mapToGlobal(position))
        
    def translate_selected_item(self, item):
        """Translate a single selected item."""
        row = item.row()
        col = item.column()
        if col == 0:  # Don't translate the key column
            return
            
        msgid = self.table.item(row, 0).text()
        locale = self.table.horizontalHeaderItem(col).text()
        self.translate_item(row, col, msgid, locale)
        
    def translate_item(self, row, col, msgid, locale):
        """Translate a single item and update the table."""
        # Get the English translation if available, otherwise use default locale
        default_locale = self.config.get('translation.default_locale', 'en')
        source_text = self.translations[msgid].get_translation('en') or self.translations[msgid].get_translation(default_locale)
        
        if not source_text:
            return
            
        # Try translation once, retry once if it fails
        for attempt in range(2):
            try:
                translated = self.translation_service.translate(
                    text=source_text,
                    target_locale=locale,
                    context=f"Translation key: {msgid}"
                )
                if translated:
                    item = QTableWidgetItem(translated)
                    self.table.setItem(row, col, item)
                    return
            except Exception as e:
                if attempt == 0:  # First attempt failed, will retry
                    continue
                print(f"Translation failed for {msgid} to {locale}: {e}")
                
    def translate_all_missing(self):
        """Translate all missing items."""
        for row in range(self.table.rowCount()):
            msgid = self.table.item(row, 0).text()
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                item = self.table.item(row, col)
                
                # Skip if item exists and has content
                if item and item.text().strip():
                    continue
                    
                self.translate_item(row, col, msgid, locale)
        
    def load_data(self, translations, locales):
        """Load translation data into the table."""
        # Store translations for later use
        self.translations = translations
        
        # Get default locale and exclude it from the list
        default_locale = self.config.get('translation.default_locale', 'en')
        display_locales = [loc for loc in locales if loc != default_locale]
        
        # Set up columns (first column is msgid, then one for each non-default locale)
        self.table.setColumnCount(len(display_locales) + 1)
        headers = ["Translation Key"] + display_locales
        self.table.setHorizontalHeaderLabels(headers)
        
        # Find all translations with missing or invalid entries
        rows = []
        for msgid, group in translations.items():
            if not group.is_in_base:
                continue
            missing_locales = group.get_missing_locales(locales)
            invalid_unicode = group.get_invalid_unicode_locales()
            invalid_indices = group.get_invalid_index_locales()
            
            if missing_locales or invalid_unicode or invalid_indices:
                rows.append((msgid, group))
        
        # Set up rows
        self.table.setRowCount(len(rows))
        
        # Define custom colors
        missing_color = QColor(255, 200, 200)  # Light pink
        unicode_color = QColor(255, 255, 200)  # Light yellow
        index_color = QColor(200, 255, 255)    # Light cyan
        
        # Fill in data
        for row, (msgid, group) in enumerate(rows):
            # Add msgid
            msgid_item = QTableWidgetItem(msgid)
            msgid_item.setFlags(msgid_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, msgid_item)
            
            # Add translations for each locale (excluding default)
            for col, locale in enumerate(display_locales, 1):
                value = group.get_translation(locale)
                item = QTableWidgetItem(value)
                
                # Highlight problematic cells with custom colors
                if locale in group.get_missing_locales(locales):
                    item.setBackground(missing_color)
                elif locale in group.get_invalid_unicode_locales():
                    item.setBackground(unicode_color)
                elif locale in group.get_invalid_index_locales():
                    item.setBackground(index_color)
                
                self.table.setItem(row, col, item)
        
        # Adjust column widths
        self.table.resizeColumnsToContents()
        
    def save_changes(self):
        """Save changes to the translations."""
        try:
            Utils.log("Starting save changes process...")
            
            # First, ensure translation service is cleaned up
            if hasattr(self, 'translation_service'):
                Utils.log("Cleaning up translation service...")
                try:
                    if hasattr(self.translation_service, '_executor'):
                        Utils.log("Shutting down translation service executor...")
                        self.translation_service._executor.shutdown(wait=True)
                    if hasattr(self.translation_service, 'llm'):
                        Utils.log("Cleaning up LLM instance...")
                        if hasattr(self.translation_service.llm, '_loop'):
                            self.translation_service.llm._loop.close()
                    Utils.log("Deleting translation service...")
                    del self.translation_service
                except Exception as e:
                    Utils.log_red(f"Error during translation service cleanup: {e}")
            
            Utils.log("Processing table changes...")
            # Collect all changes first
            changes = []
            for row in range(self.table.rowCount()):
                msgid = self.table.item(row, 0).text()
                for col in range(1, self.table.columnCount()):
                    locale = self.table.horizontalHeaderItem(col).text()
                    item = self.table.item(row, col)
                    if item:
                        new_value = item.text().strip()
                        # Only include if the value is non-empty
                        if len(new_value) > 0:
                            Utils.log(f"Collecting translation update for {msgid} in {locale}")
                            changes.append((msgid, locale, new_value))
                        elif len(item.text()) > 0:
                            Utils.log_yellow(f"Empty translation with spaces for {msgid} in {locale}")
            
            # Emit all changes after collection with delays between each
            Utils.log(f"Emitting {len(changes)} translation updates...")
            for i, (msgid, locale, new_value) in enumerate(changes):
                self.translation_updated.emit(msgid, locale, new_value)
                Utils.log(f"Emitted update {i+1}/{len(changes)}")
                if i < len(changes) - 1:  # Don't sleep after the last one
                    QThread.msleep(100)  # 100ms delay between emissions
            
            Utils.log("All changes processed, accepting dialog...")
            self.accept()
        except Exception as e:
            Utils.log_red(f"Error during save changes: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save changes: {e}") 