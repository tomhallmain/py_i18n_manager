import logging
import os
import sys

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                            QTextEdit, QTabWidget, QMessageBox, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from i18n.i18n_manager import I18NManager
from ui.stats_widget import StatsWidget
from ui.outstanding_items_window import OutstandingItemsWindow
from ui.all_translations_window import AllTranslationsWindow
from ui.recent_projects_dialog import RecentProjectsDialog
from ui.setup_translation_project_window import SetupTranslationProjectWindow
from utils.settings_manager import SettingsManager
from utils.translations import I18N
from workers.translation_worker import TranslationWorker
from i18n.translation_manager_results import TranslationManagerResults, TranslationAction

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Set up translation
_ = I18N._

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.debug("Initializing MainWindow")
        self.setWindowTitle(_("i18n Translation Manager"))
        self.setMinimumSize(800, 600)
        
        # Initialize settings manager
        self.settings_manager = SettingsManager()
        
        # Initialize state
        self.current_project = None
        self.locales = None
        self.outstanding_window = None
        self.all_translations_window = None
        self.modified_locales = set()  # Track modified locales
        self.i18n_manager = None  # Store I18NManager instance
        
        # Initialize debounce timer for translation updates
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.process_batched_updates)
        self.pending_updates = {}  # Dictionary to store pending updates by locale
        
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
        title_layout.addStretch()
        
        # Project selection button
        select_project_btn = QPushButton(_("Select Project"))
        select_project_btn.clicked.connect(self.show_project_selector)
        
        project_layout.addLayout(title_layout)
        project_layout.addWidget(select_project_btn)
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
        
        # Action buttons
        button_layout = QHBoxLayout()
        self.check_status_btn = QPushButton(_("Check Status"))
        self.update_po_btn = QPushButton(_("Update PO Files"))
        self.create_mo_btn = QPushButton(_("Create MO Files"))
        self.show_outstanding_btn = QPushButton(_("Show Outstanding Items"))
        self.show_all_btn = QPushButton(_("Show All Translations"))
        self.write_default_btn = QPushButton(_("Write Default Locale"))
        self.generate_pot_btn = QPushButton(_("Generate POT"))
        self.find_untranslated_btn = QPushButton(_("Find Untranslated"))
        
        self.check_status_btn.clicked.connect(lambda: self.run_translation_task())
        self.update_po_btn.clicked.connect(lambda: self.run_translation_task(TranslationAction.WRITE_PO_FILES))
        self.create_mo_btn.clicked.connect(lambda: self.run_translation_task(TranslationAction.WRITE_MO_FILES))
        self.show_outstanding_btn.clicked.connect(self.show_outstanding_items)
        self.show_all_btn.clicked.connect(self.show_all_translations)
        self.write_default_btn.clicked.connect(self.write_default_locale)
        self.generate_pot_btn.clicked.connect(self.generate_pot)
        self.find_untranslated_btn.clicked.connect(self.find_untranslated_strings)
        
        button_layout.addWidget(self.check_status_btn)
        button_layout.addWidget(self.update_po_btn)
        button_layout.addWidget(self.create_mo_btn)
        button_layout.addWidget(self.show_outstanding_btn)
        button_layout.addWidget(self.show_all_btn)
        button_layout.addWidget(self.write_default_btn)
        button_layout.addWidget(self.generate_pot_btn)
        button_layout.addWidget(self.find_untranslated_btn)
        status_layout.addLayout(button_layout)
        
        self.tab_widget.addTab(status_tab, _("Status"))
        
        # Update button states after all buttons are created
        self.update_button_states()
        
        # Load last project if available
        self.load_last_project()
        
    def load_last_project(self):
        """Load the last selected project if it exists."""
        last_project = self.settings_manager.load_last_project()
        if last_project:
            self.current_project = last_project
            self.project_label.setText(f"Project: {os.path.basename(last_project)}")
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
        self.project_label.setText(f"Project: {os.path.basename(directory)}")
        self.update_button_states()
        
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
        
    def update_button_states(self):
        has_project = self.current_project is not None
        has_translations = self.i18n_manager is not None and self.i18n_manager.translations is not None
        self.check_status_btn.setEnabled(has_project)
        self.update_po_btn.setEnabled(has_project)
        self.create_mo_btn.setEnabled(has_project)
        self.show_outstanding_btn.setEnabled(has_project and has_translations)
        self.show_all_btn.setEnabled(has_project and has_translations)
        self.write_default_btn.setEnabled(has_project and has_translations)
        self.generate_pot_btn.setEnabled(has_project and has_translations)
        self.find_untranslated_btn.setEnabled(has_project and has_translations)
        
    def run_translation_task(self, action: TranslationAction = TranslationAction.CHECK_STATUS):
        """Run a translation task with the specified action.
        
        Args:
            action (TranslationAction): The action to perform. Defaults to CHECK_STATUS.
        """
        if not self.current_project:
            logger.warning("No project selected, cannot run translation task")
            QMessageBox.warning(self, "Error", "Please select a project first")
            return
            
        logger.debug(f"Starting translation task with action: {action.name}, modified locales: {self.modified_locales}")
        
        # Get intro details from config
        intro_details = self.settings_manager.get_intro_details()
        
        # Create I18NManager if needed
        if not self.i18n_manager:
            self.i18n_manager = I18NManager(self.current_project, intro_details=intro_details)
            
        self.worker = TranslationWorker(
            self.current_project, 
            action, 
            self.modified_locales,
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
        self.modified_locales.clear()
        
        if not results.action_successful:
            error_msg = "Task completed with warnings or errors:\n\n" + results.error_message
            logger.warning(f"Translation task completed with errors: {error_msg}")
            QMessageBox.warning(self, "Warning", error_msg)
            
            # If this was a status check and it failed, remove the project from recent projects
            if results.action == TranslationAction.CHECK_STATUS:
                logger.warning(f"Status check failed for project {self.current_project}, removing from recent projects")
                self.handle_project_removal(self.current_project)

        # Check if project needs setup
        if self.needs_project_setup():
            logger.debug("Project needs setup, showing setup window")
            self.show_project_setup()
            return


    def handle_translations_ready(self, translations, locales):
        """Handle when translations are ready to be displayed."""
        logger.debug(f"Translations ready - count: {len(translations)}, locales: {locales}")
        self.locales = locales
        self.update_button_states()
        
        # Add a success message if this was an automatic check
        if self.status_text.toPlainText().startswith("Loading project:"):
            self.status_text.append("\nProject loaded successfully!")
            self.status_text.append(f"Found {len(translations)} translations in {len(locales)} locales.")
            
    def update_status(self, text):
        self.status_text.append(text)
        
    def update_stats(self, total_translations, total_locales, missing_translations):
        # Calculate stale translations and missing translations using I18NManager's logic
        stale_translations = 0
        missing_translations_count = 0
        invalid_unicode_count = 0
        invalid_indices_count = 0
        if self.i18n_manager is not None:
            not_in_base, missing_locale_groups, invalid_unicode_groups, invalid_index_groups = self.i18n_manager.get_invalid_translations()
            stale_translations = len(not_in_base)
            missing_translations_count = len(missing_locale_groups)
            invalid_unicode_count = len(invalid_unicode_groups)
            invalid_indices_count = len(invalid_index_groups)
            
        self.stats_widget.update_stats(
            total_translations, 
            total_locales, 
            missing_translations_count, 
            stale_translations,
            invalid_unicode_count,
            invalid_indices_count
        )
        
    def show_outstanding_items(self):
        """Show the outstanding items window."""
        if not self.i18n_manager or not self.i18n_manager.translations or not self.locales:
            QMessageBox.warning(self, "Error", "No translation data available")
            return
            
        if not self.outstanding_window:
            self.outstanding_window = OutstandingItemsWindow(self)
            self.outstanding_window.translation_updated.connect(self.handle_translation_update)
            
        self.outstanding_window.load_data(self.i18n_manager.translations, self.locales)
        self.outstanding_window.exec()
        
        # After the window is closed, update the UI
        self.update_stats(
            len(self.i18n_manager.translations),
            len(self.locales),
            sum(1 for group in self.i18n_manager.translations.values() 
                if len(group.get_missing_locales(self.locales)) > 0)
        )
        
    def handle_translation_update(self, locale, changes):
        """Handle batched translation updates from the outstanding items window.
        
        Args:
            locale (str): The locale code
            changes (list): List of (msgid, new_value) tuples for this locale
        """
        logger.debug(f"Handling translation updates for locale {locale} - {len(changes)} changes")
        
        # Update the translations in memory
        for msgid, new_value in changes:
            if msgid in self.i18n_manager.translations:
                logger.debug(f"Updating translation in memory for {msgid} in {locale}")
                self.i18n_manager.translations[msgid].add_translation(locale, new_value)
            else:
                logger.warning(f"Translation key {msgid} not found in translations")
        
        # Track the modified locale
        if locale not in self.modified_locales:
            self.modified_locales.add(locale)
            
        # Add to pending updates
        self.pending_updates[locale] = changes
        
        # Reset the timer
        self.update_timer.start(1000)  # debounce time
        
    def process_batched_updates(self):
        """Process all pending translation updates in a single batch."""
        if not self.pending_updates:
            return
            
        logger.debug(f"Processing batched updates for {len(self.pending_updates)} locales")
        
        # Start translation task for all modified locales
        if self.modified_locales:
            logger.debug(f"Starting translation task for locales: {self.modified_locales}")
            self.run_translation_task(TranslationAction.WRITE_PO_FILES)
            
        # Update the UI with the new translations
        if hasattr(self, 'outstanding_window') and self.outstanding_window:
            logger.debug("Updating outstanding items window with new translations")
            self.outstanding_window.load_data(self.i18n_manager.translations, self.locales)
            
        # Clear pending updates
        self.pending_updates.clear()
        
    def show_all_translations(self):
        if not self.i18n_manager or not self.i18n_manager.translations or not self.locales:
            QMessageBox.warning(self, "Error", "Please check status first to load translation data")
            return
            
        if not self.all_translations_window:
            self.all_translations_window = AllTranslationsWindow(self)
            self.all_translations_window.translation_updated.connect(self.handle_translation_update)
            
        self.all_translations_window.load_data(self.i18n_manager.translations, self.locales)
        self.all_translations_window.show()

    def handle_project_removal(self, project_path):
        """Handle removal of a project from recent projects."""
        self.settings_manager.remove_project(project_path)
        
        # If the removed project was the current project, clear it
        if self.current_project == project_path:
            self.current_project = None
            self.project_label.setText("No project selected")
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
        event.accept()

    def write_default_locale(self):
        """Write the PO file for the default locale."""
        if not self.i18n_manager or not self.i18n_manager.translations:
            QMessageBox.warning(self, "Error", "No translation data available")
            return
            
        try:
            default_locale = self.settings_manager.get_intro_details().get('translation.default_locale', 'en')
            if default_locale in self.locales:
                self.status_text.append(f"\nWriting PO file for default locale ({default_locale})...")
                if self.i18n_manager.write_locale_po_file(default_locale):
                    self.status_text.append("Default locale PO file written successfully!")
                else:
                    QMessageBox.warning(self, "Error", f"Failed to write PO file for default locale ({default_locale})")
            else:
                QMessageBox.warning(self, "Error", f"Default locale ({default_locale}) not found in project")
        except Exception as e:
            error_msg = f"Failed to write default locale PO file: {e}"
            logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

    def generate_pot(self):
        """Generate the base.pot file for the current project."""
        if not self.current_project:
            QMessageBox.warning(self, "Error", "Please select a project first")
            return
            
        try:
            self.status_text.append("\nGenerating base.pot file...")
            if self.i18n_manager and self.i18n_manager.generate_pot_file():
                self.status_text.append("Successfully generated base.pot file")
                # Run status check to refresh translations
                self.run_translation_task()
            else:
                QMessageBox.warning(self, "Error", "Failed to generate base.pot file")
        except Exception as e:
            error_msg = f"Failed to generate POT file: {e}"
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
        logger.debug("Project setup completed, running translation task")
        self.run_translation_task()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
