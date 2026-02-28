from datetime import datetime
import os
import sys

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                            QTextEdit, QTabWidget, QMessageBox, QFrame)
from PyQt6.QtCore import Qt, QTimer

from i18n.i18n_manager import I18NManager
from i18n.translation_manager_results import TranslationManagerResults, TranslationAction
from lib.multi_display import SmartMainWindow
from ui.all_translations_window import AllTranslationsWindow
from ui.app_style import AppStyle
from ui.bulk_pot_analysis_window import BulkPotAnalysisWindow
from ui.cross_project_analysis_window import CrossProjectAnalysisWindow
from ui.outstanding_items_window import OutstandingItemsWindow
from ui.recent_projects_dialog import RecentProjectsDialog
from ui.setup_translation_project_window import SetupTranslationProjectWindow
from ui.stats_widget import StatsWidget
from utils.globals import ProjectType
from utils.logging_setup import get_logger
from utils.project_detector import ProjectDetector
from utils.settings_manager import SettingsManager
from utils.translations import I18N
from workers.translation_worker import TranslationWorker

logger = get_logger("main_window")

# Set up translation
_ = I18N._

class MainWindow(SmartMainWindow):
    def __init__(self):
        super().__init__(restore_geometry=True)
        logger.debug("Initializing MainWindow")
        self.setWindowTitle(_("i18n Translation Manager"))
        
        # Default size; restore_window_geometry() may override with cached position/size
        screen = QApplication.primaryScreen().geometry()
        self.setMinimumSize(int(screen.width() * 0.8), int(screen.height() * 0.8))  # 80% of screen size
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))  # 90% of screen size

        # Initialize settings manager
        self.settings_manager = SettingsManager()

        # Initialize state
        self.current_project = None
        self.locales = None
        self.outstanding_window = None
        self.all_translations_window = None
        self.i18n_manager = None  # Store I18NManager instance

        # Initialize debounce timer for translation updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.process_batched_updates)
        self.pending_updates = {}  # Dictionary to store pending updates by locale
        self.pending_deletions = set()  # Translation keys deleted from editor windows

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Project selection with frame
        project_frame = QFrame()
        project_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        project_layout = QVBoxLayout(project_frame)

        # Project title
        title_layout = QHBoxLayout()
        title_label = QLabel(_("Current Project:"))
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.project_label = QLabel(_("No project selected"))
        self.project_label.setStyleSheet("font-size: 14px;")
        title_layout.addWidget(title_label)
        title_layout.addWidget(self.project_label)
        
        # Add project type label (after project name)
        self.project_type_label = QLabel("")
        self.project_type_label.setStyleSheet("font-size: 12px; color: #666; padding-left: 10px;")
        title_layout.addWidget(self.project_type_label)
        
        # Add locales label (right-aligned)
        self.locales_label = QLabel("")
        self.locales_label.setStyleSheet("font-size: 14px;")
        self.locales_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        title_layout.addStretch()  # Add stretch before the locales label to push it right
        title_layout.addWidget(self.locales_label)

        # Project selection buttons in a horizontal layout
        button_layout = QHBoxLayout()
        select_project_btn = QPushButton(_("Select Project"))
        select_project_btn.clicked.connect(self.show_project_selector)

        # Add modify project settings button
        self.modify_project_btn = QPushButton(_("Modify Project Settings"))
        self.modify_project_btn.clicked.connect(self.show_project_setup)
        self.modify_project_btn.setEnabled(False)  # Disabled by default until a project is selected

        button_layout.addWidget(select_project_btn)
        button_layout.addWidget(self.modify_project_btn)

        project_layout.addLayout(title_layout)
        project_layout.addLayout(button_layout)
        layout.addWidget(project_frame)

        # Stats widget
        self.stats_widget = StatsWidget()
        layout.addWidget(self.stats_widget)

        # Tab widget for different views
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Status tab
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)

        # Status text area
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        status_layout.addWidget(self.status_text)

        # Action buttons - split into two rows
        button_layout = QVBoxLayout()
        
        # First row of buttons
        first_row_layout = QHBoxLayout()
        self.check_status_btn = QPushButton(_("Check Status"))
        self.write_default_btn = QPushButton(_("Write Default Locale"))
        self.show_all_btn = QPushButton(_("Show All Translations"))
        self.show_outstanding_btn = QPushButton(_("Show Outstanding Items"))
        self.find_untranslated_btn = QPushButton(_("Find Untranslated"))

        self.check_status_btn.clicked.connect(lambda: self.run_translation_task())
        self.write_default_btn.clicked.connect(self.write_default_locale)
        self.show_all_btn.clicked.connect(self.show_all_translations)
        self.show_outstanding_btn.clicked.connect(self.show_outstanding_items)
        self.find_untranslated_btn.clicked.connect(self.find_untranslated_strings)

        first_row_layout.addWidget(self.check_status_btn)
        first_row_layout.addWidget(self.write_default_btn)
        first_row_layout.addWidget(self.show_all_btn)
        first_row_layout.addWidget(self.show_outstanding_btn)
        first_row_layout.addWidget(self.find_untranslated_btn)

        # Second row of buttons
        second_row_layout = QHBoxLayout()
        self.bulk_pot_btn = QPushButton(_("Bulk Project Status"))
        self.cross_project_btn = QPushButton(_("Cross-Project Analysis"))
        self.generate_pot_btn = QPushButton(_("Generate Base File"))
        self.update_po_btn = QPushButton(_("Update Translation Files"))
        self.create_mo_btn = QPushButton(_("Compile Translations"))

        self.bulk_pot_btn.clicked.connect(self.show_bulk_pot_analysis)
        self.cross_project_btn.clicked.connect(self.show_cross_project_analysis)
        self.generate_pot_btn.clicked.connect(self.generate_pot)
        self.update_po_btn.clicked.connect(lambda: self.run_translation_task(TranslationAction.WRITE_PO_FILES))
        self.create_mo_btn.clicked.connect(lambda: self.run_translation_task(TranslationAction.WRITE_MO_FILES))

        second_row_layout.addWidget(self.bulk_pot_btn)
        second_row_layout.addWidget(self.cross_project_btn)
        second_row_layout.addWidget(self.generate_pot_btn)
        second_row_layout.addWidget(self.update_po_btn)
        second_row_layout.addWidget(self.create_mo_btn)

        # Add both rows to the main button layout
        button_layout.addLayout(first_row_layout)
        button_layout.addLayout(second_row_layout)
        status_layout.addLayout(button_layout)

        self.tab_widget.addTab(status_tab, _("Status"))

        # Update button states after all buttons are created
        self.update_button_states()

        # Restore main window position/size from app_info_cache (same display as last run)
        self.restore_window_geometry()

        # Load last project if available
        self.load_last_project()

    def update_window_title(self, project_name=None):
        """Update the window title with the project name if provided."""
        title = _("i18n Translation Manager")
        if project_name and project_name.strip() != "":
            self.setWindowTitle(f"{title} - {project_name}")
        else:
            self.setWindowTitle(title)

    def load_last_project(self):
        """Load the last selected project if it exists."""
        last_project = self.settings_manager.load_last_project()
        if last_project:
            self.current_project = last_project
            project_name = os.path.basename(last_project)
            self.project_label.setText(project_name)
            self.update_window_title(project_name)
            self.update_project_type_display()
            self.update_button_states()

            # Clear previous status
            self.status_text.clear()
            self.status_text.append(f"Loading project: {last_project}")

            # Run status check
            self.run_translation_task()

    def show_project_selector(self):
        """Show the project selection dialog."""
        recent_projects = self.settings_manager.load_recent_projects()

        if recent_projects:
            dialog = RecentProjectsDialog(recent_projects, self)
            dialog.project_selected.connect(self.handle_project_selection)
            dialog.project_removed.connect(self.handle_project_removal)
            dialog.exec()
        else:
            # If no recent projects, show directory picker directly
            self.select_project()

    def handle_project_selection(self, directory):
        """Handle project selection from either recent projects or directory picker."""
        self.current_project = directory
        project_name = os.path.basename(directory)
        self.project_label.setText(project_name)
        self.update_window_title(project_name)
        self.update_button_states()

        # Detect and save project type if not already saved
        saved_project_type = self.settings_manager.get_project_type(directory)
        if not saved_project_type:
            detected_type = ProjectDetector.detect_project_type(directory)
            if detected_type:
                self.settings_manager.save_project_type(directory, detected_type.value)
                logger.info(f"Detected and saved project type: {detected_type.value} for {directory}")
            else:
                # Default to Python if detection fails
                self.settings_manager.save_project_type(directory, "python")
                logger.warning(f"Could not detect project type for {directory}, defaulting to Python")
        
        # Update project type display
        self.update_project_type_display()

        # Save the selected project
        self.settings_manager.save_last_project(directory)

        # Clear previous status
        self.status_text.clear()
        self.status_text.append(f"Loading project: {directory}")

        # Update i18n_manager with new directory if it exists
        if self.i18n_manager:
            self.i18n_manager.set_directory(directory)

        # Run status check
        self.run_translation_task()

    def select_project(self):
        """Show directory picker for project selection."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Project Directory",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        if directory:
            self.handle_project_selection(directory)

    def update_project_type_display(self):
        """Update the project type label based on the current project."""
        if not self.current_project:
            self.project_type_label.setText("")
            return
        
        project_type = self.settings_manager.get_project_type_as_type(self.current_project)
        if project_type:
            type_display = project_type.get_display_name()
            self.project_type_label.setText(f"({type_display})")
        else:
            self.project_type_label.setText("")
    
    def update_button_states(self):
        has_project = self.current_project is not None
        has_translations = self.i18n_manager is not None and self.i18n_manager.translations is not None
        
        # Get project type to determine if compilation is relevant
        project_type = None
        if has_project:
            project_type = self.settings_manager.get_project_type_as_type(self.current_project)
        
        # Compile Translations button - only enabled for Python projects (MO files are gettext-specific)
        compile_enabled = has_project and project_type == ProjectType.PYTHON
        self.create_mo_btn.setEnabled(compile_enabled)
        
        if not compile_enabled and has_project and project_type:
            # Set tooltip explaining why it's disabled
            project_type_display = project_type.get_display_name()
            self.create_mo_btn.setToolTip(
                _("Translation file compilation is not relevant for {} projects. "
                  "{} projects use YAML files directly without a compilation step.").format(
                    project_type_display, project_type_display
                )
            )
        else:
            # Clear tooltip for enabled state
            self.create_mo_btn.setToolTip("")
        
        self.check_status_btn.setEnabled(has_project)
        self.update_po_btn.setEnabled(has_project)
        self.show_outstanding_btn.setEnabled(has_project and has_translations)
        self.show_all_btn.setEnabled(has_project and has_translations)
        self.write_default_btn.setEnabled(has_project and has_translations)
        self.generate_pot_btn.setEnabled(has_project and has_translations)
        self.find_untranslated_btn.setEnabled(has_project and has_translations)
        self.cross_project_btn.setEnabled(has_project)
        self.bulk_pot_btn.setEnabled(True)  # Always enabled as it works across all projects
        self.modify_project_btn.setEnabled(has_project)

    def run_translation_task(self, action: TranslationAction = TranslationAction.CHECK_STATUS):
        """Run a translation task with the specified action.
        
        Args:
            action (TranslationAction): The action to perform. Defaults to CHECK_STATUS.
        """
        if not self.current_project:
            logger.warning("No project selected, cannot run translation task")
            QMessageBox.warning(self, "Error", "Please select a project first")
            return
            
        logger.debug(f"Starting translation task with action: {action.name}, modified locales: {self.pending_updates.keys()}")
        
        # Get intro details from config
        intro_details = self.settings_manager.get_intro_details()
        
        # Create I18NManager if needed
        if not self.i18n_manager:
            self.i18n_manager = I18NManager(self.current_project, intro_details=intro_details, settings_manager=self.settings_manager)
            
        self.worker = TranslationWorker(
            self.current_project, 
            action, 
            pending_updates=self.pending_updates.copy(),
            pending_deletions=self.pending_deletions.copy(),
            intro_details=intro_details,
            manager=self.i18n_manager
        )
        
        self.worker.finished.connect(self.handle_task_finished)
        self.worker.output.connect(self.update_status)
        self.worker.stats_updated.connect(self.update_stats)
        self.worker.translations_ready.connect(self.handle_translations_ready)
        self.worker.start()
        
        # Disable buttons while task is running
        self.update_button_states()
        
    def handle_task_finished(self, results: TranslationManagerResults):
        """Handle completion of a translation task."""
        logger.debug(f"Translation task finished - action: {results.action.name}, success: {results.action_successful}")
        self.update_button_states()
        
        # Clear modified locales after task is complete
        self.pending_updates.clear()
        
        if not results.action_successful:
            error_msg = "Task completed with warnings or errors:\n\n" + results.error_message
            logger.warning(f"Translation task completed with errors: {error_msg}")
            QMessageBox.warning(self, "Warning", error_msg)

            # TODO maybe implement this with other condition: if not self.needs_project_setup()            
            # # If this was a status check and it failed, remove the project from recent projects
            # if results.action == TranslationAction.CHECK_STATUS:
            #     logger.warning(f"Status check failed for project {self.current_project}, removing from recent projects")
            #     self.handle_project_removal(self.current_project)

        # Check if project needs setup
        if self.needs_project_setup():
            logger.debug("Project needs setup, showing setup window")
            self.show_project_setup()
            return

        # Handle translation results
        self.handle_translation_results(results)

        # If outstanding window is open, refresh it from the latest validation state.
        if (self.outstanding_window and self.outstanding_window.isVisible() and
                self.i18n_manager and self.i18n_manager.translations and self.locales):
            self.outstanding_window.load_data(
                self.i18n_manager.translations,
                self.locales,
                skip_duplicate_prompt=True,
            )

    def handle_translations_ready(self, translations, locales):
        """Handle when translations are ready to be displayed."""
        logger.debug(f"Translations ready - count: {len(translations)}, locales: {locales}")
        self.locales = locales
        self.update_button_states()
        
        # Update locales label
        if locales:
            self.locales_label.setText(", ".join(sorted(locales)))
        else:
            self.locales_label.setText("")

        # Add a success message if this was an automatic check
        if self.status_text.toPlainText().startswith("Loading project:"):
            self.status_text.append("\nProject loaded successfully!")
            self.status_text.append(f"Found {len(translations)} translations in {len(locales)} locales.")

    def update_status(self, text):
        self.status_text.append(text)

    def update_stats(self, results: TranslationManagerResults):
        """Update the statistics display."""
        self.stats_widget.update_stats(results)

    def show_outstanding_items(self):
        """Show the outstanding items window."""
        if not self.i18n_manager or not self.i18n_manager.translations or not self.locales:
            QMessageBox.warning(self, "Error", "No translation data available")
            return

        if not self.outstanding_window:
            self.outstanding_window = OutstandingItemsWindow(self, project_path=self.current_project)
            self.outstanding_window.translation_updated.connect(self.handle_translation_update)
            self.outstanding_window.translation_group_deleted.connect(self.handle_translation_group_delete)

        # Update project path and properties before loading data
        self.outstanding_window.project_path = self.current_project
        self.outstanding_window.setup_properties()
        has_items = self.outstanding_window.load_data(self.i18n_manager.translations, self.locales)
        
        # Only open the window if there are items to display
        if has_items:
            self.outstanding_window.exec()

        # The timer will handle running the translation task when needed

    def handle_translation_update(self, locale, changes):
        """Handle batched translation updates from the outstanding items window.
        
        Args:
            locale (str): The locale code
            changes (list): List of (key, new_value) tuples for this locale (key is TranslationKey)
        """
        logger.debug(f"Handling translation updates for locale {locale} - {len(changes)} changes")
        
        # Update the translations in memory
        missing_keys = []
        for key, new_value in changes:
            if key in self.i18n_manager.translations:
                logger.debug(f"Updating translation in memory for {key} in {locale}")
                self.i18n_manager.translations[key].add_translation(locale, new_value)
            else:
                missing_keys.append(key)
                logger.warning(f"Translation key {key} not found in translations dict")
        
        if missing_keys:
            logger.warning(f"Total {len(missing_keys)} keys were missing from translations dict: {missing_keys[:10]}{'...' if len(missing_keys) > 10 else ''}")
        
        # Add to pending updates
        self.pending_updates[locale] = changes
        
        # Reset the timer
        self.update_timer.start(1000)  # debounce time
        
    def process_batched_updates(self):
        """Process all pending translation updates in a single batch."""
        if not self.pending_updates and not self.pending_deletions:
            return

        # Deletions affect all locale files, so force all locales into modified set.
        if self.pending_deletions and self.locales:
            for locale in self.locales:
                self.pending_updates.setdefault(locale, [])

        logger.debug(f"Processing batched updates for {len(self.pending_updates)} locales")
        logger.debug(f"Starting translation task for locales: {self.pending_updates.keys()}")
        self.run_translation_task(TranslationAction.WRITE_PO_FILES)
            
        # Clear pending updates
        self.pending_updates.clear()
        self.pending_deletions.clear()

    def handle_translation_group_delete(self, key):
        """Handle deletion of a translation group from editor windows."""
        if not self.i18n_manager or not self.i18n_manager.translations:
            return

        if key in self.i18n_manager.translations:
            del self.i18n_manager.translations[key]
            logger.debug(f"Deleted translation key from manager dict: {key}")
        else:
            logger.debug(f"Delete signal received for already-removed key: {key}")

        # Queue deletion for persistence, but do not trigger writes yet.
        # Writes should happen on explicit save/accept flows only.
        self.pending_deletions.add(key)
        self.i18n_manager.queue_deleted_keys([key])
        logger.debug(
            f"Queued deletion for persistence (waiting for save/accept). Pending deletions: {len(self.pending_deletions)}"
        )
        
    def show_all_translations(self):
        if not self.i18n_manager or not self.i18n_manager.translations or not self.locales:
            QMessageBox.warning(self, "Error", "Please check status first to load translation data")
            return
            
        if not self.all_translations_window:
            self.all_translations_window = AllTranslationsWindow(self)
            self.all_translations_window.translation_updated.connect(self.handle_translation_update)
            self.all_translations_window.translation_group_deleted.connect(self.handle_translation_group_delete)
            
        self.all_translations_window.load_data(self.i18n_manager.translations, self.locales)
        # NOTE if there are properties that need to be re-initialized, below method will need to be implemented
        # self.all_translations_window.setup_properties()
        self.all_translations_window.show()

    def handle_project_removal(self, project_path):
        """Handle removal of a project from recent projects."""
        self.settings_manager.remove_project(project_path)
        
        # If the removed project was the current project, clear it
        if self.current_project == project_path:
            self.current_project = None
            self.project_label.setText("No project selected")
            self.locales_label.setText("")  # Clear locales label
            self.project_type_label.setText("")  # Clear project type label
            self.update_window_title()  # Reset window title
            self.update_button_states()
            # Clear stats and translations
            self.locales = None
            self.i18n_manager = None
            self.stats_widget.update_stats(0, 0, 0)
            # Clear status text
            self.status_text.clear()

    def closeEvent(self, event):
        """Handle application closing."""
        # If there's a current project and it failed to load, remove it
        if self.current_project and not self.i18n_manager:
            self.handle_project_removal(self.current_project)
        super().closeEvent(event)

    def write_default_locale(self):
        """Write the PO file for the default locale."""
        if not self.i18n_manager or not self.i18n_manager.translations:
            QMessageBox.warning(self, "Error", "No translation data available")
            return
            
        try:
            # Use project-specific default locale if available, otherwise fall back to global
            default_locale = self.settings_manager.get_project_default_locale(self.current_project)
            if default_locale in self.locales:
                self.status_text.append(f"\nWriting translation file for default locale ({default_locale})...")
                if self.i18n_manager.write_locale_po_file(default_locale):
                    self.status_text.append("Default locale translation file written successfully!")
                else:
                    QMessageBox.warning(self, "Error", f"Failed to write translation file for default locale ({default_locale})")
            else:
                QMessageBox.warning(self, "Error", f"Default locale ({default_locale}) not found in project")
        except Exception as e:
            error_msg = f"Failed to write default locale translation file: {e}"
            logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

    def generate_pot(self):
        """Generate the base translation file for the current project."""
        if not self.current_project:
            QMessageBox.warning(self, "Error", "Please select a project first")
            return
            
        try:
            self.status_text.append("\nGenerating base translation file...")
            if self.i18n_manager and self.i18n_manager.generate_pot_file():
                self.status_text.append("Successfully generated base translation file")
                # Run status check to refresh translations
                self.run_translation_task()
            else:
                QMessageBox.warning(self, "Error", "Failed to generate base translation file")
        except Exception as e:
            error_msg = f"Failed to generate base translation file: {e}"
            logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

    def find_untranslated_strings(self):
        """Find and display potential untranslated strings in the project."""
        if not self.i18n_manager:
            QMessageBox.warning(self, "Error", "Please select a project first")
            return
            
        try:
            self.status_text.append("\nSearching for untranslated strings...")
            results = self.i18n_manager.find_translatable_strings()
            
            if not results:
                self.status_text.append("No untranslated strings found in UI components.")
                return
                
            self.status_text.append("\nPotential untranslated strings found:")
            for file_path, strings in results.items():
                self.status_text.append(f"\nIn {file_path}:")
                for string in strings:
                    self.status_text.append(f"  • {string}")
                    
        except Exception as e:
            error_msg = f"Error finding untranslated strings: {e}"
            logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

    def needs_project_setup(self):
        """Check if the project needs initial setup."""
        if not self.i18n_manager:
            return False
        
        results = self.i18n_manager.manage_translations()
        return results.needs_setup()

    def show_project_setup(self):
        """Show the project setup window."""
        setup_window = SetupTranslationProjectWindow(self.current_project, self)
        setup_window.project_configured.connect(self.handle_project_setup_complete)
        setup_window.exec()
        
    def handle_project_setup_complete(self):
        """Handle completion of project setup."""
        logger.debug("Project setup completed, refreshing project type and running translation task")
        # Refresh UI/project-type dependent button state immediately after setup save.
        self.update_project_type_display()
        self.update_button_states()

        # Re-read project type from settings and recreate the concrete manager if needed.
        # This avoids stale in-memory manager type (e.g., Python) after changing setup to Ruby.
        if self.i18n_manager and self.current_project:
            self.i18n_manager.set_directory(self.current_project)

        self.run_translation_task()

    def show_cross_project_analysis(self):
        """Show the cross-project analysis window."""
        if not self.current_project:
            QMessageBox.warning(self, "Error", "Please select a project first")
            return
            
        # Check if we have recent projects to analyze against
        recent_projects = self.settings_manager.load_recent_projects()
        if len(recent_projects) < 2:
            QMessageBox.information(
                self, 
                _("No Projects to Analyze"), 
                _("You need at least 2 projects in your recent projects list to perform cross-project analysis.")
            )
            return
            
        # Show the analysis window
        analysis_window = CrossProjectAnalysisWindow(self)
        analysis_window.exec()

    def show_bulk_pot_analysis(self):
        """Show the bulk POT analysis window."""
        # Check if we have recent projects to analyze
        recent_projects = self.settings_manager.load_recent_projects()
        if not recent_projects:
            QMessageBox.information(
                self, 
                _("No Projects to Analyze"), 
                _("You need at least 1 project in your recent projects list to perform bulk POT analysis.")
            )
            return
            
        # Show the analysis window
        analysis_window = BulkPotAnalysisWindow(self)
        analysis_window.exec()

    def handle_translation_results(self, results):
        """Handle results from translation management operations."""
        if not results.action_successful:
            return
            
        # Show reminder if translation files were updated
        if results.po_files_updated:
            locales_str = ", ".join(results.updated_locales)
            QMessageBox.information(
                self,
                _("Compiled Files Need Update"),
                _("Translation files have been updated for the following locales:")
                + f"\n{locales_str}\n\n"
                + _("Remember to run Compile Translations to apply these changes.")
            )

def main():
    app = QApplication(sys.argv)
    AppStyle.sync_theme_from_application(app)
    window = MainWindow()
    logger.info(f"Application started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
