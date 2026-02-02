from PyQt6.QtWidgets import QVBoxLayout, QLabel, QProgressBar, QApplication
from PyQt6.QtCore import Qt, QTimer

from lib.multi_display import SmartDialog


class DownloadDialog(SmartDialog):
    """Dialog showing download progress for translation models."""

    def __init__(self, parent=None):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title="Downloading Translation Model",
            geometry="300x150",
            offset_x=50,
            offset_y=50,
            center=True,
        )
        self.setModal(True)
        self.setFixedSize(300, 150)
        
        # Create layout
        layout = QVBoxLayout()
        
        # Add loading animation
        self.loading_label = QLabel()
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Create a loading animation using dots
        self.loading_dots = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_loading_dots)
        self.timer.start(500)  # Update every 500ms
        self._update_loading_dots()
        layout.addWidget(self.loading_label)
        
        # Add status label
        self.status_label = QLabel("Preparing download...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Add progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        layout.addWidget(self.progress_bar)
        
        self.setLayout(layout)
        
        # Ensure the dialog is visible
        self.show()
        self.raise_()
        
    def _update_loading_dots(self):
        """Update the loading animation dots."""
        self.loading_dots = (self.loading_dots + 1) % 4
        self.loading_label.setText("Loading" + "." * self.loading_dots)
        QApplication.processEvents()  # Process events for the animation
        
    def update_status(self, message):
        """Update the status message."""
        self.status_label.setText(message)
        QApplication.processEvents()  # Process pending events to update the UI
        
    def set_determinate_progress(self, value, maximum):
        """Switch to determinate progress with specific value and maximum."""
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)
        QApplication.processEvents()  # Process pending events to update the UI
        
    def set_indeterminate_progress(self):
        """Switch to indeterminate progress."""
        self.progress_bar.setRange(0, 0)
        QApplication.processEvents()  # Process pending events to update the UI
        
    def closeEvent(self, event):
        """Handle dialog close event."""
        self.timer.stop()  # Stop the loading animation timer
        super().closeEvent(event) 