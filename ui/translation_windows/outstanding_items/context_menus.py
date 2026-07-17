"""Table and header context menus for the Outstanding Items window.

Extracted as-is from OutstandingItemsWindow. Each function takes the owning window as its
first argument and calls back into the window's existing action handlers (copy/fill/delete/
translate) -- only the menu construction itself moved, not the actions it triggers.
"""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from utils.globals import config_manager
from utils.translations import I18N

_ = I18N._


def show_context_menu(window, position):
    """Show context menu for translation options."""
    item = window.table.itemAt(position)
    if not item:
        return
    _show_context_menu_for_item(window, item, window.table.mapToGlobal(position))


def show_frozen_context_menu(window, position):
    """Show context menu for first-column cells in frozen view."""
    frozen = window.table._frozen_table
    index = frozen.indexAt(position)
    if not index.isValid():
        return
    item = window.table.item(index.row(), index.column())
    if not item:
        return
    _show_context_menu_for_item(window, item, frozen.viewport().mapToGlobal(position))


def _show_context_menu_for_item(window, item, global_position):
    """Build and show context menu for a specific table item."""

    menu = QMenu()

    # Add Copy Text option first
    copy_text = QAction(_("Copy Text"), window)
    copy_text.triggered.connect(lambda: window.copy_cell_text(item))
    menu.addAction(copy_text)

    # Add Copy Default Translation option
    default_locale = config_manager.get('translation.default_locale', 'en')
    copy_default = QAction(_("Copy Default Translation"), window)
    copy_default.triggered.connect(lambda: window.copy_default_translation(item, default_locale))
    menu.addAction(copy_default)

    fill_missing_with_default = QAction(_("Fill Missing in Row with Default Translation"), window)
    fill_missing_with_default.triggered.connect(
        lambda: window.fill_row_missing_with_default_translation(item.row())
    )
    menu.addAction(fill_missing_with_default)

    menu.addSeparator()
    delete_key = QAction(_("Delete Translation Key"), window)
    delete_key.triggered.connect(lambda: window.delete_translation_group_for_row(item.row()))
    menu.addAction(delete_key)

    # Only show translation options for non-key column cells
    if item.column() > 0:
        menu.addSeparator()
        # Add Argos Translate option
        translate_with_argos = QAction(_("Translate with Argos Translate"), window)
        translate_with_argos.triggered.connect(lambda: window.translate_selected_item(item, use_llm=False))
        menu.addAction(translate_with_argos)

        # Add LLM Translate option. Disabled while a background "Translate All" batch is
        # running: both paths would call into the same TranslationService/LLM instance, which
        # isn't safe for two overlapping requests -- Argos above has no such shared in-flight
        # state, so it stays enabled.
        translate_with_llm = QAction(_("Translate with LLM"), window)
        translate_with_llm.triggered.connect(lambda: window.translate_selected_item(item, use_llm=True))
        if getattr(window, "is_translating", False):
            translate_with_llm.setEnabled(False)
            translate_with_llm.setToolTip(
                _("Disabled while a background LLM translation batch is running.")
            )
        menu.addAction(translate_with_llm)

    menu.exec(global_position)


def show_header_context_menu(window, position):
    """Show context menu for header items."""
    # Get the column index at the position
    column = window.table.horizontalHeader().logicalIndexAt(position)
    if column < 0:
        return

    # Create menu
    menu = QMenu()

    # Add Copy Text option
    copy_text = QAction(_("Copy Text"), window)
    header_text = window.table.horizontalHeaderItem(column).text()
    copy_text.triggered.connect(lambda: window.copy_text_to_clipboard(header_text))
    menu.addAction(copy_text)

    menu.exec(window.table.horizontalHeader().mapToGlobal(position))


def show_frozen_header_context_menu(window, position):
    """Show context menu for frozen first-column header."""
    header = window.table._frozen_table.horizontalHeader()
    menu = QMenu()
    copy_text = QAction(_("Copy Text"), window)
    header_item = window.table.horizontalHeaderItem(0)
    header_text = header_item.text() if header_item else ""
    copy_text.triggered.connect(lambda: window.copy_text_to_clipboard(header_text))
    menu.addAction(copy_text)
    menu.exec(header.mapToGlobal(position))
