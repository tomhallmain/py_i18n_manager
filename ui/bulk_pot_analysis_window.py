import os
from typing import List, Optional
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTextEdit, QProgressBar, QTableWidget,
                            QTableWidgetItem, QHeaderView, QMessageBox, 
                            QFrame, QGroupBox, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor

from i18n.bulk_pot_analyzer import BulkPotAnalyzer, ProjectAnalysisResult, GitStatus
from utils.globals import ProjectType
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager
from utils.translations import I18N

# Set up translation
_ = I18N._

logger = get_logger("bulk_pot_analysis_window")

class BulkAnalysisWorker(QThread):
    """Worker thread for performing bulk project status checks."""
    
    progress = pyqtSignal(str)
    project_complete = pyqtSignal(ProjectAnalysisResult)
    analysis_complete = pyqtSignal(list)  # List[ProjectAnalysisResult]
    error = pyqtSignal(str)
    
    def __init__(self, analyzer: BulkPotAnalyzer):
        super().__init__()
        self.analyzer = analyzer
        
    def run(self):
        try:
            logger.debug("BulkAnalysisWorker.run() started")
            
            projects = self.analyzer.get_available_projects()
            if not projects:
                self.error.emit(_("No projects available for analysis."))
                return
            
            self.progress.emit(_("Starting bulk project status check for {} projects...").format(len(projects)))
            
            results = []
            for i, project_path in enumerate(projects):
                project_name = os.path.basename(project_path)
                self.progress.emit(_("Analyzing project {} of {}: {}").format(i + 1, len(projects), project_name))
                
                result = self.analyzer.analyze_project(project_path)
                results.append(result)
                self.project_complete.emit(result)
            
            self.progress.emit(_("Bulk analysis complete!"))
            self.analysis_complete.emit(results)
            
        except Exception as e:
            logger.error(f"Error in bulk analysis worker: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self.error.emit(str(e))

class BulkPotAnalysisWindow(QDialog):
    """Window for bulk project status checking and base file generation across all projects.
    
    This window generates/updates base translation files for all projects and reports on:
    - Missing translations per locale
    - Git repository status
    - Base file modification status
    - Overall project health
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Bulk Project Status"))
        self.setModal(True)
        
        # Set window size
        self.resize(1200, 800)
        
        # Initialize components
        self.settings_manager = SettingsManager()
        self.analyzer = BulkPotAnalyzer(self.settings_manager)
        self.results: List[ProjectAnalysisResult] = []
        self.worker: Optional[BulkAnalysisWorker] = None
        
        self.setup_ui()
        
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        
        # Top section with controls
        top_layout = QHBoxLayout()
        
        self.analyze_btn = QPushButton(_("Analyze All Projects"))
        self.analyze_btn.clicked.connect(self.start_analysis)
        top_layout.addWidget(self.analyze_btn)
        
        self.refresh_btn = QPushButton(_("Refresh"))
        self.refresh_btn.clicked.connect(self.refresh_analysis)
        self.refresh_btn.setEnabled(False)
        top_layout.addWidget(self.refresh_btn)
        
        self.close_btn = QPushButton(_("Close"))
        self.close_btn.clicked.connect(self.close)
        top_layout.addWidget(self.close_btn)
        
        top_layout.addStretch()
        
        layout.addLayout(top_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(20)
        layout.addWidget(self.progress_bar)
        
        # Main content area
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Results table (left side)
        table_group = QGroupBox(_("Project Analysis Results"))
        table_layout = QVBoxLayout(table_group)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(8)
        self.results_table.setHorizontalHeaderLabels([
            _("Project"), _("Type"), _("Status"), _("Missing"), _("Total"), 
            _("Locales"), _("Git Status"), _("Base Modified")
        ])
        
        # Set column widths
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Project name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Type
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Missing
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Total
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Locales
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Git Status
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # Base Modified
        
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.itemSelectionChanged.connect(self.on_selection_changed)
        
        table_layout.addWidget(self.results_table)
        content_splitter.addWidget(table_group)
        
        # Details panel (right side)
        details_group = QGroupBox(_("Project Details"))
        details_layout = QVBoxLayout(details_group)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        details_layout.addWidget(self.details_text)
        
        content_splitter.addWidget(details_group)
        
        # Set splitter proportions
        content_splitter.setSizes([800, 400])
        
        layout.addWidget(content_splitter)
        
        # Summary section at bottom
        summary_frame = QFrame()
        summary_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        summary_layout = QHBoxLayout(summary_frame)
        
        self.summary_label = QLabel(_("No analysis performed yet"))
        self.summary_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        summary_layout.addWidget(self.summary_label)
        
        layout.addWidget(summary_frame)
        
    def start_analysis(self):
        """Start the bulk analysis."""
        # Disable controls during analysis
        self.analyze_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Clear previous results
        self.results = []
        self.results_table.setRowCount(0)
        self.details_text.clear()
        self.summary_label.setText(_("Analysis in progress..."))
        
        # Start worker thread
        self.worker = BulkAnalysisWorker(self.analyzer)
        self.worker.progress.connect(self.update_progress)
        self.worker.project_complete.connect(self.on_project_complete)
        self.worker.analysis_complete.connect(self.on_analysis_complete)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()
        
    def refresh_analysis(self):
        """Refresh the analysis results."""
        self.start_analysis()
        
    def update_progress(self, message: str):
        """Update progress message."""
        self.summary_label.setText(message)
        
    def on_project_complete(self, result: ProjectAnalysisResult):
        """Handle completion of a single project analysis."""
        # Add to results list
        self.results.append(result)
        
        # Add to table
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        
        # Project name
        project_item = QTableWidgetItem(result.project_name)
        project_item.setData(Qt.ItemDataRole.UserRole, result)
        self.results_table.setItem(row, 0, project_item)
        
        # Project type
        project_type = self.settings_manager.get_project_type(result.project_path)
        if project_type:
            try:
                type_enum = ProjectType(project_type)
                type_display = type_enum.get_display_name()
            except ValueError:
                type_display = project_type.capitalize()
        else:
            type_display = "—"
        type_item = QTableWidgetItem(type_display)
        self.results_table.setItem(row, 1, type_item)
        
        # Status
        if result.error_message:
            status_item = QTableWidgetItem(_("Error"))
            status_item.setBackground(QColor(255, 200, 200))  # Light red
        elif result.has_missing_translations:
            status_item = QTableWidgetItem(_("Missing Translations"))
            status_item.setBackground(QColor(255, 255, 200))  # Light yellow
        else:
            status_item = QTableWidgetItem(_("Complete"))
            status_item.setBackground(QColor(200, 255, 200))  # Light green
        self.results_table.setItem(row, 2, status_item)
        
        # Missing translations count
        missing_item = QTableWidgetItem(str(result.missing_translations_count))
        self.results_table.setItem(row, 3, missing_item)
        
        # Total translations
        total_item = QTableWidgetItem(str(result.total_translations))
        self.results_table.setItem(row, 4, total_item)
        
        # Locales with missing
        locales_text = ", ".join(result.locales_with_missing) if result.locales_with_missing else _("None")
        locales_item = QTableWidgetItem(locales_text)
        self.results_table.setItem(row, 5, locales_item)
        
        # Git status
        git_status_map = {
            GitStatus.CLEAN: _("Clean"),
            GitStatus.MODIFIED: _("Modified"),
            GitStatus.UNTRACKED: _("Untracked"),
            GitStatus.ERROR: _("Error"),
            GitStatus.UNKNOWN: _("Unknown")
        }
        git_item = QTableWidgetItem(git_status_map.get(result.git_status, result.git_status.value))
        self.results_table.setItem(row, 6, git_item)
        
        # Base modified (POT for Python, YAML for Ruby)
        base_modified_item = QTableWidgetItem(_("Yes") if result.base_was_modified else _("No"))
        self.results_table.setItem(row, 7, base_modified_item)
        
    def on_analysis_complete(self, results: List[ProjectAnalysisResult]):
        """Handle completion of the entire analysis."""
        self.results = results
        
        # Re-enable controls
        self.analyze_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        # Update summary
        total_projects = len(results)
        projects_with_missing = sum(1 for r in results if r.has_missing_translations)
        projects_with_errors = sum(1 for r in results if r.error_message)
        total_missing = sum(r.missing_translations_count for r in results)
        
        summary_text = _("Analysis complete: {} projects analyzed").format(total_projects)
        if projects_with_missing > 0:
            summary_text += _(", {} projects have missing translations ({} total missing)").format(
                projects_with_missing, total_missing)
        if projects_with_errors > 0:
            summary_text += _(", {} projects had errors").format(projects_with_errors)
        
        self.summary_label.setText(summary_text)
        
    def on_analysis_error(self, error_message: str):
        """Handle analysis error."""
        self.analyze_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, _("Analysis Error"), error_message)
        
    def on_selection_changed(self):
        """Handle table selection change."""
        selected_items = self.results_table.selectedItems()
        if not selected_items:
            self.details_text.clear()
            return
            
        # Get the selected result
        row = selected_items[0].row()
        project_item = self.results_table.item(row, 0)
        result = project_item.data(Qt.ItemDataRole.UserRole)
        
        # Update details text
        details = []
        details.append(f"<h3>{result.project_name}</h3>")
        details.append(f"<b>{_('Project Path:')}</b> {result.project_path}")
        
        # Get project type for display
        project_type = self.settings_manager.get_project_type(result.project_path)
        if project_type:
            try:
                type_enum = ProjectType(project_type)
                type_display = type_enum.get_display_name()
            except ValueError:
                type_display = project_type.capitalize()
            details.append(f"<b>{_('Project Type:')}</b> {type_display}")
        
        # Use generic "Base File" label instead of "POT File"
        details.append(f"<b>{_('Base File:')}</b> {result.base_file_path}")
        details.append(f"<b>{_('Total Translations:')}</b> {result.total_translations}")
        details.append(f"<b>{_('Missing Translations:')}</b> {result.missing_translations_count}")
        details.append(f"<b>{_('Git Status:')}</b> {result.git_status.value}")
        details.append(f"<b>{_('Base Modified:')}</b> {_('Yes') if result.base_was_modified else _('No')}")
        
        if result.locales_with_missing:
            details.append(f"<b>{_('Locales with Missing Translations:')}</b>")
            for locale in result.locales_with_missing:
                details.append(f"  • {locale}")
        
        if result.error_message:
            details.append(f"<b>{_('Error:')}</b>")
            details.append(f"<span style='color: red;'>{result.error_message}</span>")
        
        self.details_text.setHtml("<br>".join(details))
        
    def closeEvent(self, event):
        """Handle window close event."""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        event.accept() 