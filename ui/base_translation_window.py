from PyQt6.QtWidgets import QTableWidget, QHeaderView

from lib.multi_display import SmartDialog
from ui.frozen_table_widget import FrozenTableWidget


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
        self.table = FrozenTableWidget()
        self.table.setColumnCount(0)  # Will be set when data is loaded
        self.table.setRowCount(0)     # Will be set when data is loaded
        
        # Enable horizontal scrolling
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(70)  # Reduced minimum width
        
        # Set vertical header behavior
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
        return self.table
    
    def set_dynamic_column_widths(self, num_locales):
        """Set dynamic maximum width based on number of locales.
        
        Args:
            num_locales (int): Number of locales to display
        """
        # Base width for few locales
        base_width = 160
        
        # Calculate width using a continuous scale
        # Width decreases as number of locales increases
        # Formula: base_width * (1 - (num_locales - 1) * 0.02)
        # This gives a smooth decrease from base_width to about 70% of base_width at 20 locales
        max_width = int(base_width * (1 - (num_locales - 1) * 0.02))
        
        # Ensure width stays within reasonable bounds
        max_width = max(90, min(max_width, base_width))
        
        self.table.horizontalHeader().setMaximumSectionSize(max_width)
        
        # Set fixed width for the first column (msgid)
        self.table.setColumnWidth(0, 100)  # Reduced fixed width for msgid column
        
        # Keep frozen first column in sync (width and visibility)
        if hasattr(self.table, 'updateFrozenColumn'):
            self.table.updateFrozenColumn()