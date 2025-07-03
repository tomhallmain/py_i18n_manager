import logging
import os
from typing import List, Optional
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QComboBox, QTextEdit, QProgressBar, 
                            QCheckBox, QGroupBox, QListWidget, QListWidgetItem,
                            QMessageBox, QFrame, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from i18n.cross_project_analyzer import CrossProjectAnalyzer, CrossProjectAnalysis, TranslationMatch
from utils.settings_manager import SettingsManager
from utils.translations import I18N

# Set up translation
_ = I18N._

logger = logging.getLogger(__name__)

class AnalysisWorker(QThread):
    """Worker thread for performing cross-project analysis."""
    
    progress = pyqtSignal(str)
    analysis_complete = pyqtSignal(list)  # List[CrossProjectAnalysis]
    error = pyqtSignal(str)
    
    def __init__(self, analyzer: CrossProjectAnalyzer, target_project: str, 
                 target_locales: Optional[List[str]] = None):
        super().__init__()
        self.analyzer = analyzer
        self.target_project = target_project
        self.target_locales = target_locales
        
    def run(self):
        try:
            logger.debug(f"AnalysisWorker.run() started")
            logger.debug(f"Target project: {self.target_project}")
            logger.debug(f"Target locales: {self.target_locales}")
            
            self.progress.emit(_("Starting cross-project analysis..."))
            
            # Analyze all projects
            logger.debug(f"Calling analyzer.analyze_all_projects()")
            analyses = self.analyzer.analyze_all_projects(self.target_project, self.target_locales)
            logger.debug(f"analyze_all_projects returned {len(analyses)} analyses")
            
            self.progress.emit(_("Analysis complete!"))
            self.analysis_complete.emit(analyses)
            
        except Exception as e:
            logger.error(f"Error in analysis worker: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self.error.emit(str(e))

class CrossProjectAnalysisWindow(QDialog):
    """Window for cross-project translation analysis."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Cross-Project Translation Analysis"))
        self.setModal(True)
        
        # Set window size
        self.resize(1000, 700)
        
        # Initialize components
        self.settings_manager = SettingsManager()
        self.analyzer = CrossProjectAnalyzer(self.settings_manager)
        self.analyses: List[CrossProjectAnalysis] = []
        self.worker: Optional[AnalysisWorker] = None
        
        self.setup_ui()
        self.load_available_projects()
        
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        
        # Compact top section with minimal vertical space
        top_layout = QHBoxLayout()
        
        # Project selection (compact)
        project_layout = QHBoxLayout()
        project_layout.addWidget(QLabel(_("Target Project:")))
        self.target_project_combo = QComboBox()
        self.target_project_combo.setMinimumWidth(250)
        self.target_project_combo.currentIndexChanged.connect(self.on_target_project_changed)
        project_layout.addWidget(self.target_project_combo)
        
        # Locale selection (compact)
        project_layout.addWidget(QLabel(_("Locales:")))
        self.all_locales_checkbox = QCheckBox(_("All"))
        self.all_locales_checkbox.setChecked(True)
        self.all_locales_checkbox.toggled.connect(self.on_all_locales_toggled)
        project_layout.addWidget(self.all_locales_checkbox)
        
        self.locale_list = QListWidget()
        self.locale_list.setMaximumHeight(60)
        self.locale_list.setMaximumWidth(150)
        self.locale_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        project_layout.addWidget(self.locale_list)
        
        top_layout.addLayout(project_layout)
        
        # Analysis controls (compact)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(5)
        
        self.analyze_btn = QPushButton(_("Analyze"))
        self.analyze_btn.clicked.connect(self.start_analysis)
        controls_layout.addWidget(self.analyze_btn)
        
        # Add checkbox for applying all matches vs only missing
        self.apply_all_matches_checkbox = QCheckBox(_("Apply All Matches"))
        self.apply_all_matches_checkbox.setToolTip(_("If checked, apply all matches including already filled translations. If unchecked, only apply missing translations."))
        controls_layout.addWidget(self.apply_all_matches_checkbox)
        
        self.apply_btn = QPushButton(_("Apply Selected"))
        self.apply_btn.clicked.connect(self.apply_selected_matches)
        self.apply_btn.setEnabled(False)
        controls_layout.addWidget(self.apply_btn)
        
        self.apply_all_btn = QPushButton(_("Apply All"))
        self.apply_all_btn.clicked.connect(self.apply_all_matches)
        self.apply_all_btn.setEnabled(False)
        controls_layout.addWidget(self.apply_all_btn)
        
        self.close_btn = QPushButton(_("Close"))
        self.close_btn.clicked.connect(self.close)
        controls_layout.addWidget(self.close_btn)
        
        top_layout.addLayout(controls_layout)
        
        layout.addLayout(top_layout)
        
        # Progress bar (compact)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(20)
        layout.addWidget(self.progress_bar)
        
        # Results area - give more space to matches
        results_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Analysis summary (smaller)
        summary_group = QGroupBox(_("Analysis Summary"))
        summary_layout = QVBoxLayout(summary_group)
        
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumWidth(250)
        summary_layout.addWidget(self.summary_text)
        
        results_splitter.addWidget(summary_group)
        
        # Detailed matches (larger)
        matches_group = QGroupBox(_("Translation Matches"))
        matches_layout = QVBoxLayout(matches_group)
        
        self.matches_list = QListWidget()
        self.matches_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        matches_layout.addWidget(self.matches_list)
        
        results_splitter.addWidget(matches_group)
        
        # Set splitter proportions to give more space to matches
        results_splitter.setSizes([250, 750])
        
        layout.addWidget(results_splitter)
        
    def load_available_projects(self):
        """Load available projects into the combo box."""
        projects = self.analyzer.get_available_projects()
        
        self.target_project_combo.clear()
        for project in projects:
            project_name = os.path.basename(project)
            self.target_project_combo.addItem(project_name, project)
            
        if projects:
            self.target_project_combo.setCurrentIndex(0)
            self.on_target_project_changed()
            
    def on_target_project_changed(self):
        """Handle target project selection change."""
        current_data = self.target_project_combo.currentData()
        if current_data:
            self.load_project_locales(current_data)
            
    def load_project_locales(self, project_path: str):
        """Load locales for the selected project."""
        self.locale_list.clear()
        
        try:
            # Get manager for the project
            manager = self.analyzer._get_or_create_manager(project_path)
            if manager and manager.locales:
                for locale in sorted(manager.locales):
                    item = QListWidgetItem(locale)
                    self.locale_list.addItem(item)
                    
        except Exception as e:
            logger.error(f"Error loading locales for project {project_path}: {e}")
            
    def on_all_locales_toggled(self, checked: bool):
        """Handle all locales checkbox toggle."""
        self.locale_list.setEnabled(not checked)
        
    def get_selected_locales(self) -> Optional[List[str]]:
        """Get selected locales for analysis."""
        if self.all_locales_checkbox.isChecked():
            return None
            
        selected_items = self.locale_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, _("Warning"), _("Please select at least one locale to analyze."))
            return []
            
        return [item.text() for item in selected_items]
        
    def start_analysis(self):
        """Start the cross-project analysis."""
        target_project = self.target_project_combo.currentData()
        if not target_project:
            QMessageBox.warning(self, _("Error"), _("Please select a target project."))
            return
            
        target_locales = self.get_selected_locales()
        if target_locales is not None and not target_locales:
            return  # User cancelled due to no locale selection
            
        # Disable controls during analysis
        self.analyze_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Clear previous results
        self.analyses = []
        self.summary_text.clear()
        self.matches_list.clear()
        
        # Start worker thread
        self.worker = AnalysisWorker(self.analyzer, target_project, target_locales)
        self.worker.progress.connect(self.update_progress)
        self.worker.analysis_complete.connect(self.on_analysis_complete)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()
        
    def update_progress(self, message: str):
        """Update progress message."""
        self.summary_text.append(message)
        
    def on_analysis_complete(self, analyses: List[CrossProjectAnalysis]):
        """Handle analysis completion."""
        self.analyses = analyses
        
        # Re-enable controls
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        # Update UI with results
        self.update_summary()
        self.update_matches_list()
        
        # Enable apply buttons if we have matches
        has_matches = any(analysis.matches_found for analysis in analyses)
        has_missing = any(analysis.missing_matches for analysis in analyses)
        self.apply_btn.setEnabled(has_matches)
        self.apply_all_btn.setEnabled(has_missing)  # Only enable if there are missing translations
        
    def on_analysis_error(self, error_message: str):
        """Handle analysis error."""
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, _("Analysis Error"), error_message)
        
    def update_summary(self):
        """Update the analysis summary display."""
        if not self.analyses:
            self.summary_text.append(_("No analysis results available."))
            return
            
        summary_lines = [_("Analysis Summary:"), ""]
        
        total_matches = sum(len(analysis.matches_found) for analysis in self.analyses)
        total_missing = sum(len(analysis.missing_matches) for analysis in self.analyses)
        
        summary_lines.append(_("Total matches found: {}").format(total_matches))
        summary_lines.append(_("Missing translations: {}").format(total_missing))
        summary_lines.append(_("Already filled translations: {}").format(total_matches - total_missing))
        summary_lines.append("")
        
        for analysis in self.analyses:
            if analysis.matches_found:
                project_name = os.path.basename(analysis.source_project)
                summary_lines.append(_("From {}:").format(project_name))
                summary_lines.append(_("  • {} total matches").format(len(analysis.matches_found)))
                summary_lines.append(_("  • {} missing translations").format(len(analysis.missing_matches)))
                summary_lines.append(_("  • {} already filled").format(len(analysis.matches_found) - len(analysis.missing_matches)))
                summary_lines.append(_("  • Match rate: {:.1f}%").format(analysis.match_rate))
                summary_lines.append("")
                
        self.summary_text.setPlainText("\n".join(summary_lines))
        
    def update_matches_list(self):
        """Update the matches list display."""
        self.matches_list.clear()
        
        if not self.analyses:
            return
            
        # Consolidate all matches
        all_matches = []
        for analysis in self.analyses:
            all_matches.extend(analysis.matches_found)
            
        # Sort by target locale and msgid
        all_matches.sort(key=lambda m: (m.target_locale, m.target_msgid))
        
        # Add to list
        for match in all_matches:
            source_project = os.path.basename(match.source_project)
            item_text = f"[{match.target_locale}] {match.target_msgid[:50]}..."
            if len(match.target_msgid) > 50:
                item_text += "..."
                
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, match)
            
            # Add tooltip with full details
            tooltip = f"Source: {source_project}\n"
            tooltip += f"Target: {match.target_msgid}\n"
            tooltip += f"Locale: {match.target_locale}\n"
            tooltip += f"Translation: {match.source_translation}"
            item.setToolTip(tooltip)
            
            self.matches_list.addItem(item)
            
    def apply_selected_matches(self):
        """Apply selected translation matches."""
        selected_items = self.matches_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, _("Warning"), _("Please select matches to apply."))
            return
            
        matches = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
        self.apply_matches(matches)
        
    def apply_all_matches(self):
        """Apply all translation matches."""
        if not self.analyses:
            return
            
        # Get the apply mode from checkbox
        apply_all_matches = self.apply_all_matches_checkbox.isChecked()
        
        if apply_all_matches:
            # Get all matches
            all_matches = []
            for analysis in self.analyses:
                all_matches.extend(analysis.matches_found)
        else:
            # Get only missing matches
            all_matches = []
            for analysis in self.analyses:
                all_matches.extend(analysis.missing_matches)
            
        if not all_matches:
            if apply_all_matches:
                QMessageBox.information(self, _("Info"), _("No matches to apply."))
            else:
                QMessageBox.information(self, _("Info"), _("No missing translations to apply."))
            return
            
        self.apply_matches(all_matches)
        
    def apply_matches(self, matches: List[TranslationMatch]):
        """Apply the specified translation matches."""
        if not matches:
            return
            
        # Get the apply mode from checkbox
        apply_all_matches = self.apply_all_matches_checkbox.isChecked()
        
        # Create appropriate confirmation message
        if apply_all_matches:
            msg = _("Apply {} translation matches (including already filled translations) to the target project?").format(len(matches))
        else:
            msg = _("Apply {} missing translation matches to the target project?").format(len(matches))
            
        reply = QMessageBox.question(self, _("Confirm Application"), msg,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        try:
            # Group matches by target project
            target_project = matches[0].target_project
            
            # Create a temporary analysis object for application
            temp_analysis = CrossProjectAnalysis(
                source_project="",  # Not used for application
                target_project=target_project,
                matches_found=matches
            )
            
            # Apply matches with the selected mode
            applied_changes = self.analyzer.apply_matches_to_target(
                temp_analysis, 
                dry_run=False, 
                apply_all_matches=apply_all_matches
            )
            
            if applied_changes:
                # Show success message
                changes_text = []
                for locale, count in applied_changes.items():
                    changes_text.append(_("{}: {} translations").format(locale, count))
                    
                success_msg = _("Successfully applied translations:\n\n{}").format("\n".join(changes_text))
                QMessageBox.information(self, _("Success"), success_msg)
                
                # Refresh the analysis
                self.start_analysis()
            else:
                if apply_all_matches:
                    QMessageBox.warning(self, _("Warning"), _("No translations were applied (all were already filled)."))
                else:
                    QMessageBox.warning(self, _("Warning"), _("No missing translations were applied."))
                
        except Exception as e:
            logger.error(f"Error applying matches: {e}")
            QMessageBox.critical(self, _("Error"), _("Failed to apply translations: {}").format(str(e)))
            
    def closeEvent(self, event):
        """Handle window close event."""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        event.accept() 