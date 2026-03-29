from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget, QHeaderView, QMessageBox

from lib.multi_display import SmartDialog
from ui.frozen_table_widget import FrozenTableWidget
from utils.translations import I18N

_ = I18N._


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


class BaseTranslationWindow(SmartDialog):
    """Base class for translation windows with shared table setup logic.
    Positions on the same display as the parent via SmartDialog.
    """

    def __init__(self, parent=None, title=None, geometry="1100x750"):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=title,
            geometry=geometry,
            offset_x=50,
            offset_y=50,
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