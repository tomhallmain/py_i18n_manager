from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QMenu, QCheckBox, QTextEdit, QStyledItemDelegate)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QColor, QAction, QKeyEvent
from PyQt6.QtWidgets import QApplication

from lib.translation_service import TranslationService
from utils.config import ConfigManager
from utils.globals import TranslationStatus
from utils.translations import I18N
from utils.utils import Utils
from ui.base_translation_window import BaseTranslationWindow

_ = I18N._

class MultilineItemDelegate(QStyledItemDelegate):
    """A delegate that supports multiline editing in table cells."""
    def createEditor(self, parent, option, index):
        editor = QTextEdit(parent)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        return editor
        
    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        editor.setText(value)
        
    def setModelData(self, editor, model, index):
        value = editor.toPlainText()
        model.setData(index, value, Qt.ItemDataRole.EditRole)
        
    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)
        
    def eventFilter(self, editor, event):
        """Filter events to handle Shift+Enter for newlines."""
        if event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    # Insert newline on Shift+Enter
                    editor.insertPlainText("\n")
                    return True
                else:
                    # Regular Enter - finish editing
                    editor.clearFocus()
                    return True
        return super().eventFilter(editor, event)

class OutstandingItemsWindow(BaseTranslationWindow):
    # Signal now takes a list of (msgid, new_value) tuples for each locale
    translation_updated = pyqtSignal(str, list)  # locale, [(msgid, new_value), ...]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Outstanding Translation Items"))

        # Get screen dimensions and set window size
        screen = QApplication.primaryScreen().geometry()
        self.setMinimumSize(int(screen.width() * 0.8), int(screen.height() * 0.8))  # 80% of screen size
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))  # 90% of screen size

        self.config = ConfigManager()

        self.show_escaped = False  # By default it should be encoded, not escaped
        self.setup_properties()
        self.setup_ui()

    def setup_properties(self):
        self.default_locale = self.config.get('translation.default_locale', 'en')
        self.translation_service = TranslationService(default_locale=self.default_locale)
        self.is_translating = False

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
        self.table = self.setup_table()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        # Enable context menu for header
        self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        
        # Set row height to accommodate multiple lines
        self.table.verticalHeader().setDefaultSectionSize(100)
        
        # Set the delegate for multiline editing
        self.table.setItemDelegate(MultilineItemDelegate())
        
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
        self.unicode_toggle.setChecked(self.show_escaped)
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
        
        # Add Copy Text option first
        copy_text = QAction(_("Copy Text"), self)
        copy_text.triggered.connect(lambda: self.copy_cell_text(item))
        menu.addAction(copy_text)
        
        # Add Copy Default Translation option
        default_locale = self.config.get('translation.default_locale', 'en')
        copy_default = QAction(_("Copy Default Translation"), self)
        copy_default.triggered.connect(lambda: self.copy_default_translation(item, default_locale))
        menu.addAction(copy_default)
        
        # Only show translation options for non-key column cells
        if item.column() > 0:
            menu.addSeparator()
            # Add Argos Translate option
            translate_with_argos = QAction(_("Translate with Argos Translate"), self)
            translate_with_argos.triggered.connect(lambda: self.translate_selected_item(item, use_llm=False))
            menu.addAction(translate_with_argos)
            
            # Add LLM Translate option
            translate_with_llm = QAction(_("Translate with LLM"), self)
            translate_with_llm.triggered.connect(lambda: self.translate_selected_item(item, use_llm=True))
            menu.addAction(translate_with_llm)
        
        menu.exec(self.table.mapToGlobal(position))

    def show_header_context_menu(self, position):
        """Show context menu for header items."""
        # Get the column index at the position
        column = self.table.horizontalHeader().logicalIndexAt(position)
        if column < 0:
            return
            
        # Create menu
        menu = QMenu()
        
        # Add Copy Text option
        copy_text = QAction(_("Copy Text"), self)
        header_text = self.table.horizontalHeaderItem(column).text()
        copy_text.triggered.connect(lambda: self.copy_text_to_clipboard(header_text))
        menu.addAction(copy_text)
        
        menu.exec(self.table.horizontalHeader().mapToGlobal(position))

    def copy_cell_text(self, item):
        """Copy the text from a cell to the clipboard."""
        if item:
            self.copy_text_to_clipboard(item.text())

    def copy_text_to_clipboard(self, text):
        """Copy the given text to the clipboard."""
        QApplication.clipboard().setText(text)

    def copy_default_translation(self, item, default_locale):
        """Copy the default locale's translation for the selected item.
        
        Args:
            item: The table item that was right-clicked
            default_locale (str): The default locale code
        """
        row = item.row()
        msgid = self.table.item(row, 0).text()
        if msgid in self.translations:
            default_text = self.translations[msgid].get_translation(default_locale)
            if default_text:
                self.copy_text_to_clipboard(default_text)

    def translate_selected_item(self, item, use_llm=False):
        """Translate a single selected item.
        
        Args:
            item: The table item to translate
            use_llm (bool): Whether to use LLM for translation
        """
        row = item.row()
        col = item.column()
        if col == 0:  # Don't translate the key column
            return
            
        msgid = self.table.item(row, 0).text()
        locale = self.table.horizontalHeaderItem(col).text()
        self.translate_item(row, col, msgid, locale, use_llm)

    def translate_item(self, row, col, msgid, locale, use_llm=False):
        """Translate a single item and update the table.
        
        Args:
            row (int): The row number in the table
            col (int): The column number in the table
            msgid (str): The translation key
            locale (str): The target locale
            use_llm (bool): Whether to use LLM for translation
        """
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
                    context=f"Translation key: {msgid}",
                    use_llm=use_llm
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
        self.translations = translations

        # Get default locale and exclude it from the list
        default_locale = self.config.get('translation.default_locale', 'en')
        display_locales = [loc for loc in locales if loc != default_locale]

        # Set up columns (first column is msgid, then one for each non-default locale)
        self.table.setColumnCount(len(display_locales) + 1)
        headers = ["Translation Key"] + display_locales
        self.table.setHorizontalHeaderLabels(headers)

        # Set dynamic column widths based on number of locales
        self.set_dynamic_column_widths(len(display_locales))

        # Find all translations with missing or invalid entries
        all_invalid_groups = {}
        for msgid, group in translations.items():
            if not group.is_in_base:
                continue

            invalid_locales = group.get_invalid_translations(locales)
            if invalid_locales.has_errors:
                all_invalid_groups[group.key] = (invalid_locales, group)

        self.table.setRowCount(len(all_invalid_groups))
        
        # Define custom colors
        missing_color = QColor(255, 255, 200)    # Light yellow for missing translations
        critical_color = QColor(255, 200, 200)   # Light red for critical issues (unicode/indices)
        style_color = QColor(255, 220, 180)      # Light orange for style issues

        for row, (invalid_locales, group) in enumerate(all_invalid_groups.values()):
            msgid_item = QTableWidgetItem(group.key)
            msgid_item.setFlags(msgid_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, msgid_item)

            # Add translations for each locale (excluding default)
            for col, locale in enumerate(display_locales, 1):
                value = group.get_translation(locale)
                item = QTableWidgetItem(value)

                # Build tooltip text for invalid statuses
                tooltip_parts = []

                # Highlight problematic cells with custom colors
                if locale in invalid_locales.missing_locales:
                    item.setBackground(missing_color)
                    tooltip_parts.append(TranslationStatus.MISSING.get_translated_value())

                elif (locale in invalid_locales.invalid_unicode_locales or 
                      locale in invalid_locales.invalid_index_locales):
                    item.setBackground(critical_color)
                    if locale in invalid_locales.invalid_unicode_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_UNICODE.get_translated_value())
                    else:
                        tooltip_parts.append(TranslationStatus.INVALID_INDICES.get_translated_value())

                elif (locale in invalid_locales.invalid_brace_locales or
                      locale in invalid_locales.invalid_leading_space_locales or
                      locale in invalid_locales.invalid_newline_locales):
                    item.setBackground(style_color)
                    if locale in invalid_locales.invalid_brace_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_BRACES.get_translated_value())
                    if locale in invalid_locales.invalid_leading_space_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_LEADING_SPACE.get_translated_value())
                    if locale in invalid_locales.invalid_newline_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_NEWLINE.get_translated_value())

                if tooltip_parts:
                    item.setToolTip("\n".join(tooltip_parts))

                self.table.setItem(row, col, item)

        self.table.resizeColumnsToContents()

    def save_changes(self):
        """Save changes to the translations."""
        try:
            Utils.log("Starting save changes process...")
            
            # Store current column widths
            column_widths = [self.table.columnWidth(i) for i in range(self.table.columnCount())]
            
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
                    
                    # Reinitialize translation service
                    Utils.log("Reinitializing translation service...")
                    default_locale = self.config.get('translation.default_locale', 'en')
                    self.translation_service = TranslationService(default_locale=default_locale)
                except Exception as e:
                    Utils.log_red(f"Error during translation service cleanup/reinitialization: {e}")
            
            Utils.log("Processing table changes...")
            # Collect all changes first, grouped by locale
            changes_by_locale = {}
            has_remaining_empty = False
            rows_to_remove = []
            
            for row in range(self.table.rowCount()):
                msgid = self.table.item(row, 0).text()
                row_complete = True
                
                for col in range(1, self.table.columnCount()):
                    locale = self.table.horizontalHeaderItem(col).text()
                    item = self.table.item(row, col)
                    if item:
                        new_value = item.text()
                        # Only include if the value is non-empty
                        if len(new_value) > 0:
                            Utils.log(f"Collecting translation update for {msgid} in {locale}")
                            if locale not in changes_by_locale:
                                changes_by_locale[locale] = []
                            changes_by_locale[locale].append((msgid, new_value))
                        else:
                            row_complete = False
                            has_remaining_empty = True
                            if len(item.text()) > 0:
                                Utils.log_yellow(f"Empty translation with spaces for {msgid} in {locale}")
                
                # If all cells in this row have translations, mark it for removal
                if row_complete:
                    rows_to_remove.append(row)
            
            # Emit one batch per locale
            Utils.log(f"Emitting batches for {len(changes_by_locale)} locales...")
            for i, (locale, changes) in enumerate(changes_by_locale.items()):
                Utils.log(f"Emitting batch of {len(changes)} updates for locale {locale}")
                self.translation_updated.emit(locale, changes)
                if i < len(changes_by_locale) - 1:  # Don't sleep after the last one
                    QThread.msleep(100)  # 100ms delay between locales
            
            # Remove completed rows in reverse order to maintain correct indices
            for row in sorted(rows_to_remove, reverse=True):
                self.table.removeRow(row)
            
            # Restore column widths
            for i, width in enumerate(column_widths):
                self.table.setColumnWidth(i, width)
            
            # Only close the dialog if there are no remaining empty translations
            if has_remaining_empty:
                Utils.log("There are still empty translations remaining...")
            else:
                Utils.log("No remaining empty translations, accepting dialog...")
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