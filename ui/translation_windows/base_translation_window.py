from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox

from i18n.translation_group import TranslationGroup, TranslationKey
from lib.multi_display import SmartWindow
from lib.translation_service import TranslationService
from ui.frozen_table_widget import FrozenTableWidget
from utils.config import config_manager
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager
from utils.translations import I18N

_ = I18N._

logger = get_logger("base_translation_window")


def create_frozen_translation_table() -> FrozenTableWidget:
    """Shared frozen first-column table used by translation windows and quality review."""
    table = FrozenTableWidget()
    table.setColumnCount(0)
    table.setRowCount(0)
    table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setMinimumSectionSize(70)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return table


def configure_translation_table_column_widths(table: QTableWidget, num_locales: int) -> None:
    """Apply dynamic column max width rules (msgid column + locale columns)."""
    base_width = 160
    max_width = int(base_width * (1 - (num_locales - 1) * 0.02))
    max_width = max(90, min(max_width, base_width))
    table.horizontalHeader().setMaximumSectionSize(max_width)
    table.setColumnWidth(0, 100)
    if hasattr(table, "updateFrozenColumn"):
        table.updateFrozenColumn()


class BaseTranslationWindow(SmartWindow):
    """Base class for non-modal translation tool windows with shared table setup.

    Uses :class:`~lib.multi_display.SmartWindow` so multiple editors can stay open alongside
    the main window (unlike modal :class:`~lib.multi_display.SmartDialog`).
    """

    def __init__(
        self,
        parent=None,
        title=None,
        geometry="1100x750",
        offset_x=50,
        offset_y=50,
    ):
        super().__init__(
            persistent_parent=parent,
            position_parent=parent,
            title=title,
            geometry=geometry,
            offset_x=offset_x,
            offset_y=offset_y,
        )

    def setup_table(self):
        """Set up the common table configuration (first column frozen when scrolling)."""
        self.table = create_frozen_translation_table()
        return self.table
    
    def set_dynamic_column_widths(self, num_locales):
        """Set dynamic maximum width based on number of locales.
        
        Args:
            num_locales (int): Number of locales to display
        """
        configure_translation_table_column_widths(self.table, num_locales)

    def get_key_from_row(self, row):
        """Get translation key object from first-column UserRole (fallback to text)."""
        item = self.table.item(row, 0)
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if key is not None:
            return key
        return item.text() if item else ""

    def _translation_key_for_row(self, row: int) -> Any:
        """Key used for catalog lookups; subclasses may override (e.g. outstanding duplicates)."""
        return self.get_key_from_row(row)

    def _get_translations_catalog(self) -> Optional[Dict[Any, TranslationGroup]]:
        """In-memory ``TranslationKey`` → :class:`~i18n.translation_group.TranslationGroup`` map."""
        return None

    def setup_translation_service(self, project_path: Optional[str] = None) -> None:
        """Create :class:`~lib.translation_service.TranslationService` for Argos/LLM cell translation."""
        self.project_path = project_path
        self.default_locale = config_manager.get("translation.default_locale", "en")
        if not hasattr(self, "settings_manager") or self.settings_manager is None:
            self.settings_manager = SettingsManager()
        prompt_template = self.settings_manager.get_llm_prompt_template(self.project_path)
        prompt_template_multi_locale = self.settings_manager.get_llm_prompt_template_multi_locale(
            self.project_path
        )
        cjk_reject = self.settings_manager.get_llm_cjk_reject_threshold_percentage(
            self.project_path
        )
        llm_model = self.settings_manager.get_llm_model(self.project_path)
        llm_model_multi_locale = self.settings_manager.get_llm_model_multi_locale(self.project_path)
        self.translation_service = TranslationService(
            default_locale=self.default_locale,
            prompt_template=prompt_template,
            prompt_template_multi_locale=prompt_template_multi_locale,
            cjk_reject_threshold_percentage=cjk_reject,
            project_path=self.project_path,
            llm_model=llm_model,
            llm_model_multi_locale=llm_model_multi_locale,
        )

    def reload_translation_service_settings(self) -> None:
        """Reload LLM prompts / CJK threshold / models on the active translation service."""
        if not getattr(self, "translation_service", None) or not getattr(
            self, "settings_manager", None
        ):
            return
        pt = self.settings_manager.get_llm_prompt_template(self.project_path)
        pt_multi = self.settings_manager.get_llm_prompt_template_multi_locale(self.project_path)
        cjk = self.settings_manager.get_llm_cjk_reject_threshold_percentage(self.project_path)
        self.translation_service.set_prompt_template(pt)
        self.translation_service.set_prompt_template_multi_locale(pt_multi)
        self.translation_service.set_cjk_reject_threshold_percentage(cjk)
        self.translation_service.set_llm_model(self.settings_manager.get_llm_model(self.project_path))
        self.translation_service.set_llm_model_multi_locale(
            self.settings_manager.get_llm_model_multi_locale(self.project_path)
        )
        logger.info("LLM translation settings reloaded")

    def copy_text_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def copy_cell_text(self, item: QTableWidgetItem) -> None:
        if item:
            self.copy_text_to_clipboard(item.text())

    def copy_default_translation(self, item: QTableWidgetItem, default_locale: str) -> None:
        row = item.row()
        key = self._translation_key_for_row(row)
        cat = self._get_translations_catalog()
        if cat and key in cat:
            default_text = cat[key].get_translation(default_locale)
            if default_text:
                self.copy_text_to_clipboard(default_text)

    @staticmethod
    def _prompt_context_for_key(key: Any, source_text: str) -> Optional[str]:
        if isinstance(key, TranslationKey):
            key_str = key.msgid
        elif isinstance(key, tuple):
            key_str = key[1]
        elif isinstance(key, str):
            key_str = key
        else:
            key_str = str(key)
        if key_str != source_text:
            return f"Translation key: {key_str}"
        return None

    def translate_selected_item(self, item: QTableWidgetItem, use_llm: bool = False) -> None:
        """Translate one non-key cell using Argos or LLM (same pipeline as Outstanding Items)."""
        row = item.row()
        col = item.column()
        if col == 0:
            return
        key = self._translation_key_for_row(row)
        locale = self.table.horizontalHeaderItem(col).text()
        self.translate_table_cell(row, col, key, locale, use_llm=use_llm)

    def translate_table_cell(
        self,
        row: int,
        col: int,
        key: Any,
        locale: str,
        use_llm: bool = False,
    ) -> None:
        """Run translation for a single table cell and refresh the item."""
        cat = self._get_translations_catalog()
        if not cat or key not in cat:
            return
        if not getattr(self, "translation_service", None):
            return
        group = cat[key]
        default_locale = self.default_locale
        source_text = group.get_translation("en") or group.get_translation(default_locale)
        if not source_text:
            return
        context = self._prompt_context_for_key(key, source_text)
        for attempt in range(2):
            try:
                translated = self.translation_service.translate(
                    text=source_text,
                    target_locale=locale,
                    context=context,
                    use_llm=use_llm,
                )
                if translated:
                    new_item = QTableWidgetItem(translated)
                    self.table.setItem(row, col, new_item)
                    QTimer.singleShot(0, lambda: self.table.viewport().update())
                    return
            except Exception as e:
                if attempt == 0:
                    continue
                logger.error("Translation failed for %s → %s: %s", key, locale, e)

    def confirm_delete_translation_group(self, key_display: str) -> bool:
        """Show confirmation dialog before deleting a translation group."""
        reply = QMessageBox.warning(
            self,
            _("Delete Translation Key"),
            _("Delete translation key \"{key_display}\" from all locales?\n\n"
              "This will remove the key from written translation files on save/update.").format(
                key_display=key_display
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes