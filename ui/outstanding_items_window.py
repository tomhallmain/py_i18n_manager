from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QMenu, QCheckBox, QTextEdit, QStyledItemDelegate,
                            QFileDialog,
                            QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QObject
from PyQt6.QtGui import QAction, QKeyEvent, QShortcut, QKeySequence
from PyQt6.QtWidgets import QApplication
import os
import random
import string

from lib.translation_service import TranslationService
from ui.app_style import AppStyle
from utils.globals import config_manager
from utils.globals import TranslationStatus
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager
from utils.translations import I18N
from ui.base_translation_window import BaseTranslationWindow
from ui.llm_settings_dialog import LLMSettingsDialog

_ = I18N._

logger = get_logger(__name__)

# Minimum column widths: key column fits keys like "en.views.projects.created_at"; others slightly less
KEY_COLUMN_MIN_WIDTH = 200
OTHER_COLUMN_MIN_WIDTH = 120

class MultilineItemDelegate(QStyledItemDelegate):
    """A delegate that supports multiline editing in table cells."""
    def createEditor(self, parent, option, index):
        editor = QTextEdit(parent)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        editor.setAcceptRichText(False)
        return editor
        
    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        editor.setPlainText(value if value is not None else "")
        
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


class TranslationWorker(QObject):
    """Worker for running translation tasks in a separate thread."""
    progress_updated = pyqtSignal(int, int, str)  # completed, total, current_key
    translation_completed = pyqtSignal(int, int, str)  # row, col, translated_text
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self, translation_service, queue, use_llm=False):
        super().__init__()
        self.translation_service = translation_service
        self.queue = queue
        self.use_llm = use_llm
        self._cancelled = False
        self.total = len(queue)
        self.completed = 0
        
    def cancel(self):
        """Cancel the translation process."""
        self._cancelled = True
        # Also cancel any ongoing LLM generation
        if self.use_llm and hasattr(self.translation_service, 'llm'):
            self.translation_service.llm.cancel_generation()
    
    def run(self):
        """Process the translation queue."""
        try:
            while self.queue and not self._cancelled:
                row, col, key, locale, source_text = self.queue.pop(0)
                
                # Display key for progress
                display_key = key if isinstance(key, str) else key[1] if isinstance(key, tuple) else str(key)
                if len(display_key) > 40:
                    display_key = display_key[:37] + "..."
                
                self.progress_updated.emit(self.completed, self.total, f"{display_key} -> {locale}")
                
                if self._cancelled:
                    break
                
                # Build smart context - only include key if it differs from source text
                key_str = key if isinstance(key, str) else key[1] if isinstance(key, tuple) else str(key)
                if key_str != source_text:
                    context = f"Translation key: {key_str}"
                else:
                    context = None  # Key is same as source, no extra context needed
                
                # Perform translation
                try:
                    translated = self.translation_service.translate(
                        text=source_text,
                        target_locale=locale,
                        context=context,
                        use_llm=self.use_llm
                    )
                    
                    if translated and not self._cancelled:
                        self.translation_completed.emit(row, col, translated)
                        
                except Exception as e:
                    logger.error(f"Translation failed for {key} to {locale}: {e}")
                
                self.completed += 1
                
            self.progress_updated.emit(self.completed, self.total, "")
            
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class TranslationProgressDialog(QDialog):
    """Dialog showing translation progress with cancel option."""
    
    cancelled = pyqtSignal()
    
    def __init__(self, parent=None, title="Translation Progress", use_llm=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self.use_llm = use_llm
        
        # Prevent closing via X button while active
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Method label
        method_text = "LLM" if self.use_llm else "Argos Translate"
        self.method_label = QLabel(f"Translation Method: {method_text}")
        self.method_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.method_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Count label
        self.count_label = QLabel("0 / 0 translations completed")
        layout.addWidget(self.count_label)
        
        # Current item label
        self.current_label = QLabel("Preparing...")
        self.current_label.setWordWrap(True)
        self.current_label.setStyleSheet("color: gray;")
        layout.addWidget(self.current_label)
        
        # Cancel button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QPushButton(_("Cancel"))
        self.cancel_btn.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
    def update_progress(self, completed, total, current_item):
        """Update the progress display."""
        if total > 0:
            percentage = int((completed / total) * 100)
            self.progress_bar.setValue(percentage)
        
        self.count_label.setText(f"{completed} / {total} translations completed")
        
        if current_item:
            self.current_label.setText(f"Translating: {current_item}")
        else:
            self.current_label.setText("Finished" if completed >= total else "Preparing...")
    
    def on_cancel(self):
        """Handle cancel button click."""
        reply = QMessageBox.question(
            self, 
            _("Cancel Translation"),
            _("Are you sure you want to cancel the translation process?\n\nCompleted translations will be kept."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(_("Cancelling..."))
            self.current_label.setText("Cancelling translation process...")
            self.cancelled.emit()
    
    def on_finished(self):
        """Handle when translation is finished."""
        self.cancel_btn.setText(_("Close"))
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)
        # Re-enable close button
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowCloseButtonHint)
        self.show()  # Refresh window flags


class OutstandingItemsWindow(BaseTranslationWindow):
    # Signal now takes a list of (msgid, new_value) tuples for each locale
    translation_updated = pyqtSignal(str, list)  # locale, [(msgid, new_value), ...]
    translation_group_deleted = pyqtSignal(object)  # key object (TranslationKey or str)

    def __init__(self, parent=None, project_path=None):
        super().__init__(parent, title=_("Outstanding Translation Items"), geometry="1200x800")
        # Screen-relative min size; position already set by SmartDialog on parent's display
        screen = QApplication.primaryScreen().geometry()
        self.setMinimumSize(int(screen.width() * 0.8), int(screen.height() * 0.8))
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))

        self.project_path = project_path
        self.show_escaped = False  # By default it should be encoded, not escaped
        # Track duplicate value matches: {default_value: [list of msgids]}
        self.duplicate_value_groups = {}
        # Track which outstanding translation represents a group: {displayed_msgid: [all_matched_msgids]}
        self.outstanding_duplicate_groups = {}
        # Minimum width for first column (Translation Key); set in load_data
        self._min_key_column_width = KEY_COLUMN_MIN_WIDTH
        self._last_combine_duplicates_choice = "no"
        self._current_invalid_groups = {}

        self.setup_properties()
        self.setup_ui()

    def setup_properties(self):
        self.default_locale = config_manager.get('translation.default_locale', 'en')
        self.settings_manager = SettingsManager()
        
        # Load prompt template (project-specific or global)
        prompt_template = self.settings_manager.get_llm_prompt_template(self.project_path)
        cjk_reject_threshold = self.settings_manager.get_llm_cjk_reject_threshold_percentage(self.project_path)
        self.translation_service = TranslationService(
            default_locale=self.default_locale,
            prompt_template=prompt_template,
            cjk_reject_threshold_percentage=cjk_reject_threshold,
            project_path=self.project_path,
        )
        
        self.is_translating = False
        self._translation_worker = None
        self._translation_thread = None
        self._progress_dialog = None

    def closeEvent(self, event):
        """Handle cleanup when the window is closed."""
        if self.is_translating:
            reply = QMessageBox.question(self, _('Translation in Progress'),
                                       _('Translation is in progress. Are you sure you want to close?'),
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            # Cancel ongoing translation
            self._cancel_translation_worker()
        if hasattr(self, 'translation_service'):
            del self.translation_service
        super().closeEvent(event)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Translation buttons
        self.translate_all_argos_btn = QPushButton(_("Translate All (Argos)"))
        self.translate_all_argos_btn.clicked.connect(lambda: self.translate_all_missing(use_llm=False))
        self.translate_all_argos_btn.setToolTip(_("Translate all missing items using Argos Translate (fast, offline)"))
        
        self.translate_all_llm_btn = QPushButton(_("Translate All (LLM)"))
        self.translate_all_llm_btn.clicked.connect(lambda: self.translate_all_missing(use_llm=True))
        self.translate_all_llm_btn.setToolTip(_("Translate all missing items using LLM (slower, higher quality)"))
        
        self.llm_settings_btn = QPushButton(_("LLM Settings"))
        self.llm_settings_btn.clicked.connect(self.open_llm_settings)
        self.llm_settings_btn.setToolTip(_("Configure LLM translation prompt template"))

        self.export_tsv_btn = QPushButton(_("Export Outstanding TSV"))
        self.export_tsv_btn.clicked.connect(self.export_outstanding_to_tsv)
        self.export_tsv_btn.setToolTip(_("Export outstanding keys and invalid locale buckets to TSV"))
        
        save_btn = QPushButton(_("Save Changes"))
        save_btn.clicked.connect(self.save_changes)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        
        # Add Unicode display toggle
        self.unicode_toggle = QCheckBox(_("Show Escaped Unicode"))
        self.unicode_toggle.setChecked(self.show_escaped)
        self.unicode_toggle.stateChanged.connect(self.toggle_unicode_display)
        
        button_layout.addWidget(self.translate_all_argos_btn)
        button_layout.addWidget(self.translate_all_llm_btn)
        button_layout.addWidget(self.llm_settings_btn)
        button_layout.addWidget(self.export_tsv_btn)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        button_layout.addWidget(self.unicode_toggle)
        layout.addLayout(button_layout)
        
        # Table for translations
        self.table = self.setup_table()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        if hasattr(self.table, "_frozen_table"):
            self.table._frozen_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table._frozen_table.customContextMenuRequested.connect(self.show_frozen_context_menu)
        # Enable context menu for header
        self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        if hasattr(self.table, "_frozen_table"):
            self.table._frozen_table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table._frozen_table.horizontalHeader().customContextMenuRequested.connect(self.show_frozen_header_context_menu)
        # Enforce minimum width on first column when user resizes (set in load_data)
        self.table.horizontalHeader().sectionResized.connect(self._clamp_key_column_width)
        
        # Set row height to accommodate multiple lines
        self.table.verticalHeader().setDefaultSectionSize(100)
        
        # Set the delegate for multiline editing
        self.table.setItemDelegate(MultilineItemDelegate())
        
        # Add keyboard shortcut for testing: F5 to fill all cells with random strings
        fill_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F5), self)
        fill_shortcut.activated.connect(self.fill_all_cells_with_random_strings)
        
        layout.addWidget(self.table)

    def toggle_unicode_display(self, state):
        """Toggle between escaped and unescaped Unicode display."""
        self.show_escaped = state == Qt.CheckState.Checked.value
        self.update_table_display()

    def show_context_menu(self, position):
        """Show context menu for translation options."""
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
        
        # Add Copy Text option first
        copy_text = QAction(_("Copy Text"), self)
        copy_text.triggered.connect(lambda: self.copy_cell_text(item))
        menu.addAction(copy_text)
        
        # Add Copy Default Translation option
        default_locale = config_manager.get('translation.default_locale', 'en')
        copy_default = QAction(_("Copy Default Translation"), self)
        copy_default.triggered.connect(lambda: self.copy_default_translation(item, default_locale))
        menu.addAction(copy_default)

        menu.addSeparator()
        delete_key = QAction(_("Delete Translation Key"), self)
        delete_key.triggered.connect(lambda: self.delete_translation_group_for_row(item.row()))
        menu.addAction(delete_key)
        
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
        
        menu.exec(global_position)

    def delete_translation_group_for_row(self, row: int):
        """Delete translation group represented by a table row."""
        key = self._get_key_from_row(row)
        item = self.table.item(row, 0)
        key_display = item.text() if item else str(key)

        keys_to_delete = self.outstanding_duplicate_groups.get(key, [key])
        if len(keys_to_delete) > 1:
            key_display = f"{key_display} (+{len(keys_to_delete) - 1} duplicate keys)"

        if not self.confirm_delete_translation_group(key_display):
            return

        deleted_any = False
        for del_key in keys_to_delete:
            if del_key in self.translations:
                del self.translations[del_key]
                self.translation_group_deleted.emit(del_key)
                deleted_any = True

        if deleted_any:
            has_items = self.load_data(self.translations, self.locales, skip_duplicate_prompt=True)
            if not has_items:
                # Special case: only deletions remained. Force immediate persistence.
                parent = self.parent()
                if parent and hasattr(parent, "process_batched_updates"):
                    logger.debug("Outstanding list exhausted after delete; triggering immediate batched update")
                    QTimer.singleShot(0, parent.process_batched_updates)
                self.accept()

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

    def show_frozen_header_context_menu(self, position):
        """Show context menu for frozen first-column header."""
        header = self.table._frozen_table.horizontalHeader()
        menu = QMenu()
        copy_text = QAction(_("Copy Text"), self)
        header_item = self.table.horizontalHeaderItem(0)
        header_text = header_item.text() if header_item else ""
        copy_text.triggered.connect(lambda: self.copy_text_to_clipboard(header_text))
        menu.addAction(copy_text)
        menu.exec(header.mapToGlobal(position))

    def _clamp_key_column_width(self, logical_index: int, _old_size: int, new_size: int):
        """Keep the first column (Translation Key) at or above its content-based minimum."""
        if logical_index != 0:
            return
        min_w = getattr(self, "_min_key_column_width", None)
        if min_w is not None and new_size < min_w:
            self.table.setColumnWidth(0, min_w)

    def set_dynamic_column_widths(self, num_locales: int):
        """Override: key column has a fixed minimum width and is resizable; other columns slightly less."""
        super().set_dynamic_column_widths(num_locales)
        # Key column: minimum width to fit keys like "en.views.projects.created_at", resizable
        self.table.setColumnWidth(0, KEY_COLUMN_MIN_WIDTH)
        self.table.horizontalHeader().setMinimumSectionSize(OTHER_COLUMN_MIN_WIDTH)
        self.table.horizontalHeader().setMaximumSectionSize(800)

    def copy_cell_text(self, item):
        """Copy the text from a cell to the clipboard."""
        if item:
            self.copy_text_to_clipboard(item.text())

    def copy_text_to_clipboard(self, text):
        """Copy the given text to the clipboard."""
        QApplication.clipboard().setText(text)

    def _get_key_from_row(self, row):
        """Extract the translation key from a table row (stored in UserRole when populated).
        Falls back to display text for backward compatibility (e.g. Ruby where key is string).
        
        Args:
            row (int): The row number
            
        Returns:
            The translation key (str for Ruby, (context, msgid) for Python with context)
        """
        item = self.table.item(row, 0)
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if key is not None:
            return key
        msgid_display = item.text() if item else ""
        # Extract original by removing "(N duplicates)" suffix if present
        if " (" in msgid_display and " duplicates)" in msgid_display:
            return msgid_display.split(" (")[0]
        return msgid_display

    def copy_default_translation(self, item, default_locale):
        """Copy the default locale's translation for the selected item.
        
        Args:
            item: The table item that was right-clicked
            default_locale (str): The default locale code
        """
        row = item.row()
        key = self._get_key_from_row(row)
        if key in self.translations:
            default_text = self.translations[key].get_translation(default_locale)
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
            
        key = self._get_key_from_row(row)
        locale = self.table.horizontalHeaderItem(col).text()
        self.translate_item(row, col, key, locale, use_llm)

    def translate_item(self, row, col, key, locale, use_llm=False):
        """Translate a single item and update the table.
        
        Args:
            row (int): The row number in the table
            col (int): The column number in the table
            key: The translation key (str or (context, msgid) for Python)
            locale (str): The target locale
            use_llm (bool): Whether to use LLM for translation
        """
        # Get the English translation if available, otherwise use default locale
        default_locale = config_manager.get('translation.default_locale', 'en')
        source_text = self.translations[key].get_translation('en') or self.translations[key].get_translation(default_locale)

        if not source_text:
            return

        # Build smart context - only include key if it differs from source text
        key_str = key if isinstance(key, str) else key[1] if isinstance(key, tuple) else str(key)
        if key_str != source_text:
            context = f"Translation key: {key_str}"
        else:
            context = None  # Key is same as source, no extra context needed

        # Try translation once, retry once if it fails
        for attempt in range(2):
            try:
                translated = self.translation_service.translate(
                    text=source_text,
                    target_locale=locale,
                    context=context,
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
                logger.error(f"Translation failed for {key} to {locale}: {e}")

    def translate_all_missing(self, use_llm=False):
        """Translate all missing items using the specified method.
        
        Args:
            use_llm (bool): If True, use LLM for translation; otherwise use Argos Translate.
        """
        # Create a list of items to translate with source text
        translation_queue = []
        default_locale = config_manager.get('translation.default_locale', 'en')
        
        for row in range(self.table.rowCount()):
            key = self._get_key_from_row(row)
            
            # Get source text for this key
            source_text = None
            if key in self.translations:
                source_text = self.translations[key].get_translation('en') or self.translations[key].get_translation(default_locale)
            
            if not source_text:
                continue
                
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                item = self.table.item(row, col)
                
                # Skip if item exists and has content
                if item and item.text().strip():
                    continue
                    
                translation_queue.append((row, col, key, locale, source_text))
        
        if not translation_queue:
            QMessageBox.information(self, _("No Items"), _("No missing translations found."))
            return
        
        # Show confirmation
        method_name = "LLM" if use_llm else "Argos Translate"
        reply = QMessageBox.question(
            self,
            _("Confirm Translation"),
            _("This will translate {count} missing items using {method}.\n\n"
              "LLM translations are higher quality but slower.\n"
              "Argos translations are faster but may be less accurate.\n\n"
              "Continue?").format(count=len(translation_queue), method=method_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.is_translating = True
        self.translate_all_argos_btn.setEnabled(False)
        self.translate_all_llm_btn.setEnabled(False)
        
        # Create and show progress dialog
        self._progress_dialog = TranslationProgressDialog(
            self, 
            title=_("Translation Progress"), 
            use_llm=use_llm
        )
        self._progress_dialog.cancelled.connect(self._cancel_translation_worker)
        
        # Create worker and thread
        self._translation_thread = QThread()
        self._translation_worker = TranslationWorker(
            self.translation_service, 
            translation_queue, 
            use_llm=use_llm
        )
        self._translation_worker.moveToThread(self._translation_thread)
        
        # Connect signals
        self._translation_thread.started.connect(self._translation_worker.run)
        self._translation_worker.progress_updated.connect(self._on_translation_progress)
        self._translation_worker.translation_completed.connect(self._on_translation_completed)
        self._translation_worker.finished.connect(self._on_translation_finished)
        self._translation_worker.error.connect(self._on_translation_error)
        
        # Start the thread
        self._translation_thread.start()
        self._progress_dialog.show()
    
    def _on_translation_progress(self, completed, total, current_item):
        """Handle progress updates from the worker."""
        if self._progress_dialog:
            self._progress_dialog.update_progress(completed, total, current_item)
    
    def _on_translation_completed(self, row, col, translated_text):
        """Handle a completed translation."""
        item = QTableWidgetItem(translated_text)
        self.table.setItem(row, col, item)
        # Force UI update
        QTimer.singleShot(0, lambda: self.table.viewport().update())
    
    def _on_translation_finished(self):
        """Handle when translation process is finished."""
        self.is_translating = False
        self.translate_all_argos_btn.setEnabled(True)
        self.translate_all_llm_btn.setEnabled(True)
        
        if self._progress_dialog:
            self._progress_dialog.on_finished()
        
        # Clean up thread
        if self._translation_thread:
            self._translation_thread.quit()
            self._translation_thread.wait()
            self._translation_thread = None
        
        self._translation_worker = None
    
    def _on_translation_error(self, error_msg):
        """Handle translation errors."""
        logger.error(f"Translation error: {error_msg}")
        QMessageBox.warning(self, _("Translation Error"), 
                          _("An error occurred during translation:\n{error}").format(error=error_msg))
    
    def _cancel_translation_worker(self):
        """Cancel the ongoing translation process."""
        if self._translation_worker:
            self._translation_worker.cancel()
            logger.info("Translation cancellation requested")
    
    def open_llm_settings(self):
        """Open the LLM settings dialog."""
        dialog = LLMSettingsDialog(project_path=self.project_path, parent=self)
        dialog.settings_saved.connect(self._reload_prompt_template)
        dialog.exec()
    
    def _reload_prompt_template(self):
        """Reload the prompt template after settings change."""
        prompt_template = self.settings_manager.get_llm_prompt_template(self.project_path)
        cjk_reject_threshold = self.settings_manager.get_llm_cjk_reject_threshold_percentage(self.project_path)
        self.translation_service.set_prompt_template(prompt_template)
        self.translation_service.set_cjk_reject_threshold_percentage(cjk_reject_threshold)
        logger.info("LLM translation settings reloaded")
        
    def _detect_duplicate_values(self, translations, locales):
        """Detect duplicate translation values in the default locale.
        
        Returns:
            tuple: (existing_to_outstanding_matches, outstanding_duplicates)
                - existing_to_outstanding_matches: dict mapping default_value to list of (existing_msgid, outstanding_msgid) tuples
                - outstanding_duplicates: dict mapping default_value to list of outstanding msgids
        """
        default_locale = config_manager.get('translation.default_locale', 'en')
        
        # Build map of default locale values to translation keys
        value_to_keys = {}
        for key, group in translations.items():
            if not group.is_in_base:
                continue
            default_value = group.get_translation(default_locale)
            if default_value and default_value.strip():
                if default_value not in value_to_keys:
                    value_to_keys[default_value] = []
                value_to_keys[default_value].append(key)
        
        # Find duplicates (values with multiple keys)
        existing_to_outstanding_matches = {}  # {default_value: [(existing_key, outstanding_key), ...]}
        outstanding_duplicates = {}  # {default_value: [outstanding_keys]}
        
        # Find all outstanding translations (those with errors)
        outstanding_keys = set()
        for key, group in translations.items():
            if not group.is_in_base:
                continue
            invalid_locales = group.get_invalid_translations(locales)
            if invalid_locales.has_errors:
                outstanding_keys.add(key)
        
        # Check for matches
        for default_value, keys in value_to_keys.items():
            if len(keys) > 1:
                # This value appears in multiple keys
                existing_keys = []
                outstanding_keys_for_value = []
                
                for key in keys:
                    # Check if this translation has existing translations for non-default locales
                    group = translations[key]
                    has_existing_translations = False
                    for locale in locales:
                        if locale != default_locale:
                            if locale in group.values and group.values[locale].strip():
                                has_existing_translations = True
                                break
                    
                    if key in outstanding_keys:
                        outstanding_keys_for_value.append(key)
                    elif has_existing_translations:
                        existing_keys.append(key)
                
                # If we have both existing and outstanding, create matches
                if existing_keys and outstanding_keys_for_value:
                    if default_value not in existing_to_outstanding_matches:
                        existing_to_outstanding_matches[default_value] = []
                    for outstanding_key in outstanding_keys_for_value:
                        for existing_key in existing_keys:
                            existing_to_outstanding_matches[default_value].append((existing_key, outstanding_key))
                
                # If we have multiple outstanding with same value, track them
                if len(outstanding_keys_for_value) > 1:
                    outstanding_duplicates[default_value] = outstanding_keys_for_value
        
        return existing_to_outstanding_matches, outstanding_duplicates
    
    def _ask_combine_duplicates(self, existing_to_outstanding_count, outstanding_duplicates_count):
        """Ask user if they want to combine duplicate translations.
        
        Args:
            existing_to_outstanding_count: Number of matches between existing and outstanding
            outstanding_duplicates_count: Number of duplicate groups in outstanding translations
            
        Returns:
            str: One of "yes", "no", "cancel". "cancel" means user closed the dialog (X/Escape)
                 and the outstanding window should not open.
        """
        total_matches = existing_to_outstanding_count + outstanding_duplicates_count
        if total_matches == 0:
            return "no"
        
        message_parts = []
        if existing_to_outstanding_count > 0:
            message_parts.append(f"{existing_to_outstanding_count} match(es) between existing translations and outstanding translations")
        if outstanding_duplicates_count > 0:
            message_parts.append(f"{outstanding_duplicates_count} duplicate value group(s) in outstanding translations")
        
        message = (
            f"Found {total_matches} duplicate translation value(s) in the default locale:\n\n"
            f"{' | '.join(message_parts)}\n\n"
            "Would you like to combine these translations to avoid re-translation?\n\n"
            "- Yes: Pre-fill from existing translations and group duplicates (one row per value)\n"
            "- No: Open without combining; show all outstanding items\n"
            "- Cancel: Do not open Outstanding Translations"
        )
        
        msgbox = QMessageBox(self)
        msgbox.setWindowTitle(_("Combine Duplicate Translations?"))
        msgbox.setText(message)
        msgbox.setStandardButtons(
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel
        )
        msgbox.setDefaultButton(QMessageBox.StandardButton.Yes)
        msgbox.setEscapeButton(QMessageBox.StandardButton.Cancel)
        
        reply = msgbox.exec()
        
        if reply == QMessageBox.StandardButton.Yes:
            return "yes"
        if reply == QMessageBox.StandardButton.No:
            return "no"
        # Cancel, or X, or Escape
        return "cancel"

    def _format_locale_list(self, locales_set):
        """Format locale sets in the current locale order."""
        if not locales_set:
            return ""
        ordered = [loc for loc in self.locales if loc in locales_set]
        # Include any unexpected locales not present in self.locales
        extras = sorted([loc for loc in locales_set if loc not in self.locales])
        return ", ".join(ordered + extras)

    def export_outstanding_to_tsv(self):
        """Export current outstanding rows and invalid locale buckets to a TSV file."""
        if not self._current_invalid_groups:
            QMessageBox.information(self, _("No Data"), _("There are no outstanding rows to export."))
            return

        default_locale = config_manager.get('translation.default_locale', 'en')
        headers = [
            "Translation Key",
            "Defined without Error",
            "Missing",
            "Invalid Unicode",
            "Invalid Braces",
            "Invalid Leading Space",
            "Invalid Newline",
            "Invalid CJK",
        ]

        lines = ["\t".join(headers)]

        for _key, (invalid_locales, group) in self._current_invalid_groups.items():
            # Keep Invalid Unicode aligned with current outstanding UI behavior
            # where invalid indices are grouped as critical with unicode.
            invalid_unicode = set(invalid_locales.invalid_unicode_locales) | set(invalid_locales.invalid_index_locales)
            missing = set(invalid_locales.missing_locales)
            invalid_braces = set(invalid_locales.invalid_brace_locales)
            invalid_leading_space = set(invalid_locales.invalid_leading_space_locales)
            invalid_newline = set(invalid_locales.invalid_newline_locales)
            invalid_cjk = set(invalid_locales.invalid_cjk_locales)

            all_error_locales = (
                missing
                | invalid_unicode
                | invalid_braces
                | invalid_leading_space
                | invalid_newline
                | invalid_cjk
            )

            defined_without_error = set()
            for locale in self.locales:
                value = group.get_translation(locale)
                if value and value.strip() and locale not in all_error_locales:
                    defined_without_error.add(locale)
            # Default locale is often not in self.locales list from header filtering in this window.
            default_value = group.get_translation(default_locale)
            if default_value and default_value.strip() and default_locale not in all_error_locales:
                defined_without_error.add(default_locale)

            row_values = [
                group.key.msgid,
                self._format_locale_list(defined_without_error),
                self._format_locale_list(missing),
                self._format_locale_list(invalid_unicode),
                self._format_locale_list(invalid_braces),
                self._format_locale_list(invalid_leading_space),
                self._format_locale_list(invalid_newline),
                self._format_locale_list(invalid_cjk),
            ]
            # Keep TSV shape stable (no tabs/newlines in cell content)
            safe_values = [str(v).replace("\t", " ").replace("\r", " ").replace("\n", " ") for v in row_values]
            lines.append("\t".join(safe_values))

        default_name = os.path.join(self.project_path or "", "outstanding_translation_keys.tsv")
        dialog_result = QFileDialog.getSaveFileName(
            self,
            _("Export Outstanding TSV"),
            default_name,
            _("TSV Files (*.tsv);;All Files (*)"),
        )
        file_path = dialog_result[0]
        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write("\n".join(lines) + "\n")
            QMessageBox.information(
                self,
                _("Export Complete"),
                _("Exported {count} outstanding key(s) to:\n{path}").format(
                    count=len(self._current_invalid_groups),
                    path=file_path
                ),
            )
        except Exception as e:
            logger.error(f"Failed to export outstanding TSV: {e}")
            QMessageBox.critical(
                self,
                _("Export Failed"),
                _("Could not export TSV file:\n{error}").format(error=str(e)),
            )

    def load_data(self, translations, locales, skip_duplicate_prompt=False):
        """Load translation data into the table.
        
        translations is the manager's in-memory dict (by reference). Choosing "Yes"
        on the combine-duplicates dialog pre-fills that dict in place, so the manager
        becomes dirty immediately; nothing is reverted by closing this window without
        saving. The window itself is a view only—each open calls load_data with the
        current manager state, so it does not hold persistent dirty state.
        
        Returns:
            bool: True if there are items to display (caller should open the window),
                  False if nothing to show (e.g. user chose Cancel, or all resolved).
        """
        self.translations = translations
        self.locales = locales
        logger.debug("Resetting duplicate groups at start of load_data")
        self.outstanding_duplicate_groups = {}  # Reset duplicate groups

        # Get default locale and exclude it from the list
        default_locale = config_manager.get('translation.default_locale', 'en')
        display_locales = [loc for loc in locales if loc != default_locale]

        # Set up columns (first column is msgid, then one for each non-default locale)
        self.table.setColumnCount(len(display_locales) + 1)
        headers = ["Translation Key"] + display_locales
        self.table.setHorizontalHeaderLabels(headers)

        # Set dynamic column widths based on number of locales
        self.set_dynamic_column_widths(len(display_locales))

        # Find all translations with missing or invalid entries (key = translations dict key)
        all_invalid_groups = {}
        for key, group in translations.items():
            if not group.is_in_base:
                continue

            invalid_locales = group.get_invalid_translations(locales)
            if invalid_locales.has_errors:
                all_invalid_groups[key] = (invalid_locales, group)

        # Detect duplicate values
        existing_to_outstanding_matches, outstanding_duplicates = self._detect_duplicate_values(translations, locales)

        # Ask user once, then reuse the last choice for silent refreshes.
        combine_reply = "no"
        if existing_to_outstanding_matches or outstanding_duplicates:
            if skip_duplicate_prompt:
                combine_reply = self._last_combine_duplicates_choice or "no"
                if combine_reply == "cancel":
                    combine_reply = "no"
            else:
                combine_reply = self._ask_combine_duplicates(
                    len(existing_to_outstanding_matches), len(outstanding_duplicates)
                )
                if combine_reply == "cancel":
                    # User closed dialog (X) or chose Cancel: do not open outstanding window
                    return False
                self._last_combine_duplicates_choice = combine_reply

            if combine_reply == "yes":
                # Pre-fill outstanding translations from existing translations
                pre_filled_keys = set()  # Track which outstanding keys were pre-filled
                for default_value, matches in existing_to_outstanding_matches.items():
                    for existing_key, outstanding_key in matches:
                        existing_group = translations[existing_key]
                        outstanding_group = translations[outstanding_key]
                        
                        # Copy translations from existing to outstanding for all non-default locales
                        for locale in display_locales:
                            if locale in existing_group.values and existing_group.values[locale].strip():
                                outstanding_group.add_translation(locale, existing_group.values[locale])
                                logger.debug(f"Pre-filled {outstanding_key} in {locale} from {existing_key}")
                                pre_filled_keys.add(outstanding_key)
                
                # Track outstanding duplicates - we'll show only one of each group
                for default_value, duplicate_keys in outstanding_duplicates.items():
                    # Use the first key as the representative
                    representative_key = duplicate_keys[0]
                    # Store all matched keys
                    self.outstanding_duplicate_groups[representative_key] = duplicate_keys
                    logger.debug(f"Grouped duplicate outstanding translations: {representative_key} represents {duplicate_keys}")
                    default_value_display = default_value[:50] + "..." if len(default_value) > 50 else default_value
                    logger.debug(f"  Default value: '{default_value_display}'")
                    logger.debug(f"  Will show only '{representative_key}' in table, apply to all {len(duplicate_keys)} keys on save")
                
                # Re-check invalid translations after pre-filling (they may now be resolved)
                all_invalid_groups = {}
                for key, group in translations.items():
                    if not group.is_in_base:
                        continue

                    invalid_locales = group.get_invalid_translations(locales)
                    if invalid_locales.has_errors:
                        all_invalid_groups[key] = (invalid_locales, group)
                
                # Filter out duplicate outstanding translations (keep only representative)
                filtered_invalid_groups = {}
                excluded_keys = set()
                for key, (invalid_locales, group) in all_invalid_groups.items():
                    # Check if this key is part of a duplicate group (but not the representative)
                    is_excluded = False
                    for rep_key, matched_keys in self.outstanding_duplicate_groups.items():
                        if key in matched_keys and key != rep_key:
                            excluded_keys.add(key)
                            is_excluded = True
                            break
                    
                    if not is_excluded:
                        filtered_invalid_groups[key] = (invalid_locales, group)
                
                all_invalid_groups = filtered_invalid_groups
                logger.info(f"Filtered out {len(excluded_keys)} duplicate outstanding translations")
                
                # If all outstanding translations were resolved by pre-filling, show success dialog
                if len(all_invalid_groups) == 0:
                    resolved_count = len(pre_filled_keys)
                    QMessageBox.information(
                        self,
                        _("All Translations Resolved"),
                        f"All outstanding translation(s) were automatically filled from existing translations with matching default values.\n\n"
                        f"Resolved {resolved_count} outstanding translation key(s). No outstanding translations remain.\n\n"
                        f"⚠️ Please remember to run a Translation Update to save the duplicate translations.",
                        QMessageBox.StandardButton.Ok
                    )
                    # Return False to indicate no items to display
                    return False
            # combine_reply == "no": fall through and open window with all items (no combining)

        self._current_invalid_groups = all_invalid_groups
        self.table.setRowCount(len(all_invalid_groups))
        
        AppStyle.sync_theme_from_widget(self)
        highlight_colors = AppStyle.get_translation_highlight_colors()
        missing_color = highlight_colors["missing"]
        critical_color = highlight_colors["critical"]
        style_color = highlight_colors["style"]

        for row, (key, (invalid_locales, group)) in enumerate(all_invalid_groups.items()):
            display_text = group.key.msgid
            msgid_item = QTableWidgetItem(display_text)
            msgid_item.setData(Qt.ItemDataRole.UserRole, key)
            msgid_item.setFlags(msgid_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            # If this key represents a duplicate group, add indicator
            if key in self.outstanding_duplicate_groups:
                matched_keys = self.outstanding_duplicate_groups[key]
                if len(matched_keys) > 1:
                    msgid_item.setText(f"{display_text} ({len(matched_keys)} duplicates)")
                    msgid_item.setToolTip(f"This translation represents {len(matched_keys)} keys with the same default value:\n" + 
                                        "\n".join(f"  • {m}" for m in matched_keys))

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
                      locale in invalid_locales.invalid_newline_locales or
                      locale in invalid_locales.invalid_cjk_locales):
                    item.setBackground(style_color)
                    if locale in invalid_locales.invalid_brace_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_BRACES.get_translated_value())
                    if locale in invalid_locales.invalid_leading_space_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_LEADING_SPACE.get_translated_value())
                    if locale in invalid_locales.invalid_newline_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_NEWLINE.get_translated_value())
                    if locale in invalid_locales.invalid_cjk_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_CJK.get_translated_value())

                if tooltip_parts:
                    item.setToolTip("\n".join(tooltip_parts))

                self.table.setItem(row, col, item)

        # Start every column at its minimum width; user can resize to make them wider
        self.table.setColumnWidth(0, KEY_COLUMN_MIN_WIDTH)
        for col in range(1, self.table.columnCount()):
            self.table.setColumnWidth(col, OTHER_COLUMN_MIN_WIDTH)
        self._min_key_column_width = KEY_COLUMN_MIN_WIDTH
        
        # Return True only when there are rows to display.
        has_items = len(all_invalid_groups) > 0
        if not has_items:
            logger.debug("No outstanding items found after load_data")
        return has_items

    def save_changes(self):
        """Save changes to the translations."""
        try:
            logger.debug("Starting save changes process...")
            
            # Store current column widths
            column_widths = [self.table.columnWidth(i) for i in range(self.table.columnCount())]
            
            # First, ensure translation service is cleaned up
            if hasattr(self, 'translation_service'):
                logger.debug("Cleaning up translation service...")
                try:
                    if hasattr(self.translation_service, '_executor'):
                        logger.debug("Shutting down translation service executor...")
                        self.translation_service._executor.shutdown(wait=True)
                    if hasattr(self.translation_service, 'llm'):
                        logger.debug("Cleaning up LLM instance...")
                        if hasattr(self.translation_service.llm, '_loop'):
                            self.translation_service.llm._loop.close()
                    logger.debug("Deleting translation service...")
                    del self.translation_service
                    
                    # Reinitialize translation service
                    logger.debug("Reinitializing translation service...")
                    default_locale = config_manager.get('translation.default_locale', 'en')
                    prompt_template = self.settings_manager.get_llm_prompt_template(self.project_path)
                    cjk_reject_threshold = self.settings_manager.get_llm_cjk_reject_threshold_percentage(self.project_path)
                    self.translation_service = TranslationService(
                        default_locale=default_locale,
                        prompt_template=prompt_template,
                        cjk_reject_threshold_percentage=cjk_reject_threshold,
                        project_path=self.project_path,
                    )
                except Exception as e:
                    logger.error(f"Error during translation service cleanup/reinitialization: {e}")
            
            logger.debug("Processing table changes...")
            logger.debug(f"Duplicate groups tracked: {len(self.outstanding_duplicate_groups)}")
            
            # Collect all changes first, grouped by locale
            changes_by_locale = {}
            rows_to_remove = []
            
            for row in range(self.table.rowCount()):
                key = self._get_key_from_row(row)
                row_complete = True
                
                for col in range(1, self.table.columnCount()):
                    locale = self.table.horizontalHeaderItem(col).text()
                    item = self.table.item(row, col)
                    if item:
                        new_value = item.text()
                        # Only include if the value is non-empty
                        if len(new_value) > 0:
                            if locale not in changes_by_locale:
                                changes_by_locale[locale] = []
                            changes_by_locale[locale].append((key, new_value))
                            
                            # If this key represents a duplicate group, apply to all matched keys
                            if key in self.outstanding_duplicate_groups:
                                matched_keys = self.outstanding_duplicate_groups[key]
                                for matched_key in matched_keys:
                                    if matched_key != key:  # Don't duplicate the representative
                                        changes_by_locale[locale].append((matched_key, new_value))
                        else:
                            row_complete = False
                            if len(item.text()) > 0:
                                logger.warn(f"Empty translation with spaces for {key} in {locale}")
                
                # If all cells in this row have translations, mark it for removal
                if row_complete:
                    rows_to_remove.append(row)
            
            # Emit one batch per locale
            logger.debug(f"Emitting batches for {len(changes_by_locale)} locales...")
            for i, (locale, changes) in enumerate(changes_by_locale.items()):
                logger.debug(f"Emitting batch of {len(changes)} updates for locale {locale}")
                self.translation_updated.emit(locale, changes)
                if i < len(changes_by_locale) - 1:  # Don't sleep after the last one
                    QThread.msleep(100)  # 100ms delay between locales

            # If this save contains only key deletions (no text edits), flush queued deletions now.
            parent = self.parent()
            if (
                not changes_by_locale
                and parent
                and hasattr(parent, "pending_deletions")
                and parent.pending_deletions
                and hasattr(parent, "process_batched_updates")
            ):
                logger.debug("Save triggered with pending deletions only; processing batched updates now.")
                parent.process_batched_updates()
            
            # Remove completed rows in reverse order to maintain correct indices
            for row in sorted(rows_to_remove, reverse=True):
                self.table.removeRow(row)

            # Re-run validation and repopulate table with any still-invalid entries.
            has_items = self.load_data(self.translations, self.locales, skip_duplicate_prompt=True)
            
            # Restore column widths
            for i, width in enumerate(column_widths):
                self.table.setColumnWidth(i, width)
            
            # Close the dialog only when no outstanding items remain after revalidation.
            if not has_items:
                logger.debug("No remaining outstanding translations, accepting dialog...")
                self.accept()
                
        except Exception as e:
            logger.error(f"Error during save changes: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save changes: {e}")

    def update_table_display(self):
        """Update the table display based on current Unicode display mode."""
        if not hasattr(self, 'translations'):
            return
            
        for row in range(self.table.rowCount()):
            key = self._get_key_from_row(row)
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                group = self.translations.get(key)
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
    
    def fill_all_cells_with_random_strings(self):
        """Fill all translation cells with random strings for testing purposes.
        
        Press F5 to trigger this function. Only fills editable cells (translation columns),
        not the key column (column 0).
        """
        if not hasattr(self, 'table') or self.table.rowCount() == 0:
            return
        
        def generate_random_string(length=6):
            """Generate a random string of given length (default 6 chars)."""
            # Use letters and digits only for the random part
            chars = string.ascii_lowercase + string.digits
            return ''.join(random.choice(chars) for _ in range(length))
        
        filled_count = 0
        for row in range(self.table.rowCount()):
            # Generate one random part per row (so duplicate groups get the same value when saved)
            random_part = generate_random_string()
            
            for col in range(1, self.table.columnCount()):  # Skip column 0 (key column)
                item = self.table.item(row, col)
                if item:
                    # Get locale for this column
                    locale = self.table.horizontalHeaderItem(col).text()
                    
                    # Format: {locale}_{row_index}_{random_string}
                    # Same row index for all locales in this row (ensures duplicate groups match)
                    # Same random part for all locales in this row (ensures duplicate groups match)
                    test_string = f"{locale}_{row}_{random_part}"
                    item.setText(test_string)
                    filled_count += 1
        
        logger.debug(f"Filled {filled_count} cells with random strings (F5 pressed)")
        # Force UI update
        QTimer.singleShot(0, lambda: self.table.viewport().update()) 