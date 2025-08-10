import os
from typing import Optional

from utils.globals import ProjectType
from utils.project_detector import ProjectDetector
from utils.logging_setup import get_logger

from .i18n_manager_base import I18NManagerBase
from .python.python_i18n_manager import PythonI18NManager
from .ruby.ruby_i18n_manager import RubyI18NManager

logger = get_logger("i18n_manager")

class I18NManager(I18NManagerBase):
    """Main i18n manager that delegates to project-specific managers.
    
    This class acts as a factory and adapter, automatically detecting the project type
    and delegating to the appropriate project-specific manager (Python, Ruby, etc.).

    TODO: Add support for additional file formats:
    - Java properties files (.properties)
    - JavaScript common i18n formats:
      * JSON format (e.g., react-i18next)
      * YAML format
      * ICU MessageFormat
      * Angular i18n XLIFF format
    """
    
    def __init__(self, directory, locales=None, intro_details=None, settings_manager=None, project_type=None):
        """Initialize the main i18n manager.
        
        Args:
            directory: Project directory path
            locales: List of locale codes
            intro_details: Project metadata
            settings_manager: Settings manager instance
            project_type: Explicit project type (if None, will auto-detect)
        """
        self._directory = directory
        self.settings_manager = settings_manager
        
        # Detect project type if not provided
        if project_type is None:
            project_type = self._detect_project_type()
        
        # Create the appropriate project-specific manager
        self._manager = self._create_manager(project_type, directory, locales, intro_details, settings_manager)
        
        # Delegate all attributes to the underlying manager
        self._delegate_attributes()
    
    def _detect_project_type(self) -> ProjectType:
        """Detect the project type for this directory.
        
        Returns:
            ProjectType: The detected project type
        """
        # First check if we have a saved project type
        if self.settings_manager:
            saved_type = self.settings_manager.get_project_type(self._directory)
            if saved_type:
                try:
                    return ProjectType(saved_type)
                except ValueError:
                    logger.warning(f"Invalid saved project type: {saved_type}")
        
        # Auto-detect project type
        detected_type = ProjectDetector.detect_project_type(self._directory)
        if detected_type:
            # Save the detected type for future use
            if self.settings_manager:
                self.settings_manager.save_project_type(self._directory, detected_type.value)
            return detected_type
        
        # Default to Python if detection fails
        logger.warning(f"Could not detect project type for {self._directory}, defaulting to Python")
        if self.settings_manager:
            self.settings_manager.save_project_type(self._directory, ProjectType.PYTHON.value)
        return ProjectType.PYTHON
    
    def _create_manager(self, project_type: ProjectType, directory: str, locales, intro_details, settings_manager):
        """Create the appropriate project-specific manager.
        
        Args:
            project_type: The project type
            directory: Project directory
            locales: List of locales
            intro_details: Project metadata
            settings_manager: Settings manager
            
        Returns:
            I18NManagerBase: The appropriate manager instance
        """
        if project_type == ProjectType.PYTHON:
            logger.info(f"Creating Python i18n manager for {directory}")
            return PythonI18NManager(directory, locales, intro_details, settings_manager)
        elif project_type == ProjectType.RUBY:
            logger.info(f"Creating Ruby i18n manager for {directory}")
            return RubyI18NManager(directory, locales, intro_details, settings_manager)
        else:
            raise ValueError(f"Unsupported project type: {project_type}")
    
    def _delegate_attributes(self):
        """Delegate all attributes to the underlying manager."""
        # Delegate all the main attributes
        self.locales = self._manager.locales
        self.translations = self._manager.translations
        self.written_locales = self._manager.written_locales
        self.intro_details = self._manager.intro_details
        self._locale_dir = self._manager._locale_dir
    
    @property
    def default_locale(self) -> str:
        """Get the default locale for this project."""
        return self._manager.default_locale
    
    def _detect_locale_directory(self) -> str:
        """Detect which directory structure is being used."""
        return self._manager._detect_locale_directory()
    
    def set_directory(self, directory: str):
        """Set a new project directory and reset translation state."""
        self._directory = directory
        self._manager.set_directory(directory)
        self._delegate_attributes()
    
    def manage_translations(self, action=None, modified_locales=None):
        """Manage translations based on the specified action."""
        return self._manager.manage_translations(action, modified_locales)
    
    def get_po_file_path(self, locale: str) -> str:
        """Get the path to the PO file for a specific locale."""
        return self._manager.get_po_file_path(locale)
    
    def get_pot_file_path(self) -> str:
        """Get the path to the POT file for this project."""
        return self._manager.get_pot_file_path()
    
    def generate_pot_file(self) -> bool:
        """Generate the source translation file."""
        return self._manager.generate_pot_file()
    
    def create_mo_files(self, results):
        """Create compiled translation files."""
        return self._manager.create_mo_files(results)
    
    def write_po_files(self, modified_locales, results):
        """Write translation files for modified locales."""
        return self._manager.write_po_files(modified_locales, results)
    
    def get_invalid_translations(self):
        """Calculate invalid translations and return them in a structured format."""
        return self._manager.get_invalid_translations()
    
    def fix_invalid_translations(self) -> bool:
        """Fix invalid translations in memory."""
        return self._manager.fix_invalid_translations()
    
    def find_translatable_strings(self):
        """Find potential hardcoded strings that might need translation."""
        return self._manager.find_translatable_strings()
    
    def check_translations_changed(self, include_stale_translations: bool = False) -> bool:
        """Check if translations actually changed by comparing current state with a backup."""
        return self._manager.check_translations_changed(include_stale_translations)
    
    # Delegate all other methods to the underlying manager
    def __getattr__(self, name):
        """Delegate any other attributes to the underlying manager."""
        return getattr(self._manager, name)
