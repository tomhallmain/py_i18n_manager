from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                            QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                            QMessageBox, QMenu, QCheckBox, QTextEdit, QStyledItemDelegate,
                            QFileDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QObject
from PyQt6.QtGui import QAction, QKeyEvent, QShortcut, QKeySequence
from PyQt6.QtWidgets import QApplication
import os
import random
import string

from ui.app_style import AppStyle
from lib.llm import LLMBatchStoppingException
from utils.globals import config_manager
from utils.globals import LLMTranslationMode
from utils.globals import TranslationStatus
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager
from utils.translations import I18N
from ui.base_translation_window import BaseTranslationWindow
from ui.translation_progress_dialog import TranslationProgressDialog
from ui.llm_settings_dialog import LLMSettingsDialog
from ui.quality_review_exclusions_dialog import QualityReviewExclusionsDialog

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


def _display_key(key, max_len=40):
    """Human-readable form of a translation key for progress labels."""
    text = key if isinstance(key, str) else key[1] if isinstance(key, tuple) else str(key)
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def _context_for_key(key, source_text):
    """Only include the key as context when it differs from the source text itself."""
    key_str = key if isinstance(key, str) else key[1] if isinstance(key, tuple) else str(key)
    return f"Translation key: {key_str}" if key_str != source_text else None


class TranslationWorker(QObject):
    """Worker for running translation tasks in a separate thread.

    ``queue`` holds either per-cell items ``(row, col, key, locale, source_text)`` (Argos, or LLM
    in :attr:`LLMTranslationMode.PER_LOCALE` mode - one request per cell), or per-key items
    ``(row, key, source_text, [(col, locale), ...])`` when ``mode`` is
    :attr:`LLMTranslationMode.PER_KEY_ALL_LOCALES` - one LLM request per key covering every
    missing locale for that key at once. ``total`` counts individual missing cells either way, so
    progress reporting is consistent between modes.
    """
    progress_updated = pyqtSignal(int, int, str)  # completed, total, current_key
    translation_completed = pyqtSignal(int, int, str)  # row, col, translated_text
    finished = pyqtSignal()
    error = pyqtSignal(str)
    # message; emitted when the batch stops early due to a provider error that won't resolve by
    # continuing (rate limited, or forbidden e.g. the model requires a paid subscription)
    batch_stopped_error = pyqtSignal(str)

    def __init__(self, translation_service, queue, use_llm=False,
                 mode=LLMTranslationMode.PER_LOCALE, total=None):
        super().__init__()
        self.translation_service = translation_service
        self.queue = queue
        self.use_llm = use_llm
        self.mode = mode
        self._cancelled = False
        self.total = total if total is not None else len(queue)
        self.completed = 0

    def cancel(self):
        """Cancel the translation process."""
        self._cancelled = True
        # Also cancel any ongoing LLM generation (both single- and multi-locale clients)
        if self.use_llm and hasattr(self.translation_service, 'llm'):
            self.translation_service.llm.cancel_generation()
        if self.use_llm and hasattr(self.translation_service, 'llm_multi'):
            self.translation_service.llm_multi.cancel_generation()

    def run(self):
        """Process the translation queue."""
        try:
            is_multi_locale = self.use_llm and self.mode == LLMTranslationMode.PER_KEY_ALL_LOCALES
            while self.queue and not self._cancelled:
                try:
                    if is_multi_locale:
                        self._run_multi_locale_item()
                    else:
                        self._run_single_locale_item()
                except LLMBatchStoppingException as e:
                    # Stop the batch rather than hammering a blocked endpoint through the rest of
                    # the queue. Items already applied via translation_completed are kept.
                    logger.warning(f"Stopping translation batch: {e}")
                    self.batch_stopped_error.emit(str(e))
                    break

            self.progress_updated.emit(self.completed, self.total, "")

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def _run_single_locale_item(self):
        """Translate one (row, col) cell - one LLM/Argos request per missing locale."""
        row, col, key, locale, source_text = self.queue.pop(0)

        self.progress_updated.emit(self.completed, self.total, f"{_display_key(key)} -> {locale}")

        if self._cancelled:
            return

        context = _context_for_key(key, source_text)

        try:
            translated = self.translation_service.translate(
                text=source_text,
                target_locale=locale,
                context=context,
                use_llm=self.use_llm
            )

            if translated and not self._cancelled:
                self.translation_completed.emit(row, col, translated)

        except LLMBatchStoppingException:
            raise
        except Exception as e:
            logger.error(f"Translation failed for {key} to {locale}: {e}")

        self.completed += 1

    def _run_multi_locale_item(self):
        """Translate every missing locale for one key with a single LLM request."""
        row, key, source_text, locale_cols = self.queue.pop(0)
        locales = [locale for _, locale in locale_cols]

        self.progress_updated.emit(
            self.completed, self.total, f"{_display_key(key)} -> {', '.join(locales)}"
        )

        if self._cancelled:
            return

        context = _context_for_key(key, source_text)

        try:
            translations = self.translation_service.translate_with_llm_multi_locale(
                text=source_text,
                target_locales=locales,
                context=context,
            )
            for col, locale in locale_cols:
                translated = translations.get(locale, "")
                if translated and not self._cancelled:
                    self.translation_completed.emit(row, col, translated)

        except LLMBatchStoppingException:
            raise
        except Exception as e:
            logger.error(f"Multi-locale translation failed for {key}: {e}")

        self.completed += len(locale_cols)


class OutstandingItemsWindow(BaseTranslationWindow):
    # Signal now takes a list of (msgid, new_value) tuples for each locale
    translation_updated = pyqtSignal(str, list)  # locale, [(msgid, new_value), ...]
    translation_group_deleted = pyqtSignal(object)  # key object (TranslationKey or str)

    def __init__(self, parent=None, project_path=None):
        super().__init__(parent, title=_("Outstanding Translation Items"), geometry="1200x800")
        # Screen-relative min size; position already set by SmartWindow on parent's display
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
        self._pending_prefill_changes_by_locale = {}

        self.setup_properties()
        self.setup_ui()

    def setup_properties(self):
        self.setup_translation_service(self.project_path)
        self.is_translating = False
        self._translation_worker = None
        self._translation_thread = None
        self._progress_dialog = None

    def _record_prefill_change(self, locale, key, value):
        per_locale = self._pending_prefill_changes_by_locale.setdefault(locale, {})
        per_locale[key] = value

    def _iter_pending_prefill_changes(self):
        for locale, key_to_value in self._pending_prefill_changes_by_locale.items():
            yield locale, list(key_to_value.items())

    def _pending_prefill_update_count(self):
        return sum(len(key_to_value) for key_to_value in self._pending_prefill_changes_by_locale.values())

    def _update_prefill_notice(self):
        count = self._pending_prefill_update_count()
        if count <= 0:
            self.prefill_notice_label.hide()
            return
        self.prefill_notice_label.setText(
            _(
                "Pending duplicate-prefill updates: {count}. These may include keys not currently visible in the table and will be saved."
            ).format(count=count)
        )
        self.prefill_notice_label.show()

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

        self.exclusions_btn = QPushButton(_("Heuristic Exclusions"))
        self.exclusions_btn.clicked.connect(self.open_quality_exclusions)
        self.exclusions_btn.setToolTip(
            _("Manage msgid exclusions and ignore regex patterns for this project.")
        )

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
        button_layout.addWidget(self.exclusions_btn)
        button_layout.addWidget(self.export_tsv_btn)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)
        button_layout.addWidget(self.unicode_toggle)
        layout.addLayout(button_layout)

        self.prefill_notice_label = QLabel("")
        self.prefill_notice_label.setWordWrap(True)
        self.prefill_notice_label.setStyleSheet("color: #d4a017; font-weight: bold;")
        self.prefill_notice_label.hide()
        layout.addWidget(self.prefill_notice_label)
        
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

        fill_missing_with_default = QAction(_("Fill Missing in Row with Default Translation"), self)
        fill_missing_with_default.triggered.connect(
            lambda: self.fill_row_missing_with_default_translation(item.row())
        )
        menu.addAction(fill_missing_with_default)

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

    def fill_row_missing_with_default_translation(self, row: int):
        """Fill empty locale cells in the row with its default locale translation."""
        key = self._get_key_from_row(row)
        group = self.translations.get(key) if hasattr(self, "translations") else None
        if not group:
            return

        default_locale = config_manager.get('translation.default_locale', 'en')
        default_text = group.get_translation_as_text(default_locale)
        if not default_text or not default_text.strip():
            QMessageBox.information(
                self,
                _("No Default Translation"),
                _("The default locale translation is empty for this row."),
            )
            return

        updated_count = 0
        for col in range(1, self.table.columnCount()):
            current_item = self.table.item(row, col)
            current_text = current_item.text().strip() if current_item else ""
            if current_text:
                continue
            self.table.setItem(row, col, QTableWidgetItem(default_text))
            updated_count += 1

        if updated_count == 0:
            QMessageBox.information(
                self,
                _("No Missing Values"),
                _("No missing values were found in this row."),
            )
            return

        QTimer.singleShot(0, lambda: self.table.viewport().update())

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
                self.close()

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

    def _translation_key_for_row(self, row):
        return self._get_key_from_row(row)

    def _get_translations_catalog(self):
        return self.translations

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

    def translate_all_missing(self, use_llm=False):
        """Translate all missing items using the specified method.
        
        Args:
            use_llm (bool): If True, use LLM for translation; otherwise use Argos Translate.
        """
        default_locale = config_manager.get('translation.default_locale', 'en')

        # Group missing cells by row (key) so LLM per-key mode can request every locale for a
        # key in one call. Argos and LLM per-locale mode simply flatten this back to per-cell.
        row_entries = []  # (row, key, source_text, [(col, locale), ...])
        for row in range(self.table.rowCount()):
            key = self._get_key_from_row(row)

            # Get source text for this key
            source_text = None
            if key in self.translations:
                g = self.translations[key]
                raw = g.get_translation('en') or g.get_translation(default_locale)
                source_text = g.value_as_text(raw)

            if not source_text:
                continue

            missing_cols = []
            for col in range(1, self.table.columnCount()):
                locale = self.table.horizontalHeaderItem(col).text()
                item = self.table.item(row, col)

                # Skip if item exists and has content
                if item and item.text().strip():
                    continue

                missing_cols.append((col, locale))

            if missing_cols:
                row_entries.append((row, key, source_text, missing_cols))

        total_missing = sum(len(cols) for _, _, _, cols in row_entries)
        if total_missing == 0:
            QMessageBox.information(self, _("No Items"), _("No missing translations found."))
            return

        mode = LLMTranslationMode.PER_LOCALE
        if use_llm:
            mode = self.settings_manager.get_llm_translation_mode(self.project_path)

        if use_llm and mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
            translation_queue = list(row_entries)
            method_name = _("LLM (all locales per key)")
            confirm_note = _(
                "\n\nThis will make {count} LLM request(s), one per key covering all its "
                "missing locales at once, using model \"{model}\"."
            ).format(count=len(row_entries), model=self.translation_service.llm_multi.model_name)
        else:
            translation_queue = [
                (row, col, key, locale, source_text)
                for row, key, source_text, cols in row_entries
                for col, locale in cols
            ]
            method_name = "LLM" if use_llm else "Argos Translate"
            confirm_note = ""
            if use_llm:
                confirm_note = _(
                    "\n\nThis will make one LLM request per missing locale, using model \"{model}\"."
                ).format(model=self.translation_service.llm.model_name)

        # Show confirmation
        reply = QMessageBox.question(
            self,
            _("Confirm Translation"),
            _("This will translate {count} missing items using {method}.\n\n"
              "LLM translations are higher quality but slower.\n"
              "Argos translations are faster but may be less accurate."
              "{confirm_note}\n\n"
              "Continue?").format(count=total_missing, method=method_name, confirm_note=confirm_note),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.is_translating = True
        self.translate_all_argos_btn.setEnabled(False)
        self.translate_all_llm_btn.setEnabled(False)

        # Create and show progress dialog
        mode_label = None
        if use_llm and mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
            mode_label = _("Mode: all locales per key (model: {model})").format(
                model=self.translation_service.llm_multi.model_name
            )
        elif use_llm:
            mode_label = _("Mode: one locale at a time (model: {model})").format(
                model=self.translation_service.llm.model_name
            )

        self._progress_dialog = TranslationProgressDialog(
            self,
            title=_("Translation Progress"),
            use_llm=use_llm,
            mode_label=mode_label,
        )
        self._progress_dialog.cancelled.connect(self._cancel_translation_worker)

        # Create worker and thread
        self._translation_thread = QThread()
        self._translation_worker = TranslationWorker(
            self.translation_service,
            translation_queue,
            use_llm=use_llm,
            mode=mode,
            total=total_missing,
        )
        self._translation_worker.moveToThread(self._translation_thread)
        
        # Connect signals
        self._translation_thread.started.connect(self._translation_worker.run)
        self._translation_worker.progress_updated.connect(self._on_translation_progress)
        self._translation_worker.translation_completed.connect(self._on_translation_completed)
        self._translation_worker.finished.connect(self._on_translation_finished)
        self._translation_worker.error.connect(self._on_translation_error)
        self._translation_worker.batch_stopped_error.connect(self._on_translation_batch_stopped_error)

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

    def _on_translation_batch_stopped_error(self, message):
        """Handle the batch stopping early because of a provider error that won't resolve by
        continuing (rate limited, or forbidden e.g. the model requires a paid subscription).

        The worker already stopped the queue (see TranslationWorker.run). Rather than popping a
        separate dialog, annotate the progress dialog - it already shows how many items completed
        before the stop - with why it stopped, and leave it open for the user to close manually.
        """
        logger.warning(f"Translation batch stopped early: {message}")
        if self._progress_dialog:
            self._progress_dialog.show_stopped_early_error(
                _(
                    "Translation stopped early: {message}\n\n"
                    "Items completed before this happened (shown above) were kept."
                ).format(message=message)
            )

    def _cancel_translation_worker(self):
        """Cancel the ongoing translation process."""
        if self._translation_worker:
            self._translation_worker.cancel()
            logger.info("Translation cancellation requested")
    
    def open_llm_settings(self):
        """Open the LLM settings dialog."""
        # TODO: Move to base class
        dialog = LLMSettingsDialog(project_path=self.project_path, parent=self)
        dialog.settings_saved.connect(self.reload_translation_service_settings)
        dialog.exec()

    def open_quality_exclusions(self):
        """Open shared exclusions dialog for heuristic/script checks."""
        dialog = QualityReviewExclusionsDialog(
            project_path=self.project_path,
            settings_manager=self.settings_manager,
            parent=self,
        )
        dialog.settings_saved.connect(self._reload_after_exclusions_saved)
        dialog.exec()

    def _reload_after_exclusions_saved(self):
        if hasattr(self, "translations") and hasattr(self, "locales"):
            self.load_data(self.translations, self.locales, skip_duplicate_prompt=True)
        
    def _detect_duplicate_values(self, translations, locales, ignore_patterns=()):
        """Detect duplicate translation values in the default locale.
        
        Returns:
            tuple: (existing_to_outstanding_matches, outstanding_duplicates)
                - existing_to_outstanding_matches: dict mapping default_value to list of (existing_msgid, outstanding_msgid) tuples
                - outstanding_duplicates: dict mapping default_value to list of outstanding msgids
        """
        default_locale = config_manager.get('translation.default_locale', 'en')
        
        # Build map of default locale values to translation keys (normalized text; lists use join)
        value_to_keys = {}
        for key, group in translations.items():
            if not group.is_in_base:
                continue
            default_text = group.get_translation_as_text(default_locale)
            if default_text and default_text.strip():
                if default_text not in value_to_keys:
                    value_to_keys[default_text] = []
                value_to_keys[default_text].append(key)
        
        # Find duplicates (values with multiple keys)
        existing_to_outstanding_matches = {}  # {default_value: [(existing_key, outstanding_key), ...]}
        outstanding_duplicates = {}  # {default_value: [outstanding_keys]}
        
        # Find all outstanding translations (those with errors)
        outstanding_keys = set()
        for key, group in translations.items():
            if not group.is_in_base:
                continue
            invalid_locales = group.get_invalid_translations(
                locales, ignore_patterns=ignore_patterns
            )
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
                            if locale in group.values and group.value_as_text(
                                group.values[locale]
                            ).strip():
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

    @staticmethod
    def _sanitize_export_text(value):
        return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _truncate_export_text(value, max_len=280):
        text = str(value or "")
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    @staticmethod
    def _escape_markdown(value):
        text = str(value or "")
        text = text.replace("\\", "\\\\")
        text = text.replace("|", "\\|")
        text = text.replace("\r", " ").replace("\n", " ")
        return text

    def _format_locale_value_pairs(self, group, locales_set):
        if not locales_set:
            return ""
        ordered = [loc for loc in self.locales if loc in locales_set]
        extras = sorted([loc for loc in locales_set if loc not in self.locales])
        values = []
        for locale in ordered + extras:
            text = group.get_translation_as_text(locale)
            values.append(f"{locale}={self._sanitize_export_text(text)}")
        return " | ".join(values)

    def export_outstanding_to_tsv(self):
        """Export current outstanding rows and invalid locale buckets to a TSV file."""
        if not self._current_invalid_groups:
            QMessageBox.information(self, _("No Data"), _("There are no outstanding rows to export."))
            return

        default_locale = config_manager.get('translation.default_locale', 'en')
        headers = [
            "Translation Key",
            "Default Locale Value",
            "Defined without Error",
            "Missing",
            "Invalid Unicode",
            "Invalid Braces",
            "Invalid Leading Space",
            "Invalid Newline",
            "Invalid Character Set",
            "Invalid Locale Values",
        ]
        markdown_headers = [h for h in headers if h != "Invalid Locale Values"]

        lines = ["\t".join(headers)]
        markdown_rows = []
        markdown_details = []

        for _key, (invalid_locales, group) in self._current_invalid_groups.items():
            # Keep Invalid Unicode aligned with current outstanding UI behavior
            # where invalid indices are grouped as critical with unicode.
            invalid_unicode = set(invalid_locales.invalid_unicode_locales) | set(invalid_locales.invalid_index_locales)
            missing = set(invalid_locales.missing_locales)
            invalid_braces = set(invalid_locales.invalid_brace_locales)
            invalid_leading_space = set(invalid_locales.invalid_leading_space_locales)
            invalid_newline = set(invalid_locales.invalid_newline_locales)
            invalid_character_set = set(invalid_locales.invalid_character_set_locales)

            all_error_locales = (
                missing
                | invalid_unicode
                | invalid_braces
                | invalid_leading_space
                | invalid_newline
                | invalid_character_set
            )

            default_value = group.get_translation_as_text(default_locale)
            defined_without_error = set()
            for locale in self.locales:
                value = group.get_translation(locale)
                vt = group.value_as_text(value)
                if vt and vt.strip() and locale not in all_error_locales:
                    defined_without_error.add(locale)
            # Default locale is often not in self.locales list from header filtering in this window.
            if default_value and default_value.strip() and default_locale not in all_error_locales:
                defined_without_error.add(default_locale)

            invalid_locale_values = self._format_locale_value_pairs(group, all_error_locales)
            invalid_locale_values_tsv = self._truncate_export_text(invalid_locale_values)
            row_values = [
                group.key.msgid,
                default_value,
                self._format_locale_list(defined_without_error),
                self._format_locale_list(missing),
                self._format_locale_list(invalid_unicode),
                self._format_locale_list(invalid_braces),
                self._format_locale_list(invalid_leading_space),
                self._format_locale_list(invalid_newline),
                self._format_locale_list(invalid_character_set),
                invalid_locale_values_tsv,
            ]
            # Keep TSV shape stable (no tabs/newlines in cell content)
            safe_values = [self._sanitize_export_text(v) for v in row_values]
            lines.append("\t".join(safe_values))

            markdown_rows.append(
                {
                    "Translation Key": group.key.msgid,
                    "Default Locale Value": default_value,
                    "Defined without Error": self._format_locale_list(defined_without_error),
                    "Missing": self._format_locale_list(missing),
                    "Invalid Unicode": self._format_locale_list(invalid_unicode),
                    "Invalid Braces": self._format_locale_list(invalid_braces),
                    "Invalid Leading Space": self._format_locale_list(invalid_leading_space),
                    "Invalid Newline": self._format_locale_list(invalid_newline),
                    "Invalid Character Set": self._format_locale_list(invalid_character_set),
                }
            )
            markdown_details.append(
                {
                    "key": group.key.msgid,
                    "default": default_value,
                    "missing": missing,
                    "invalid_unicode": invalid_unicode,
                    "invalid_braces": invalid_braces,
                    "invalid_leading_space": invalid_leading_space,
                    "invalid_newline": invalid_newline,
                    "invalid_character_set": invalid_character_set,
                    "group": group,
                }
            )

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

            md_path = os.path.splitext(file_path)[0] + ".md"
            with open(md_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("# Outstanding Translation Export\n\n")
                f.write("| " + " | ".join(markdown_headers) + " |\n")
                f.write("|" + "|".join(["---"] * len(markdown_headers)) + "|\n")
                for row in markdown_rows:
                    f.write(
                        "| "
                        + " | ".join(
                            self._escape_markdown(row.get(header, ""))
                            for header in markdown_headers
                            )
                        + " |\n"
                    )
                f.write("\n## Invalid Issue Details\n\n")
                for detail in markdown_details:
                    f.write(f"### {self._escape_markdown(detail['key'])}\n")
                    f.write(f"- Default locale value: {self._escape_markdown(detail['default'])}\n")
                    category_rows = [
                        ("Missing locales", detail["missing"]),
                        ("Invalid Unicode locales", detail["invalid_unicode"]),
                        ("Invalid braces locales", detail["invalid_braces"]),
                        ("Invalid leading-space locales", detail["invalid_leading_space"]),
                        ("Invalid newline locales", detail["invalid_newline"]),
                        ("Invalid character-set locales", detail["invalid_character_set"]),
                    ]
                    for label, locales_set in category_rows:
                        if locales_set:
                            f.write(
                                f"- {label}: {self._escape_markdown(self._format_locale_list(locales_set))}\n"
                            )
                    f.write(
                        f"- Invalid locale values: {self._escape_markdown(self._format_locale_value_pairs(detail['group'], detail['missing'] | detail['invalid_unicode'] | detail['invalid_braces'] | detail['invalid_leading_space'] | detail['invalid_newline'] | detail['invalid_character_set']))}\n\n"
                    )

            QMessageBox.information(
                self,
                _("Export Complete"),
                _("Exported {count} outstanding key(s) to:\n{path}\n\nMarkdown companion:\n{md_path}").format(
                    count=len(self._current_invalid_groups),
                    path=file_path,
                    md_path=md_path,
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
        self._pending_prefill_changes_by_locale = {}
        self._update_prefill_notice()

        # Get default locale and exclude it from the list
        default_locale = config_manager.get('translation.default_locale', 'en')
        display_locales = [loc for loc in locales if loc != default_locale]

        # Set up columns (first column is msgid, then one for each non-default locale)
        self.table.setColumnCount(len(display_locales) + 1)
        headers = ["Translation Key"] + display_locales
        self.table.setHorizontalHeaderLabels(headers)

        # Set dynamic column widths based on number of locales
        self.set_dynamic_column_widths(len(display_locales))

        ignore_patterns = tuple(
            self.settings_manager.get_quality_review_script_ignore_patterns(
                self.project_path
            )
            if getattr(self, "project_path", None)
            else ()
        )

        # Find all translations with missing or invalid entries (key = translations dict key)
        all_invalid_groups = {}
        for key, group in translations.items():
            if not group.is_in_base:
                continue

            invalid_locales = group.get_invalid_translations(
                locales, ignore_patterns=ignore_patterns
            )
            if invalid_locales.has_errors:
                all_invalid_groups[key] = (invalid_locales, group)

        # Detect duplicate values
        existing_to_outstanding_matches, outstanding_duplicates = self._detect_duplicate_values(
            translations, locales, ignore_patterns=ignore_patterns
        )

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
                            if locale in existing_group.values and existing_group.value_as_text(
                                existing_group.values[locale]
                            ).strip():
                                new_value = existing_group.values[locale]
                                old_value = outstanding_group.get_translation(locale) or ""
                                outstanding_group.add_translation(locale, new_value)
                                if new_value != old_value:
                                    self._record_prefill_change(locale, outstanding_key, new_value)
                                    logger.debug(f"Pre-filled {outstanding_key} in {locale} from {existing_key}")
                                    pre_filled_keys.add(outstanding_key)
                self._update_prefill_notice()
                
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

                    invalid_locales = group.get_invalid_translations(
                        locales, ignore_patterns=ignore_patterns
                    )
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
                    queued_prefill_updates = sum(
                        len(changes) for _, changes in self._iter_pending_prefill_changes()
                    )
                    QMessageBox.information(
                        self,
                        _("All Translations Resolved"),
                        f"All outstanding translation(s) were automatically filled from existing translations with matching default values.\n\n"
                        f"Resolved {resolved_count} outstanding translation key(s). No outstanding translations remain.\n\n"
                        f"Queued {queued_prefill_updates} pre-filled locale update(s) for save.",
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
                item = QTableWidgetItem(group.get_translation_as_text(locale))

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
                      locale in invalid_locales.invalid_character_set_locales):
                    item.setBackground(style_color)
                    if locale in invalid_locales.invalid_brace_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_BRACES.get_translated_value())
                    if locale in invalid_locales.invalid_leading_space_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_LEADING_SPACE.get_translated_value())
                    if locale in invalid_locales.invalid_newline_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_NEWLINE.get_translated_value())
                    if locale in invalid_locales.invalid_character_set_locales:
                        tooltip_parts.append(TranslationStatus.INVALID_CHARACTER_SET.get_translated_value())

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
            pending_prefill_count = self._pending_prefill_update_count()
            if pending_prefill_count > 0:
                reply = QMessageBox.question(
                    self,
                    _("Save includes hidden duplicate-prefill updates"),
                    _(
                        "This save will also persist {count} pre-filled duplicate update(s), including keys that may not be visible in the current table.\n\nContinue?"
                    ).format(count=pending_prefill_count),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
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
                    logger.debug("Reinitializing translation service...")
                    self.setup_translation_service(self.project_path)
                except Exception as e:
                    logger.error(f"Error during translation service cleanup/reinitialization: {e}")
            
            logger.debug("Processing table changes...")
            logger.debug(f"Duplicate groups tracked: {len(self.outstanding_duplicate_groups)}")
            
            # Collect all changes first, grouped by locale
            changes_by_locale = {}
            
            for row in range(self.table.rowCount()):
                key = self._get_key_from_row(row)
                
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
            
            # Emit one batch per locale
            merged_changes_by_locale = {}
            for locale, changes in changes_by_locale.items():
                merged_changes_by_locale[locale] = {key: value for key, value in changes}
            for locale, changes in self._iter_pending_prefill_changes():
                key_to_value = merged_changes_by_locale.setdefault(locale, {})
                for key, value in changes:
                    # If user edited same key in table, keep explicit table edit.
                    key_to_value.setdefault(key, value)
            self._pending_prefill_changes_by_locale = {}
            self._update_prefill_notice()

            logger.debug(f"Emitting batches for {len(merged_changes_by_locale)} locales...")
            for i, (locale, key_to_value) in enumerate(merged_changes_by_locale.items()):
                changes = list(key_to_value.items())
                logger.debug(f"Emitting batch of {len(changes)} updates for locale {locale}")
                self.translation_updated.emit(locale, changes)
                if i < len(merged_changes_by_locale) - 1:  # Don't sleep after the last one
                    QThread.msleep(100)  # 100ms delay between locales

            # If this save contains only key deletions (no text edits), flush queued deletions now.
            parent = self.parent()
            if parent and hasattr(parent, "process_batched_updates"):
                logger.debug(
                    "Outstanding save complete; closing window and immediately processing batched updates."
                )
                self.close()
                QTimer.singleShot(0, parent.process_batched_updates)
                return

            # Fallback path when parent cannot process updates: keep previous in-window behavior.
            has_items = self.load_data(self.translations, self.locales, skip_duplicate_prompt=True)
            if not has_items:
                logger.debug("No remaining outstanding translations; closing window.")
                self.close()
                
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
                    if group.get_translation(locale):
                        item = self.table.item(row, col)
                        if item:
                            txt = (
                                group.get_translation_escaped_as_text(locale)
                                if self.show_escaped
                                else group.get_translation_unescaped_as_text(locale)
                            )
                            item.setText(txt)

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