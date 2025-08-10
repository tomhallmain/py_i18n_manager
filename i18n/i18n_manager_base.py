from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set

from .translation_group import TranslationGroup
from .translation_manager_results import TranslationManagerResults, TranslationAction
from .invalid_translation_groups import InvalidTranslationGroups

class I18NManagerBase(ABC):
    """Abstract base class for i18n managers that defines the common interface.
    
    This class defines the contract that all project-specific i18n managers must implement.
    Each manager handles the specific requirements of their project type (Python, Ruby, etc.)
    while providing a consistent interface for the main application.
    """
    
    def __init__(self, directory: str, locales: List[str] = None, intro_details: Dict = None, settings_manager = None):
        """Initialize the base i18n manager.
        
        Args:
            directory: Project directory path
            locales: List of locale codes
            intro_details: Project metadata
            settings_manager: Settings manager instance
        """
        self._directory = directory
        self.locales = locales[:] if locales else []
        self.translations: Dict[str, TranslationGroup] = {}
        self.written_locales: Set[str] = set()
        self.intro_details = intro_details or {
            "first_author": "AUTHOR NAME <author@example.com>",
            "last_translator": "Translator Name <translator@example.com>",
            "application_name": "APPLICATION",
            "version": "1.0"
        }
        self.settings_manager = settings_manager
        self._locale_dir = self._detect_locale_directory()
    
    @property
    @abstractmethod
    def default_locale(self) -> str:
        """Get the default locale for this project.
        
        Returns:
            str: Project-specific default locale if available, otherwise global default
        """
        pass
    
    @abstractmethod
    def _detect_locale_directory(self) -> str:
        """Detect which directory structure is being used (locale or locales).
        
        Returns:
            str: The name of the locale directory being used ('locale' or 'locales')
        """
        pass
    
    @abstractmethod
    def set_directory(self, directory: str):
        """Set a new project directory and reset translation state.
        
        Args:
            directory: The new project directory path
        """
        pass
    
    @abstractmethod
    def manage_translations(self, action: TranslationAction = TranslationAction.CHECK_STATUS, 
                          modified_locales: Set[str] = None) -> TranslationManagerResults:
        """Manage translations based on the specified action.
        
        Args:
            action: The action to perform
            modified_locales: Set of locales that have been modified and need updating
            
        Returns:
            TranslationManagerResults: Results of the translation management operation
        """
        pass
    
    @abstractmethod
    def get_po_file_path(self, locale: str) -> str:
        """Get the path to the PO file for a specific locale.
        
        Args:
            locale: Locale code
            
        Returns:
            str: Path to the PO file
        """
        pass
    
    @abstractmethod
    def get_pot_file_path(self) -> str:
        """Get the path to the POT file for this project.
        
        Returns:
            str: Path to the POT file
        """
        pass
    
    @abstractmethod
    def generate_pot_file(self) -> bool:
        """Generate the source translation file (POT for gettext, etc.).
        
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def create_mo_files(self, results: TranslationManagerResults):
        """Create compiled translation files (MO files for gettext, etc.).
        
        Args:
            results: Results object to track failures
        """
        pass
    
    @abstractmethod
    def write_po_files(self, modified_locales: Set[str], results: TranslationManagerResults):
        """Write translation files for modified locales.
        
        Args:
            modified_locales: Set of locales to update
            results: Results object to track failures
        """
        pass
    

    
    @abstractmethod
    def find_translatable_strings(self) -> Dict[str, List[str]]:
        """Find potential hardcoded strings that might need translation.
        
        Returns:
            dict: A dictionary mapping filenames to lists of potential translatable strings
        """
        pass
    
    @abstractmethod
    def check_translations_changed(self, include_stale_translations: bool = False) -> bool:
        """Check if translations actually changed by comparing current state with a backup.
        
        Args:
            include_stale_translations: If True, consider stale translations as changes
            
        Returns:
            bool: True if translations changed, False otherwise
        """
        pass
    
    # Common utility methods that can be shared
    def get_invalid_translations(self) -> InvalidTranslationGroups:
        """Calculate invalid translations and return them in a structured format.
        
        Returns:
            InvalidTranslationGroups: Container with all types of invalid translations found
        """
        invalid_groups = InvalidTranslationGroups()

        for msgid, group in self.translations.items():
            if not group.is_in_base:
                # Only report not_in_base if we haven't written to all locales yet
                if not self.written_locales.issuperset(self.locales):
                    invalid_groups.not_in_base.append(msgid)
            else:
                # Check for missing translations
                missing_locales = group.get_missing_locales(self.locales)
                if missing_locales:
                    invalid_groups.missing_locale_groups.append((msgid, missing_locales))

                # Check for invalid unicode
                invalid_unicode_locales = group.get_invalid_unicode_locales()
                if invalid_unicode_locales:
                    invalid_groups.invalid_unicode_locale_groups.append((msgid, invalid_unicode_locales))

                # Check for invalid indices
                invalid_index_locales = group.get_invalid_index_locales()
                if invalid_index_locales:
                    invalid_groups.invalid_index_locale_groups.append((msgid, invalid_index_locales))

                # Check for invalid braces
                invalid_brace_locales = group.get_invalid_brace_locales()
                if invalid_brace_locales:
                    invalid_groups.invalid_brace_locale_groups.append((msgid, invalid_brace_locales))

                # Check for invalid leading spaces
                invalid_space_locales = group.get_invalid_leading_space_locales()
                if invalid_space_locales:
                    invalid_groups.invalid_leading_space_locale_groups.append((msgid, invalid_space_locales))

                # Check for invalid newlines
                invalid_newline_locales = group.get_invalid_newline_locales()
                if invalid_newline_locales:
                    invalid_groups.invalid_newline_locale_groups.append((msgid, invalid_newline_locales))

        return invalid_groups

    def fix_invalid_translations(self) -> bool:
        """Fix invalid translations in memory.
        
        Returns:
            bool: True if any fixes were applied, False otherwise
        """
        invalid_groups = self.get_invalid_translations()
        fixes_applied = False
        
        # Fix invalid unicode
        for msgid, invalid_locales in invalid_groups.invalid_unicode_locale_groups:
            self.translations[msgid].fix_ensure_encoded_unicode(invalid_locales)
            fixes_applied = True

        # Fix invalid leading/trailing spaces
        for msgid, invalid_locales in invalid_groups.invalid_leading_space_locale_groups:
            self.translations[msgid].fix_leading_and_trailing_spaces(invalid_locales)
            fixes_applied = True

        # Fix invalid explicit newlines
        for msgid, group in self.translations.items():
            if group.fix_invalid_explicit_newlines():
                fixes_applied = True

        return fixes_applied

    def print_invalid_translations(self):
        """Print invalid translations to the console."""
        invalid_groups = self.get_invalid_translations()
        one_invalid_translation_found = False
        
        for msgid in invalid_groups.not_in_base:
            print(f"Not in base: \"{msgid}\"")
            one_invalid_translation_found = True

        for msgid, missing_locales in invalid_groups.missing_locale_groups:
            print(f"Missing translations: \"{msgid}\"")
            found_locales = list(set(self.locales) - set(missing_locales))
            if len(found_locales) > 0:
                print(f"Missing in locales: {missing_locales} - Found in locales: {found_locales}")
            else:
                print("Missing in ALL locales.")
            one_invalid_translation_found = True

        for msgid, invalid_locales in invalid_groups.invalid_unicode_locale_groups:
            print(f"Invalid unicode: \"{msgid}\" in locales: {invalid_locales}")
            one_invalid_translation_found = True

        for msgid, invalid_locales in invalid_groups.invalid_index_locale_groups:
            print(f"Invalid indices: \"{msgid}\" in locales: {invalid_locales}")
            one_invalid_translation_found = True
            
        for msgid, invalid_locales in invalid_groups.invalid_brace_locale_groups:
            print(f"Invalid braces: \"{msgid}\" in locales: {invalid_locales}")
            one_invalid_translation_found = True
            
        for msgid, invalid_locales in invalid_groups.invalid_leading_space_locale_groups:
            print(f"Invalid leading/trailing spaces: \"{msgid}\" in locales: {invalid_locales}")
            one_invalid_translation_found = True
            
        for msgid, invalid_locales in invalid_groups.invalid_newline_locale_groups:
            print(f"Invalid newlines: \"{msgid}\" in locales: {invalid_locales}")
            one_invalid_translation_found = True

        if not one_invalid_translation_found:
            print("No invalid translations found.")

    def print_translations(self):
        """Print all translations to the console."""
        for msgid, group in self.translations.items():
            print(msgid)
            for locale, msgstr in group.values.items():
                print(f"\t{locale}: {msgstr}")
            print()
