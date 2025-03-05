from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QListWidget, QListWidgetItem, QFileDialog,
                            QWidget)
from PyQt6.QtCore import Qt, pyqtSignal

class ProjectListItem(QWidget):
    remove_clicked = pyqtSignal(str)  # Signal to emit when remove is clicked
    select_clicked = pyqtSignal(str)  # Signal to emit when select is clicked
    
    def __init__(self, project_path, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Project path label
        self.path_label = QLabel(project_path)
        self.path_label.setStyleSheet("padding: 5px;")
        layout.addWidget(self.path_label)
        
        # Button container
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)
        
        # Select button
        select_btn = QPushButton("Select")
        select_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 8px;
            }
        """)
        select_btn.clicked.connect(lambda: self.select_clicked.emit(project_path))
        button_layout.addWidget(select_btn)
        
        # Remove button
        remove_btn = QPushButton("×")
        remove_btn.setFixedSize(24, 24)
        remove_btn.setStyleSheet("""
            QPushButton {
                padding: 0;
            }
        """)
        remove_btn.clicked.connect(lambda: self.remove_clicked.emit(project_path))
        button_layout.addWidget(remove_btn)
        
        layout.addWidget(button_container)
        self.project_path = project_path
        
class RecentProjectsDialog(QDialog):
    project_selected = pyqtSignal(str)  # Emitted when a project is selected
    project_removed = pyqtSignal(str)   # Emitted when a project is removed
    
    def __init__(self, recent_projects, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Project")
        self.setMinimumSize(500, 300)
        self.setup_ui(recent_projects)
        
    def setup_ui(self, recent_projects):
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Select a Recent Project")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Recent projects list
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.itemDoubleClicked.connect(self.handle_selection)
        layout.addWidget(self.list_widget)
        
        # Populate list
        for project in recent_projects:
            self.add_project_item(project)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        select_btn = QPushButton("Select")
        select_btn.clicked.connect(self.handle_selection)
        select_btn.setEnabled(False)  # Disabled until selection
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_project)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(select_btn)
        button_layout.addWidget(browse_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Connect selection change
        self.list_widget.itemSelectionChanged.connect(
            lambda: select_btn.setEnabled(bool(self.list_widget.selectedItems()))
        )
        
    def add_project_item(self, project_path):
        """Add a project item to the list."""
        item = QListWidgetItem()
        item.setSizeHint(ProjectListItem(project_path).sizeHint())
        widget = ProjectListItem(project_path)
        widget.remove_clicked.connect(self.remove_project)
        widget.select_clicked.connect(self.handle_selection)
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)
        
    def remove_project(self, project_path):
        """Remove a project from the list."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget.project_path == project_path:
                self.list_widget.takeItem(i)
                self.project_removed.emit(project_path)
                break
        
    def handle_selection(self):
        selected_items = self.list_widget.selectedItems()
        if selected_items:
            widget = self.list_widget.itemWidget(selected_items[0])
            self.project_selected.emit(widget.project_path)
            self.accept()
            
    def browse_project(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Project Directory",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        if directory:
            self.project_selected.emit(directory)
            self.accept() 