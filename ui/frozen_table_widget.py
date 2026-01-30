"""QTableWidget with a frozen first column that stays visible when scrolling horizontally."""

from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtWidgets import (
    QTableWidget,
    QTableView,
    QHeaderView,
    QAbstractItemView,
)


class FrozenTableWidget(QTableWidget):
    """
    Table widget with the first column frozen: it stays fixed while other columns scroll.
    Uses two views on the same model (Qt Frozen Column Example pattern).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frozen_table = QTableView(self)
        self._frozen_table.setModel(self.model())
        self._init_frozen_table()
        self._connect_signals()
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self._frozen_table.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        self.viewport().stackUnder(self._frozen_table)
        self._frozen_table.show()
        self._update_frozen_geometry()

    def _init_frozen_table(self):
        """Set up the overlay table that shows only the first column."""
        self._frozen_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frozen_table.verticalHeader().hide()
        self._frozen_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self._frozen_table.setSelectionModel(self.selectionModel())
        self._frozen_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._frozen_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._frozen_table.setStyleSheet(
            "QTableView { border: none; }"
        )

    def _connect_signals(self):
        """Keep frozen column and scrollbars in sync with the main table."""
        self.horizontalHeader().sectionResized.connect(self._update_section_width)
        self.verticalHeader().sectionResized.connect(self._update_section_height)
        self._frozen_table.verticalScrollBar().valueChanged.connect(
            self.verticalScrollBar().setValue
        )
        self.verticalScrollBar().valueChanged.connect(
            self._frozen_table.verticalScrollBar().setValue
        )

    def _update_section_width(self, logical_index: int, _old_size: int, new_size: int):
        """When column 0 is resized, update frozen column width and geometry."""
        if logical_index == 0:
            self._frozen_table.setColumnWidth(0, new_size)
            self._update_frozen_geometry()

    def _update_section_height(self, logical_index: int, _old_size: int, new_size: int):
        """Keep frozen row heights in sync with the main table."""
        self._frozen_table.setRowHeight(logical_index, new_size)

    def _update_frozen_geometry(self):
        """Position the frozen overlay over the first column."""
        if self.columnCount() == 0:
            self._frozen_table.setGeometry(0, 0, 0, 0)
            return
        x = self.verticalHeader().width() + self.frameWidth()
        y = self.frameWidth()
        w = self.columnWidth(0)
        h = self.viewport().height() + self.horizontalHeader().height()
        self._frozen_table.setGeometry(x, y, w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_frozen_geometry()

    def moveCursor(self, action: QAbstractItemView.CursorAction, modifiers: Qt.KeyboardModifier):
        current = super().moveCursor(action, modifiers)
        # When moving left with keyboard, keep selection visible (not under frozen column)
        if (
            action == QAbstractItemView.CursorAction.MoveLeft
            and current.column() > 0
            and self.visualRect(current).topLeft().x() < self._frozen_table.columnWidth(0)
        ):
            new_value = (
                self.horizontalScrollBar().value()
                + self.visualRect(current).topLeft().x()
                - self._frozen_table.columnWidth(0)
            )
            self.horizontalScrollBar().setValue(new_value)
        return current

    def scrollTo(self, index: QModelIndex, hint: QAbstractItemView.ScrollHint = QAbstractItemView.ScrollHint.EnsureVisible):
        """Avoid scrolling the frozen column into view."""
        if index.column() > 0:
            super().scrollTo(index, hint)

    def updateFrozenColumn(self):
        """
        Call after column count or column 0 width changes.
        Hides non-frozen columns in the overlay and updates geometry.
        """
        if self.columnCount() == 0:
            self._frozen_table.setGeometry(0, 0, 0, 0)
            return
        for col in range(1, self.columnCount()):
            self._frozen_table.setColumnHidden(col, True)
        self._frozen_table.setColumnWidth(0, self.columnWidth(0))
        self._update_frozen_geometry()
