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
    
    def _normalize_path_for_comparison(self, file_path: str, locale: str) -> str:
        """Normalize a file path to be locale-agnostic for comparison.
        
        Strips locale-specific parts from paths so they can be compared across locales.
        Examples:
        - config/locales/de/application.yml -> {locale}/application.yml
        - config/locales/en/application.yml -> {locale}/application.yml
        - config/locales/de/views/projects/_form.yml -> {locale}/views/projects/_form.yml
        - config/locales/de/application.de.yml -> {locale}/application.{locale}.yml
        - config/locales/devise.de.yml -> devise.{locale}.yml
        
        Args:
            file_path: Full file path (can be absolute or relative)
            locale: Locale code to normalize
            
        Returns:
            Normalized path with locale parts replaced by {locale} placeholder
        """
        # Normalize both paths to absolute and use forward slashes for comparison
        file_path_normalized = os.path.normpath(file_path).replace("\\", "/")
        base_locale_dir_normalized = os.path.normpath(self._base_locale_dir).replace("\\", "/")
        
        # Check if file_path is within base_locale_dir (handle both absolute and relative paths)
        if not file_path_normalized.startswith(base_locale_dir_normalized):
            # Try using os.path.relpath to see if they're related
            try:
                rel_path = os.path.relpath(file_path, self._base_locale_dir)
                # If relpath starts with .., it's outside the base directory
                if rel_path.startswith(".."):
                    return file_path_normalized
            except ValueError:
                # Paths are on different drives (Windows) or otherwise incompatible
                return file_path_normalized
        
        # Get relative path (works for both absolute and relative file_path)
        try:
            rel_path = os.path.relpath(file_path, self._base_locale_dir)
        except ValueError:
            # Paths are on different drives, use string manipulation
            if file_path_normalized.startswith(base_locale_dir_normalized):
                rel_path = file_path_normalized[len(base_locale_dir_normalized):].lstrip("/")
            else:
                return file_path_normalized
        
        # Normalize separators to forward slashes for consistent comparison
        rel_path = rel_path.replace("\\", "/")
        
        # Pattern 1: Directory structure (de/application.yml or de/views/projects/_form.yml -> {locale}/...)
        # Check if path starts with locale directory
        locale_prefix = locale + "/"
        if rel_path.startswith(locale_prefix):
            # Remove locale directory prefix
            path_after_locale = rel_path[len(locale_prefix):]
            # Normalize locale in filename if present
            parts = path_after_locale.split("/")
            base_name = parts[-1]
            if f".{locale}." in base_name:
                base_name = base_name.replace(f".{locale}.", ".{locale}.")
            elif base_name.startswith(f"{locale}."):
                base_name = base_name.replace(f"{locale}.", "{locale}.", 1)
            parts[-1] = base_name
            normalized = "{locale}/" + "/".join(parts)
            return normalized
        
        # Pattern 2: Simple flat file (de.yml -> {locale}.yml)
        if rel_path == f"{locale}.yml":
            return "{locale}.yml"
        
        # Pattern 3: Named flat file (devise.de.yml -> devise.{locale}.yml)
        # This handles files directly in base_locale_dir with locale in filename
        base_name = os.path.basename(rel_path)
        if f".{locale}." in base_name:
            normalized_base = base_name.replace(f".{locale}.", ".{locale}.")
            return normalized_base
        elif base_name.startswith(f"{locale}."):
            normalized_base = base_name.replace(f"{locale}.", "{locale}.", 1)
            return normalized_base
        
        # Fallback: return as-is (shouldn't happen for valid locale files)
        return rel_path
    
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
        # Use normalized absolute paths for robust cross-platform comparison
        # (handles path-case differences like C:\ vs c:\ on Windows).
        base_dir_abs = os.path.abspath(self._base_locale_dir)
        default_file_abs = os.path.abspath(default_file_path)
        try:
            if os.path.commonpath([
                os.path.normcase(default_file_abs),
                os.path.normcase(base_dir_abs)
            ]) != os.path.normcase(base_dir_abs):
                return None
        except ValueError:
            # Different drives or invalid path combination
            return None

        rel_path = os.path.relpath(default_file_abs, base_dir_abs)
        target_file = None
        
        # Pattern 1: Directory structure (en/application.yml -> de/application.yml)
        if rel_path.startswith(self._default_locale + os.sep):
            # Replace locale directory and localize filename when needed:
            # - en/en.yml -> de/de.yml
            # - en/javascript.en.yml -> de/javascript.de.yml
            target_rel_path = rel_path.replace(self._default_locale + os.sep, target_locale + os.sep, 1)
            target_dir = os.path.dirname(target_rel_path)
            base_name = os.path.basename(target_rel_path)
            if base_name == f"{self._default_locale}.yml":
                base_name = f"{target_locale}.yml"
            elif f".{self._default_locale}." in base_name:
                base_name = base_name.replace(f".{self._default_locale}.", f".{target_locale}.")
            elif base_name.startswith(f"{self._default_locale}."):
                base_name = base_name.replace(f"{self._default_locale}.", f"{target_locale}.", 1)
            target_rel_path = os.path.join(target_dir, base_name) if target_dir else base_name
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
        
        # CRITICAL: Normalize ALL files from ALL locales for comparison
        # Store as: normalized_path -> (original_path, locale)
        all_normalized_files: dict[str, list[tuple[str, str]]] = {}
        
        # Normalize default locale files
        for file_path in default_locale_files:
            normalized = self._normalize_path_for_comparison(file_path, self._default_locale)
            if normalized not in all_normalized_files:
                all_normalized_files[normalized] = []
            all_normalized_files[normalized].append((file_path, self._default_locale))
        
        # Normalize ALL files from ALL locales (including default, for completeness)
        for locale, locale_files in yaml_files_by_locale.items():
            for file_path in locale_files:
                normalized = self._normalize_path_for_comparison(file_path, locale)
                if normalized not in all_normalized_files:
                    all_normalized_files[normalized] = []
                all_normalized_files[normalized].append((file_path, locale))
        
        # Now compare: for each locale, check which normalized paths exist
        found_discrepancies = False
        
        # Get all normalized paths that exist in default locale
        default_normalized_paths = {
            self._normalize_path_for_comparison(f, self._default_locale)
            for f in default_locale_files
        }
        
        # Check each non-default locale
        for locale, locale_files in yaml_files_by_locale.items():
            if locale == self._default_locale:
                continue
            
            # Get normalized paths for this locale
            locale_normalized_paths = {
                self._normalize_path_for_comparison(f, locale)
                for f in locale_files
            }
            
            # Compare normalized paths ONLY
            missing_normalized = default_normalized_paths - locale_normalized_paths
            extra_normalized = locale_normalized_paths - default_normalized_paths
            
            # Convert normalized paths back to actual file paths for this locale
            missing_files = []
            for norm_path in sorted(missing_normalized):
                # Find the default locale file for this normalized path
                default_file = None
                for orig_path, orig_locale in all_normalized_files.get(norm_path, []):
                    if orig_locale == self._default_locale:
                        default_file = orig_path
                        break
                
                if default_file:
                    # Translate to target locale equivalent
                    target_equivalent = self.translate_file_path(default_file, locale)
                    if target_equivalent:
                        missing_files.append(target_equivalent)
                    else:
                        missing_files.append(default_file)
            
            extra_files = []
            for norm_path in sorted(extra_normalized):
                # Find files for this normalized path in the target locale
                for orig_path, orig_locale in all_normalized_files.get(norm_path, []):
                    if orig_locale == locale:
                        extra_files.append(orig_path)
                        break

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
