import logging
import os
from typing import List, Optional
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QComboBox, QTextEdit, QProgressBar, 
                            QCheckBox, QGroupBox, QListWidget, QListWidgetItem,
                            QMessageBox, QFrame, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from i18n.cross_project_analyzer import CrossProjectAnalyzer, CrossProjectAnalysis, MsgIdMatchGroup, TranslationMatch
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
                 target_locales: Optional[List[str]] = None, source_project: Optional[str] = None):
        super().__init__()
        self.analyzer = analyzer
        self.target_project = target_project
        self.target_locales = target_locales
        self.source_project = source_project
        
    def run(self):
        try:
            logger.debug(f"AnalysisWorker.run() started")
            logger.debug(f"Target project: {self.target_project}")
            logger.debug(f"Target locales: {self.target_locales}")
            logger.debug(f"Source project: {self.source_project}")
            
            if self.source_project:
                self.progress.emit(_("Analyzing from specific source project..."))
                logger.debug(f"Calling analyzer.analyze_project_pair()")
                analysis = self.analyzer.analyze_project_pair(
                    self.source_project, self.target_project, self.target_locales
                )
                analyses = [analysis] if analysis.matches_found else []
                logger.debug(f"analyze_project_pair returned analysis with {len(analysis.matches_found)} matches")
            else:
                self.progress.emit(_("Starting cross-project analysis..."))
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
        
        # Source project selection (compact)
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel(_("Source Project:")))
        self.source_project_combo = QComboBox()
        self.source_project_combo.setMinimumWidth(250)
        self.source_project_combo.addItem(_("All Projects"), None)  # Default option
        source_layout.addWidget(self.source_project_combo)
        
        top_layout.addLayout(source_layout)
        
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
        
        self.apply_from_project_btn = QPushButton(_("Apply from Project"))
        self.apply_from_project_btn.clicked.connect(self.apply_from_project)
        self.apply_from_project_btn.setEnabled(False)
        controls_layout.addWidget(self.apply_from_project_btn)
        
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
        """Load available projects into the combo boxes."""
        projects = self.analyzer.get_available_projects()
        logger.debug(f"Available projects: {projects}")
        logger.debug(f"Available project basenames: {[os.path.basename(p) for p in projects]}")
        
        # Populate target project combo
        self.target_project_combo.clear()
        for project in projects:
            project_name = os.path.basename(project)
            self.target_project_combo.addItem(project_name, project)
            
        if projects:
            self.target_project_combo.setCurrentIndex(0)
            self.on_target_project_changed()
            
        # Populate source project combo (excluding "All Projects" option)
        self.source_project_combo.clear()
        self.source_project_combo.addItem(_("All Projects"), None)  # Default option
        for project in projects:
            project_name = os.path.basename(project)
            self.source_project_combo.addItem(project_name, project)
            
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
        logger.debug(f"Starting analysis with target project: {target_project}")
        logger.debug(f"Target project basename: {os.path.basename(target_project) if target_project else 'None'}")
        
        if not target_project:
            QMessageBox.warning(self, _("Error"), _("Please select a target project."))
            return
            
        target_locales = self.get_selected_locales()
        logger.debug(f"Target locales: {target_locales}")
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
        
        # Get selected source project
        source_project = self.source_project_combo.currentData()
        
        # Start worker thread
        self.worker = AnalysisWorker(self.analyzer, target_project, target_locales, source_project)
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
        self.apply_from_project_btn.setEnabled(has_matches)
        
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
            if analysis.msgid_groups:
                project_name = os.path.basename(analysis.source_project)
                total_groups = len(analysis.msgid_groups)
                total_fillable = sum(g.fillable_locales_count for g in analysis.msgid_groups)
                total_filled = sum(g.filled_locales_count for g in analysis.msgid_groups)
                total_unfillable = sum(g.unfillable_locales_count for g in analysis.msgid_groups)
                
                summary_lines.append(_("From {}:").format(project_name))
                summary_lines.append(_("  • {} msgid groups").format(total_groups))
                summary_lines.append(_("  • {} fillable translations").format(total_fillable))
                summary_lines.append(_("  • {} already filled").format(total_filled))
                if total_unfillable > 0:
                    summary_lines.append(_("  • {} unfillable").format(total_unfillable))
                summary_lines.append(_("  • Match rate: {:.1f}%").format(analysis.match_rate))
                summary_lines.append("")
                
        self.summary_text.setPlainText("\n".join(summary_lines))
        
    def update_matches_list(self):
        """Update the matches list display."""
        self.matches_list.clear()
        
        if not self.analyses:
            return
            
        # Consolidate all msgid groups from all analyses
        all_groups = []
        for analysis in self.analyses:
            all_groups.extend(analysis.msgid_groups)
            
        # Sort by source project and msgid
        all_groups.sort(key=lambda g: (os.path.basename(g.source_project), g.target_msgid))
        
        # Add to list
        for group in all_groups:
            source_project = os.path.basename(group.source_project)
            
            # Create display text
            msgid_display = group.target_msgid[:60]
            if len(group.target_msgid) > 60:
                msgid_display += "..."
                
            item_text = f"[{source_project}] {msgid_display}"
            
            # Add counts to the display
            counts_text = f" (filled: {group.filled_locales_count}, fillable: {group.fillable_locales_count}"
            if group.unfillable_locales_count > 0:
                counts_text += f", unfillable: {group.unfillable_locales_count}"
            counts_text += f", total: {group.total_target_locales})"
            
            item_text += counts_text
                
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, group)
            
            # Add tooltip with full details
            tooltip = f"Source Project: {source_project}\n"
            tooltip += f"Target MsgID: {group.target_msgid}\n"
            tooltip += f"Filled Locales: {group.filled_locales_count}\n"
            tooltip += f"Fillable Locales: {group.fillable_locales_count}\n"
            if group.unfillable_locales_count > 0:
                tooltip += f"Unfillable Locales: {group.unfillable_locales_count}\n"
            tooltip += f"Total Target Locales: {group.total_target_locales}\n"
            tooltip += f"Match Rate: {group.match_rate:.1f}%"
            count = 0
            for match in group.matches:
                count += 1
                if count > 5:
                    tooltip += "\n" + _("... etc.")
                    break
                tooltip += f"\n  Match {count}: {match.source_msgid}"
                tooltip += f"\n    Source Translation: {match.source_translation}"
            item.setToolTip(tooltip)
            
            self.matches_list.addItem(item)

    def _collect_matches(self, source_project_filter: Optional[str] = None):
        """Collect all and selected matches, optionally filtered by source project"""
        target_project = self.target_project_combo.currentData()
        
        # Create a temporary analysis object for application
        temp_analysis = CrossProjectAnalysis(
            source_project="",  # Not used for application
            target_project=target_project,
        )

        # Get the apply mode from checkbox
        apply_all_matches = self.apply_all_matches_checkbox.isChecked()
        
        # Filter analyses by source project if specified
        filtered_analyses = self.analyses
        if source_project_filter:
            filtered_analyses = [analysis for analysis in self.analyses 
                               if analysis.source_project == source_project_filter]
        
        # Get all matches
        for analysis in filtered_analyses:
            temp_analysis.matches_found.extend(analysis.matches_found)
            temp_analysis.missing_matches.extend(analysis.missing_matches)

        selected_items = self.matches_list.selectedItems()
            
        # Extract matches from selected groups
        selected_matches = []
        for item in selected_items:
            group = item.data(Qt.ItemDataRole.UserRole)
            temp_analysis.selected_matches.extend(group.matches)

        return temp_analysis, apply_all_matches

    def apply_selected_matches(self):
        """Apply selected translation matches."""
        temp_analysis, apply_all_matches = self._collect_matches()
            
        if not temp_analysis.selected_matches:
            QMessageBox.warning(self, _("Warning"), _("Please select matches to apply."))
            return
            
        self.apply_matches(temp_analysis, apply_all_matches, None)
        
    def apply_all_matches(self):
        """Apply all translation matches."""
        if not self.analyses:
            return

        temp_analysis, apply_all_matches = self._collect_matches()
            
        if apply_all_matches and not temp_analysis.matches_found:
            QMessageBox.information(self, _("Info"), _("No matches to apply."))
            return
        if not apply_all_matches and not temp_analysis.missing_matches:
            QMessageBox.information(self, _("Info"), _("No missing translations to apply."))
            return
            
        self.apply_matches(temp_analysis, apply_all_matches, None)
        
    def apply_from_project(self):
        """Apply matches from the currently selected source project."""
        if not self.analyses:
            return
            
        # Get the currently selected source project
        selected_source_project = self.source_project_combo.currentData()
        
        if not selected_source_project:
            QMessageBox.warning(self, _("Warning"), _("Please select a specific source project from the dropdown."))
            return
            
        # Use _collect_matches with source project filter
        temp_analysis, apply_all_matches = self._collect_matches(selected_source_project)
        
        if not temp_analysis.matches_found:
            QMessageBox.information(self, _("Info"), _("No matches found for the selected project."))
            return
            
        # Apply matches from the selected project
        self.apply_matches(temp_analysis, apply_all_matches, 
                          source_project_filter=os.path.basename(selected_source_project))
        
    def apply_matches(self, 
                      temp_analysis: CrossProjectAnalysis,
                      apply_all_matches: bool,
                      source_project_filter: Optional[str] = None):
        """Apply the specified translation matches."""
        if not temp_analysis.matches_found:
            return
            
        # Create appropriate confirmation message
        is_selected = len(temp_analysis.selected_matches) > 0
        matches = temp_analysis.selected_matches if is_selected else temp_analysis.matches_found
        
        # Build the message with project filtering info
        if source_project_filter:
            if apply_all_matches:
                msg = _("Apply {0} translation matches (including already filled translations) from project '{1}' to the target project?").format(len(matches), source_project_filter)
            else:
                msg = _("Apply {0} missing translation matches from project '{1}' to the target project?").format(len(matches), source_project_filter)
        else:
            if apply_all_matches:
                msg = _("Apply {0} translation matches (including already filled translations) to the target project?").format(len(matches))
            else:
                msg = _("Apply {0} missing translation matches to the target project?").format(len(matches))
            
        reply = QMessageBox.question(self, _("Confirm Application"), msg,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return
            
        try:
            # Apply matches with the selected mode
            applied_changes = self.analyzer.apply_matches_to_target(
                temp_analysis, 
                apply_all_matches=apply_all_matches,
                apply_selected_matches=is_selected,
                dry_run=False, 
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