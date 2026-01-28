"""File structure manager for Ruby i18n YAML files.

This module provides a class to manage file structure parity across locales,
tracking source files for translation keys and providing utilities for translating
file paths between locales.
"""

import os
from typing import Optional

from utils.logging_setup import get_logger

logger = get_logger("file_structure_manager")


class FileStructureManager:
    """Manages file structure data and path translation for Ruby i18n files.
    
    This class encapsulates the data structures and logic needed to:
    - Track which YAML file each translation key comes from (per locale)
    - Maintain a list of all files in the default locale (for parity enforcement)
    - Store original file content (for comment preservation)
    - Translate file paths from default locale to target locales
    
    Attributes:
        _base_locale_dir: Base directory containing locale files (e.g., config/locales)
        _default_locale: Default locale code (e.g., 'en')
        _source_files: Maps translation keys to their source files: {key: {locale: file_path}}
        _default_locale_files: Set of all YAML file paths in the default locale
        _original_file_content: Maps file paths to their original content (for comment preservation)
    """
    
    def __init__(self, base_locale_dir: str, default_locale: str):
        """Initialize the file structure manager.
        
        Args:
            base_locale_dir: Base directory containing locale files (e.g., config/locales)
            default_locale: Default locale code (e.g., 'en')
        """
        self._base_locale_dir = base_locale_dir
        self._default_locale = default_locale
        # Track source files for each translation key: {key: {locale: source_file_path}}
        self._source_files: dict[str, dict[str, str]] = {}
        # Track all files that exist for default locale (to replicate structure for other locales)
        self._default_locale_files: set[str] = set()
        # Store original file content (with comments) for each file
        self._original_file_content: dict[str, str] = {}
    
    def translate_file_path(self, default_file_path: str, target_locale: str) -> Optional[str]:
        """Convert a default locale file path to target locale file path.
        
        Handles three file naming patterns:
        1. Directory structure: en/application.yml -> de/application.yml
        2. Simple flat file: en.yml -> de.yml
        3. Named flat file: devise.en.yml -> devise.de.yml
        
        Args:
            default_file_path: File path in default locale
            target_locale: Target locale code to translate to
            
        Returns:
            Translated file path, or None if translation is not possible
        """
        if not default_file_path.startswith(self._base_locale_dir):
            return None
        
        rel_path = os.path.relpath(default_file_path, self._base_locale_dir)
        target_file = None
        
        # Pattern 1: Directory structure (en/application.yml -> de/application.yml)
        if rel_path.startswith(self._default_locale + os.sep):
            target_rel_path = rel_path.replace(self._default_locale + os.sep, target_locale + os.sep, 1)
            target_file = os.path.join(self._base_locale_dir, target_rel_path)
        # Pattern 2: Simple flat file (en.yml -> de.yml)
        elif rel_path == f"{self._default_locale}.yml":
            target_file = os.path.join(self._base_locale_dir, f"{target_locale}.yml")
        else:
            # Pattern 3: Named flat file (devise.en.yml -> devise.de.yml)
            base_name = os.path.basename(default_file_path)
            if f".{self._default_locale}." in base_name:
                target_base = base_name.replace(f".{self._default_locale}.", f".{target_locale}.")
                target_file = os.path.join(self._base_locale_dir, target_base)
            elif base_name.startswith(f"{self._default_locale}."):
                # Pattern: en.something.yml -> de.something.yml
                target_base = base_name.replace(f"{self._default_locale}.", f"{target_locale}.", 1)
                target_file = os.path.join(self._base_locale_dir, target_base)
        
        return target_file
    
    def is_flat_file(self, file_path: str) -> bool:
        """Check if a file path is a flat file (directly in base_locale_dir).
        
        Flat files are directly in config/locales/ (e.g., config/locales/en.yml),
        not in a locale subdirectory (e.g., config/locales/en/application.yml).
        
        Args:
            file_path: File path to check
            
        Returns:
            True if the file is a flat file, False otherwise
        """
        file_dir = os.path.dirname(file_path)
        return os.path.normpath(file_dir) == os.path.normpath(self._base_locale_dir)
    
    def get_source_file(self, key: str, locale: str) -> Optional[str]:
        """Get source file path for a translation key in a specific locale.
        
        Args:
            key: Translation key (e.g., 'views.tasks.form.title')
            locale: Locale code
            
        Returns:
            Source file path if found, None otherwise
        """
        return self._source_files.get(key, {}).get(locale)
    
    def get_default_source_file(self, key: str) -> Optional[str]:
        """Get default locale source file path for a translation key.
        
        Args:
            key: Translation key (e.g., 'views.tasks.form.title')
            
        Returns:
            Default locale source file path if found, None otherwise
        """
        return self._source_files.get(key, {}).get(self._default_locale)
    
    def set_source_file(self, key: str, locale: str, file_path: str) -> None:
        """Set the source file path for a translation key in a specific locale.
        
        Args:
            key: Translation key (e.g., 'views.tasks.form.title')
            locale: Locale code
            file_path: Source file path
        """
        if key not in self._source_files:
            self._source_files[key] = {}
        self._source_files[key][locale] = file_path
    
    def add_default_locale_file(self, file_path: str) -> None:
        """Add a file to the set of default locale files.
        
        Args:
            file_path: File path in the default locale
        """
        self._default_locale_files.add(file_path)
    
    def get_default_locale_files(self) -> set[str]:
        """Get all files in the default locale.
        
        Returns:
            Set of file paths in the default locale
        """
        return self._default_locale_files.copy()
    
    def set_original_content(self, file_path: str, content: str) -> None:
        """Store original file content (for comment preservation).
        
        Args:
            file_path: File path
            content: Original file content as string
        """
        self._original_file_content[file_path] = content
    
    def get_original_content(self, file_path: str) -> Optional[str]:
        """Get original file content (for comment preservation).
        
        Args:
            file_path: File path
            
        Returns:
            Original file content if found, None otherwise
        """
        return self._original_file_content.get(file_path)
    
    def has_original_content(self, file_path: str) -> bool:
        """Check if original content is stored for a file.
        
        Args:
            file_path: File path
            
        Returns:
            True if original content is stored, False otherwise
        """
        return file_path in self._original_file_content
    
    def reset(self) -> None:
        """Reset all tracked data structures.
        
        Clears source files, default locale files, and original content.
        """
        self._source_files = {}
        self._default_locale_files = set()
        self._original_file_content = {}
    
    def check_file_structure_parity(
        self,
        yaml_files_by_locale: dict[str, list[str]],
        project_root: str,
    ) -> None:
        """Check and log file structure parity across locales.

        Args:
            yaml_files_by_locale: Dictionary mapping locale codes to lists of YAML file paths
                                  (typically from gather_yaml_files()).
            project_root: Root directory of the project (used to make paths relative).
        """
        default_locale_files = self.get_default_locale_files()
        if not default_locale_files:
            logger.debug("No default locale files recorded; skipping file structure parity check")
            return
        
        found_discrepancies = False
        
        # Check each non-default locale
        for locale, locale_files in yaml_files_by_locale.items():
            if locale == self._default_locale:
                continue
            
            locale_files_normalized = {os.path.normpath(f) for f in locale_files}
            
            # Convert default locale file paths to expected target locale paths
            expected_files = set()
            for default_file in default_locale_files:
                target_file = self.translate_file_path(default_file, locale)
                if target_file:
                    expected_files.add(os.path.normpath(target_file))
            
            missing = [f for f in expected_files if f not in locale_files_normalized]
            extra = [f for f in locale_files_normalized if f not in expected_files]

            missing_files = sorted(missing)
            extra_files = sorted(extra)

            if missing_files:
                found_discrepancies = True
                logger.warning(
                    f"Locale {locale} is missing {len(missing_files)} files present in default locale:"
                )
                for missing_file in missing_files:
                    rel_path = os.path.relpath(missing_file, project_root).replace("\\", "/")
                    logger.warning(f"  Missing: {rel_path}")

            if extra_files:
                found_discrepancies = True
                logger.info(
                    f"Locale {locale} has {len(extra_files)} extra files not in default locale:"
                )
                for extra_file in extra_files:
                    rel_path = os.path.relpath(extra_file, project_root).replace("\\", "/")
                    logger.info(f"  Extra: {rel_path}")
        
        # Log success if no discrepancies were found
        if not found_discrepancies:
            logger.debug("All locales have file structure parity with default locale")
    
    @property
    def base_locale_dir(self) -> str:
        """Get the base locale directory."""
        return self._base_locale_dir
    
    @property
    def default_locale(self) -> str:
        """Get the default locale code."""
        return self._default_locale
