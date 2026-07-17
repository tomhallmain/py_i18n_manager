from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                            QLabel, QTableWidgetItem, QProgressBar,
                            QMessageBox, QCheckBox, QTextEdit, QStyledItemDelegate)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QApplication
import random
import string

from ui.app_style import AppStyle
from utils.globals import config_manager
from utils.globals import LLMTranslationMode
from utils.globals import TranslationStatus
from utils.logging_setup import get_logger
from utils.translations import I18N
from ui.translation_windows.base_translation_window import BaseTranslationWindow
from ui.translation_progress_dialog import ETATracker
from ui.llm_settings_dialog import LLMSettingsDialog
from ui.quality_review_exclusions_dialog import QualityReviewExclusionsDialog
from ui.translation_windows.replace_key_window import ReplaceKeyWindow
from ui.translation_windows.outstanding_items import context_menus, tsv_export
from ui.translation_windows.outstanding_items.duplicate_prefill import (
    DuplicatePrefillState,
    ask_combine_duplicates,
    detect_duplicate_values,
)
from ui.translation_windows.outstanding_items.translation_orchestrator import (
    BackgroundTranslationController,
)

_ = I18N._

logger = get_logger(__name__)

# Minimum column widths: key column fits keys like "en.views.projects.created_at"; others slightly less
KEY_COLUMN_MIN_WIDTH = 200
OTHER_COLUMN_MIN_WIDTH = 120


def _format_eta_seconds(secs: float) -> str:
    """Human-readable "~N remaining" text for the inline batch-translate progress strip."""
    s = int(secs)
    if s < 60:
        return _("{s} sec").format(s=s)
    m, s = divmod(s, 60)
    if m < 60:
        return _("{m} min {s} sec").format(m=m, s=f"{s:02d}")
    h, m = divmod(m, 60)
    return _("{h} hr {m} min").format(h=h, m=f"{m:02d}")


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
        # Minimum width for first column (Translation Key); set in load_data
        self._min_key_column_width = KEY_COLUMN_MIN_WIDTH
        self._current_invalid_groups = {}
        # key -> current table row; rebuilt on every load_data() call. Lets a background batch
        # resolve where a result belongs *now* instead of trusting a row index captured when the
        # queue was built (see translation_orchestrator.BackgroundTranslationController).
        self._key_to_row = {}
        self._prefill = DuplicatePrefillState()

        self.setup_properties()
        self.setup_ui()

    def setup_properties(self):
        self.setup_translation_service(self.project_path)
        self.is_translating = False
        self._translation_controller = None
        self._batch_eta = None

    def closeEvent(self, event):
        """Handle cleanup when the window is closed."""
        if self.is_translating:
            reply = QMessageBox.question(self, _('Translation in Progress'),
                                       _('Translation is in progress. Are you sure you want to close?'),
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self._detach_translation_controller()
        if hasattr(self, 'translation_service'):
            del self.translation_service
        super().closeEvent(event)

    def _detach_translation_controller(self):
        """Cancel the running batch and stop it from reaching back into this window.

        Deliberately does not wait for the thread: the in-flight Argos/LLM call for the current
        item can't be interrupted mid-request (LLM.cancel_generation only joins its own internal
        thread with a short timeout, best-effort), so blocking here would freeze the window on
        close. The controller's worker/thread clean themselves up independently via their own
        finished -> quit/deleteLater connections (see BackgroundTranslationController.start)
        once the in-flight item settles or the next queue check sees the cancel flag -- this
        just disconnects the signals that reach back into this window first, so a
        'progress_updated'/'translation_completed'/'finished' emission that arrives after this
        window is gone doesn't try to update a closed widget.
        """
        controller = self._translation_controller
        if not controller:
            return
        controller.cancel()
        for signal, slot in (
            (controller.progress_updated, self._on_translation_progress),
            (controller.translation_completed, self._on_translation_completed),
            (controller.finished, self._on_translation_finished),
            (controller.error, self._on_translation_error),
            (controller.batch_stopped_error, self._on_translation_batch_stopped_error),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._translation_controller = None
        self._reset_batch_controls()

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

        self.replace_key_btn = QPushButton(_("Replace Key"))
        self.replace_key_btn.clicked.connect(self.open_replace_key_window)
        self.replace_key_btn.setToolTip(
            _("Replace the selected translation key with a new one, carrying over its translations")
        )

        self.save_btn = QPushButton(_("Save Changes"))
        self.save_btn.clicked.connect(self.save_changes)
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
        button_layout.addWidget(self.replace_key_btn)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(close_btn)
        button_layout.addWidget(self.unicode_toggle)
        layout.addLayout(button_layout)

        self.prefill_notice_label = QLabel("")
        self.prefill_notice_label.setWordWrap(True)
        self.prefill_notice_label.setStyleSheet("color: #d4a017; font-weight: bold;")
        self.prefill_notice_label.hide()
        layout.addWidget(self.prefill_notice_label)

        # Inline batch-translate progress -- replaces the old application-modal
        # TranslationProgressDialog so the rest of the window stays usable while a background
        # "Translate All" batch runs. _batch_mode_label is set once per batch and left alone;
        # _batch_status_label is overwritten on every progress signal, so the method/model info
        # would otherwise get stomped within the first fraction of a second of a batch starting.
        self._batch_mode_label = QLabel("")
        self._batch_mode_label.setWordWrap(True)
        self._batch_mode_label.setStyleSheet("font-weight: bold;")
        self._batch_mode_label.hide()
        layout.addWidget(self._batch_mode_label)

        batch_progress_row = QHBoxLayout()
        self._batch_progress_bar = QProgressBar()
        self._batch_progress_bar.setMinimum(0)
        self._batch_progress_bar.setMaximum(100)
        self._batch_progress_bar.hide()
        batch_progress_row.addWidget(self._batch_progress_bar, 1)
        self._cancel_batch_btn = QPushButton(_("Cancel"))
        self._cancel_batch_btn.clicked.connect(self._on_cancel_batch_clicked)
        self._cancel_batch_btn.hide()
        batch_progress_row.addWidget(self._cancel_batch_btn)
        layout.addLayout(batch_progress_row)

        self._batch_status_label = QLabel("")
        self._batch_status_label.setWordWrap(True)
        self._batch_status_label.setStyleSheet("color: gray;")
        self._batch_status_label.hide()
        layout.addWidget(self._batch_status_label)

        # Stays visible after a batch finishes (until the next one starts) so a rate-limit/
        # forbidden stop -- the reason a batch might end early -- isn't easy to miss now that
        # nothing is forcing the user to acknowledge a modal dialog.
        self._batch_error_label = QLabel("")
        self._batch_error_label.setWordWrap(True)
        self._batch_error_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        self._batch_error_label.hide()
        layout.addWidget(self._batch_error_label)

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
        context_menus.show_context_menu(self, position)

    def show_frozen_context_menu(self, position):
        """Show context menu for first-column cells in frozen view."""
        context_menus.show_frozen_context_menu(self, position)

    def show_header_context_menu(self, position):
        """Show context menu for header items."""
        context_menus.show_header_context_menu(self, position)

    def show_frozen_header_context_menu(self, position):
        """Show context menu for frozen first-column header."""
        context_menus.show_frozen_header_context_menu(self, position)

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

        keys_to_delete = self._prefill.outstanding_duplicate_groups.get(key, [key])
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

    def open_replace_key_window(self, row=None):
        """Open ReplaceKeyWindow for ``row``, or the currently selected row if not given."""
        if row is None:
            row = self.table.currentRow()
        if row is None or row < 0:
            QMessageBox.information(self, _("Replace Key"), _("Select a translation key first."))
            return
        if not hasattr(self, "translations") or not self.translations:
            return
        key = self._get_key_from_row(row)
        group = self.translations.get(key)
        if not group:
            QMessageBox.warning(self, _("Replace Key"), _("Could not find the selected translation key."))
            return

        dialog = ReplaceKeyWindow(
            self, self.project_path, key, group, self.locales, self.translations
        )
        dialog.key_replaced.connect(self._on_key_replaced)
        dialog.show()

    def _on_key_replaced(self, old_key, new_group):
        """Apply a ReplaceKeyWindow result: remove the old key (and any duplicate-group
        siblings it represents, same as delete_translation_group_for_row), insert the new one,
        and refresh."""
        if not hasattr(self, "translations") or not self.translations:
            return

        keys_to_replace = self._prefill.outstanding_duplicate_groups.pop(old_key, [old_key])
        for del_key in keys_to_replace:
            if del_key in self.translations:
                del self.translations[del_key]
            # Only signal a deletion if the key text actually changed -- some managers
            # (Ruby/Java/JS) prune queued-deleted keys from the on-disk tree before merging,
            # which would be a pointless prune-then-re-add for the "kept the same key, just
            # tweaked values" case.
            if del_key != new_group.key:
                self.translation_group_deleted.emit(del_key)

        self.translations[new_group.key] = new_group
        for locale in self.locales or []:
            value = new_group.get_translation_as_text(locale)
            if value:
                self.translation_updated.emit(locale, [(new_group.key, value)])

        has_items = self.load_data(self.translations, self.locales, skip_duplicate_prompt=True)
        if not has_items:
            # Special case: only a replacement (net-zero item count) remained. Force immediate
            # persistence, same as delete_translation_group_for_row.
            parent = self.parent()
            if parent and hasattr(parent, "process_batched_updates"):
                logger.debug("Outstanding list exhausted after key replace; triggering immediate batched update")
                QTimer.singleShot(0, parent.process_batched_updates)
            self.close()

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

    def _row_has_any_filled_locale(self, row):
        """True if any non-key cell in `row` currently has text.

        Used to decide staleness for LLMTranslationMode.PER_KEY_ALL_LOCALES results: one request
        covers every missing locale in the row at once, so if any of them has been filled by the
        time a result comes back, the rest of that same response is stale too (see
        translate_all_missing's is_stale closure and translation_orchestrator.py).
        """
        for col in range(1, self.table.columnCount()):
            item = self.table.item(row, col)
            if item and item.text().strip():
                return True
        return False

    def translate_all_missing(self, use_llm=False):
        """Translate all missing items using the specified method.

        Args:
            use_llm (bool): If True, use LLM for translation; otherwise use Argos Translate.
        """
        default_locale = config_manager.get('translation.default_locale', 'en')

        # Group missing cells by key so LLM per-key mode can request every locale for a key in
        # one call. Argos and LLM per-locale mode simply flatten this back to per-cell. Rows are
        # only used here to discover what's currently missing; results are addressed by key, not
        # row, so this snapshot doesn't go stale if the table's rows shift mid-batch (see
        # translation_orchestrator.py).
        row_entries = []  # (key, source_text, [(col, locale), ...])
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
                row_entries.append((key, source_text, missing_cols))

        total_missing = sum(len(cols) for _, _, cols in row_entries)
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
                (key, col, locale, source_text)
                for key, source_text, cols in row_entries
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
        self.save_btn.setEnabled(False)

        mode_label = None
        if use_llm and mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
            mode_label = _("Mode: all locales per key (model: {model})").format(
                model=self.translation_service.llm_multi.model_name
            )
        elif use_llm:
            mode_label = _("Mode: one locale at a time (model: {model})").format(
                model=self.translation_service.llm.model_name
            )

        # Reset and show the inline progress strip for this batch.
        self._batch_eta = ETATracker()
        self._batch_error_label.hide()
        method_text = _("Translation Method: {method}").format(
            method="LLM" if use_llm else "Argos Translate"
        )
        self._batch_mode_label.setText(
            f"{method_text}\n{mode_label}" if mode_label else method_text
        )
        self._batch_mode_label.show()
        self._batch_progress_bar.setValue(0)
        self._batch_progress_bar.show()
        self._batch_status_label.setText(_("Preparing..."))
        self._batch_status_label.show()
        self._cancel_batch_btn.setEnabled(True)
        self._cancel_batch_btn.setText(_("Cancel"))
        self._cancel_batch_btn.show()

        # A result is stale (dropped rather than written) if its target already has text by the
        # time it comes back. Granularity depends on mode: PER_KEY_ALL_LOCALES covers every
        # missing locale in a row with one request, so any one of them being filled makes the
        # rest of that same response stale too; every other mode (Argos, or LLM PER_LOCALE)
        # requests one cell at a time, so only that cell matters.
        if use_llm and mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
            def is_stale(row, _col):
                return self._row_has_any_filled_locale(row)
        else:
            def is_stale(row, col):
                item = self.table.item(row, col)
                return bool(item and item.text().strip())

        # Create controller, wire signals, and start the background worker/thread
        self._translation_controller = BackgroundTranslationController(self)
        self._translation_controller.progress_updated.connect(self._on_translation_progress)
        self._translation_controller.translation_completed.connect(self._on_translation_completed)
        self._translation_controller.finished.connect(self._on_translation_finished)
        self._translation_controller.error.connect(self._on_translation_error)
        self._translation_controller.batch_stopped_error.connect(self._on_translation_batch_stopped_error)
        self._translation_controller.start(
            self.translation_service,
            translation_queue,
            use_llm=use_llm,
            mode=mode,
            total=total_missing,
            row_for_key=self._key_to_row.get,
            is_stale=is_stale,
        )

    def _on_translation_progress(self, completed, total, current_item):
        """Handle progress updates from the worker."""
        if total > 0:
            self._batch_progress_bar.setValue(int((completed / total) * 100))

        self._batch_eta.record(completed)
        remaining = total - completed
        eta_secs = self._batch_eta.eta_seconds(remaining)

        count_text = _("{completed} / {total} translations completed").format(
            completed=completed, total=total
        )
        if current_item:
            detail_text = _("Translating: {item}").format(item=current_item)
        elif completed >= total:
            detail_text = _("Finished")
        elif completed > 0:
            detail_text = _("Stopped")
        else:
            detail_text = _("Preparing...")

        eta_text = ""
        if remaining > 0:
            if eta_secs is None:
                eta_text = _("Estimating time remaining…")
            else:
                eta_text = _("~{eta} remaining").format(eta=_format_eta_seconds(eta_secs))

        status_parts = [count_text, detail_text]
        if eta_text:
            status_parts.append(eta_text)
        self._batch_status_label.setText("  •  ".join(status_parts))

    def _on_translation_completed(self, row, col, translated_text):
        """Handle a completed translation."""
        item = QTableWidgetItem(translated_text)
        self.table.setItem(row, col, item)
        # Force UI update
        QTimer.singleShot(0, lambda: self.table.viewport().update())

    def _reset_batch_controls(self):
        """Re-enable buttons and hide the inline progress strip.

        Shared by the normal finish path and closeEvent's detach path. Does not touch
        self._translation_controller -- callers decide separately what to do with that
        reference (drop it immediately, since the controller itself cleans up its QThread/worker
        independently once genuinely stopped -- see translation_orchestrator.py).
        """
        self.is_translating = False
        self.translate_all_argos_btn.setEnabled(True)
        self.translate_all_llm_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

        self._batch_mode_label.hide()
        self._batch_progress_bar.hide()
        self._batch_status_label.hide()
        self._cancel_batch_btn.hide()
        # _batch_error_label is deliberately left as-is: a stop-early error (see
        # _on_translation_batch_stopped_error) should stay visible until the next batch starts,
        # not disappear the moment the worker finishes.

    def _on_translation_finished(self):
        """Handle when translation process is finished."""
        self._reset_batch_controls()
        # Dropping this reference here (rather than waiting for the QThread to actually stop) is
        # safe: the controller is parented to this window, so it stays alive regardless, and it
        # drops/cleans up its own QThread/worker independently once thread.finished proves they
        # have genuinely stopped (see BackgroundTranslationController).
        self._translation_controller = None

    def _on_translation_error(self, error_msg):
        """Handle translation errors."""
        logger.error(f"Translation error: {error_msg}")
        QMessageBox.warning(self, _("Translation Error"),
                          _("An error occurred during translation:\n{error}").format(error=error_msg))

    def _on_translation_batch_stopped_error(self, message):
        """Handle the batch stopping early because of a provider error that won't resolve by
        continuing (rate limited, or forbidden e.g. the model requires a paid subscription).

        The worker already stopped the queue (see TranslationWorker.run). Surface it in the
        inline error strip - which stays visible after the batch finishes (see
        _on_translation_finished) - rather than popping a separate dialog, since the progress
        strip above it already shows how many items completed before the stop.
        """
        logger.warning(f"Translation batch stopped early: {message}")
        self._batch_error_label.setText(
            _(
                "Translation stopped early: {message}\n\n"
                "Items completed before this happened (shown above) were kept."
            ).format(message=message)
        )
        self._batch_error_label.show()

    def _cancel_translation_worker(self):
        """Cancel the ongoing translation process."""
        if self._translation_controller:
            self._translation_controller.cancel()

    def _on_cancel_batch_clicked(self):
        """Confirm, then request cancellation of the running batch."""
        reply = QMessageBox.question(
            self,
            _("Cancel Translation"),
            _("Are you sure you want to cancel the translation process?\n\nCompleted translations will be kept."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._cancel_batch_btn.setEnabled(False)
        self._cancel_batch_btn.setText(_("Cancelling..."))
        self._cancel_translation_worker()

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

    def export_outstanding_to_tsv(self):
        """Export current outstanding rows and invalid locale buckets to a TSV file."""
        tsv_export.export_outstanding_to_tsv(
            self, self._current_invalid_groups, self.project_path, self.locales
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
        self._prefill.reset_for_load()
        self._prefill.update_notice(self.prefill_notice_label)

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
        existing_to_outstanding_matches, outstanding_duplicates = detect_duplicate_values(
            translations, locales, ignore_patterns=ignore_patterns
        )

        # Ask user once, then reuse the last choice for silent refreshes.
        combine_reply = "no"
        if existing_to_outstanding_matches or outstanding_duplicates:
            if skip_duplicate_prompt:
                combine_reply = self._prefill.last_combine_choice or "no"
                if combine_reply == "cancel":
                    combine_reply = "no"
            else:
                combine_reply = ask_combine_duplicates(
                    self, len(existing_to_outstanding_matches), len(outstanding_duplicates)
                )
                if combine_reply == "cancel":
                    # User closed dialog (X) or chose Cancel: do not open outstanding window
                    return False
                self._prefill.last_combine_choice = combine_reply

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
                                    self._prefill.record_prefill_change(locale, outstanding_key, new_value)
                                    logger.debug(f"Pre-filled {outstanding_key} in {locale} from {existing_key}")
                                    pre_filled_keys.add(outstanding_key)
                self._prefill.update_notice(self.prefill_notice_label)

                # Track outstanding duplicates - we'll show only one of each group
                for default_value, duplicate_keys in outstanding_duplicates.items():
                    # Use the first key as the representative
                    representative_key = duplicate_keys[0]
                    # Store all matched keys
                    self._prefill.outstanding_duplicate_groups[representative_key] = duplicate_keys
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
                    for rep_key, matched_keys in self._prefill.outstanding_duplicate_groups.items():
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
                        len(changes) for _, changes in self._prefill.iter_pending_prefill_changes()
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
        self._key_to_row = {}

        AppStyle.sync_theme_from_widget(self)
        highlight_colors = AppStyle.get_translation_highlight_colors()
        missing_color = highlight_colors["missing"]
        critical_color = highlight_colors["critical"]
        style_color = highlight_colors["style"]

        self.table.setRowCount(len(all_invalid_groups))

        for row, (key, (invalid_locales, group)) in enumerate(all_invalid_groups.items()):
            self._key_to_row[key] = row
            display_text = group.key.msgid
            msgid_item = QTableWidgetItem(display_text)
            msgid_item.setData(Qt.ItemDataRole.UserRole, key)
            msgid_item.setFlags(msgid_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            # If this key represents a duplicate group, add indicator
            if key in self._prefill.outstanding_duplicate_groups:
                matched_keys = self._prefill.outstanding_duplicate_groups[key]
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
            pending_prefill_count = self._prefill.pending_prefill_update_count()
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
            logger.debug(f"Duplicate groups tracked: {len(self._prefill.outstanding_duplicate_groups)}")

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
                            if key in self._prefill.outstanding_duplicate_groups:
                                matched_keys = self._prefill.outstanding_duplicate_groups[key]
                                for matched_key in matched_keys:
                                    if matched_key != key:  # Don't duplicate the representative
                                        changes_by_locale[locale].append((matched_key, new_value))

            # Emit one batch per locale
            merged_changes_by_locale = {}
            for locale, changes in changes_by_locale.items():
                merged_changes_by_locale[locale] = {key: value for key, value in changes}
            for locale, changes in self._prefill.iter_pending_prefill_changes():
                key_to_value = merged_changes_by_locale.setdefault(locale, {})
                for key, value in changes:
                    # If user edited same key in table, keep explicit table edit.
                    key_to_value.setdefault(key, value)
            self._prefill.clear_pending_prefill_changes()
            self._prefill.update_notice(self.prefill_notice_label)

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
