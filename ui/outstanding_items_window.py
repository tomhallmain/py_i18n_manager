from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QMenu, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QColor, QAction
from utils.config import ConfigManager
from lib.translation_service import TranslationService
from utils.utils import Utils
from utils.translations import I18N

_ = I18N._

class OutstandingItemsWindow(QDialog):
    # Signal now takes a list of (msgid, new_value) tuples for each locale
    translation_updated = pyqtSignal(str, list)  # locale, [(msgid, new_value), ...]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Outstanding Translation Items"))
        self.setMinimumSize(800, 600)
        self.config = ConfigManager()
        self.translation_service = TranslationService()
        self.is_translating = False
        self.show_escaped = False
        self.setup_ui()
        
    def closeEvent(self, event):
        """Handle cleanup when the window is closed."""
        if self.is_translating:
            reply = QMessageBox.question(self, _('Translation in Progress'),
                                       _('Translation is in progress. Are you sure you want to close?'),
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
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
        self.translate_all_btn = QPushButton(_("Translate All Missing"))
        self.translate_all_btn.clicked.connect(self.translate_all_missing)
        
        self.cancel_btn = QPushButton(_("Cancel Translation"))
        self.cancel_btn.clicked.connect(self.cancel_translation)
        self.cancel_btn.setEnabled(False)
        
        save_btn = QPushButton(_("Save Changes"))
        save_btn.clicked.connect(self.save_changes)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        
        # Add Unicode display toggle
        self.unicode_toggle = QCheckBox(_("Show Escaped Unicode"))
        self.unicode_toggle.stateChanged.connect(self.toggle_unicode_display)
        
        button_layout.addWidget(self.translate_all_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        button_layout.addWidget(self.unicode_toggle)
        layout.addLayout(button_layout)
        
    def show_context_menu(self, position):
        """Show context menu for translation options."""
        item = self.table.itemAt(position)
        if not item:
            return
            
        menu = QMenu()
        translate_action = QAction(_("Translate This Item"), self)
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
                    # Force UI update
                    QTimer.singleShot(0, lambda: self.table.viewport().update())
                    return
            except Exception as e:
                if attempt == 0:  # First attempt failed, will retry
                    continue
                print(f"Translation failed for {msgid} to {locale}: {e}")
                
    def translate_all_missing(self):
        """Translate all missing items."""
        self.is_translating = True
        self.translate_all_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        
        # Create a list of items to translate
        self.translation_queue = []
        for row in range(self.table.rowCount()):
            msgid = self.table.item(row, 0).text()
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                item = self.table.item(row, col)
                
                # Skip if item exists and has content
                if item and item.text().strip():
                    continue
                    
                self.translation_queue.append((row, col, msgid, locale))
        
        # Start processing the queue
        self.process_translation_queue()
        
    def process_translation_queue(self):
        """Process the next item in the translation queue."""
        if not self.is_translating or not self.translation_queue:
            self.is_translating = False
            self.translate_all_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            return
            
        row, col, msgid, locale = self.translation_queue.pop(0)
        self.translate_item(row, col, msgid, locale)
        
        # Schedule the next item to be processed
        QTimer.singleShot(100, self.process_translation_queue)
        
    def cancel_translation(self):
        """Cancel the ongoing translation process."""
        self.is_translating = False
        self.translation_queue.clear()
        self.translate_all_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
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
            # Collect all changes first, grouped by locale
            changes_by_locale = {}
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
                            if locale not in changes_by_locale:
                                changes_by_locale[locale] = []
                            changes_by_locale[locale].append((msgid, new_value))
                        elif len(item.text()) > 0:
                            Utils.log_yellow(f"Empty translation with spaces for {msgid} in {locale}")
            
            # Emit one batch per locale
            Utils.log(f"Emitting batches for {len(changes_by_locale)} locales...")
            for i, (locale, changes) in enumerate(changes_by_locale.items()):
                Utils.log(f"Emitting batch of {len(changes)} updates for locale {locale}")
                self.translation_updated.emit(locale, changes)
                if i < len(changes_by_locale) - 1:  # Don't sleep after the last one
                    QThread.msleep(100)  # 100ms delay between locales
            
            Utils.log("All changes processed, accepting dialog...")
            self.accept()
        except Exception as e:
            Utils.log_red(f"Error during save changes: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save changes: {e}") 

    def update_table_display(self):
        """Update the table display based on current Unicode display mode."""
        if not hasattr(self, 'translations'):
            return
            
        for row in range(self.table.rowCount()):
            msgid = self.table.item(row, 0).text()
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                group = self.translations.get(msgid)
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