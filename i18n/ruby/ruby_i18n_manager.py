from datetime import datetime
import glob
import os
import shutil
import sys
import time
import re
import yaml
from pathlib import Path

# IMPORTANT: Why we use both PyYAML and ruamel.yaml
#
# Ruby/Rails i18n YAML files typically use quoted string values (e.g., "value" instead of value).
# This is a Rails convention that:
#   1. Prevents YAML from interpreting special strings as booleans/null (e.g., "yes", "no", "true", "false")
#   2. Provides visual consistency in translation files
#   3. Is widely used in Rails projects
#
# PyYAML can READ quoted strings perfectly fine, but it does NOT preserve quote style when WRITING:
#   - PyYAML parses YAML into Python objects and discards formatting (quotes, comments, spacing)
#   - When dumping, PyYAML makes its own formatting decisions and doesn't preserve original quote style
#   - This is by design - PyYAML focuses on data structure, not formatting preservation
#
# ruamel.yaml was created specifically to preserve YAML formatting:
#   - Preserves quotes, comments, indentation, and other formatting during round-trip operations
#   - Allows us to maintain the Rails convention of quoted string values
#   - Better suited for configuration files and i18n files where formatting matters
#
# Strategy:
#   - Use PyYAML for reading (works fine with quoted strings, simpler, faster)
#   - Use ruamel.yaml for writing when available (preserves quotes and comments)
#   - Fall back to PyYAML for writing if ruamel.yaml is not available (values won't be quoted, but still valid YAML)
#
# Try to import ruamel.yaml for better YAML handling (preserves comments and quotes)
try:
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString
    RUAMEL_AVAILABLE = True
except ImportError:
    RUAMEL_AVAILABLE = False
    RuamelYAML = None
    DoubleQuotedScalarString = None

from i18n.translation_group import TranslationGroup, TranslationKey
from ..translation_manager_results import TranslationManagerResults, TranslationAction, LocaleStatus
from ..invalid_translation_groups import InvalidTranslationGroups
from ..i18n_manager_base import I18NManagerBase
from .file_structure_manager import FileStructureManager

from utils.logging_setup import get_logger

logger = get_logger("ruby_i18n_manager")

class RubyI18NManager(I18NManagerBase):
    """Manages the Ruby/Rails internationalization (i18n) workflow for YAML translation files.
    
    This manager supports Ruby on Rails projects using the standard Rails i18n YAML format.
    Rails i18n uses YAML files organized in config/locales/ with nested key structures.
    
    The workflow for managing Ruby/Rails translations consists of several steps:
    
    1. YAML File Structure:
       - Translations are stored in YAML files under config/locales/
       - Files are organized by namespace (models/, views/, etc.)
       - Keys use dot notation (e.g., "tasks.form.title")
       - Each locale has its own directory (e.g., config/locales/en/, config/locales/es/)
    
    2. Base Translation Set:
       - Parse YAML files from the default locale to establish base translations
       - Extract nested keys and flatten them (e.g., en.tasks.form.title -> "tasks.form.title")
       - Each key becomes a TranslationGroup marked as 'in_base'
    
    3. Locale Translations:
       - Parse YAML files for each locale
       - Track missing translations (keys in base but not in locale)
       - Identify invalid translations (Unicode/format string issues)
       - Support nested YAML structures
    
    4. Translation Management:
       - Track missing translations for each locale
       - Identify invalid Unicode sequences
       - Identify invalid format string indices/braces
       - Allow user to fix/add translations via UI
    
    5. YAML File Updates:
       - Write updated YAML files organized by namespace
       - Maintain Rails i18n file structure (models/, views/, etc.)
       - Preserve nested key structure in YAML format
    
    Note: For extracting translatable strings from Ruby/ERB source files,
    consider using external tools like `i18n-tasks`.
    """

    def __init__(self, directory, locales=[], intro_details=None, settings_manager=None):
        logger.info(f"Initializing RubyI18NManager with directory: {directory}, locales: {locales}")
        super().__init__(directory, locales, intro_details, settings_manager)
        # Initialize file structure manager (after _locale_dir is set by parent __init__)
        base_locale_dir = os.path.join(self._directory, self._locale_dir)
        self._file_structure_manager = FileStructureManager(base_locale_dir, self.default_locale)
        
    @property
    def default_locale(self) -> str:
        """Get the default locale for this project.
        
        Returns:
            str: Project-specific default locale if available, otherwise global default
        """
        if self.settings_manager:
            return self.settings_manager.get_project_default_locale(self._directory)
        else:
            return self.intro_details.get('translation.default_locale', 'en')

    def _detect_locale_directory(self):
        """Detect which directory structure is being used for Rails i18n.
        
        Rails projects typically use config/locales for YAML translation files.
        
        Returns:
            str: The path to the locales directory (e.g., 'config/locales')
        """
        # Rails projects use config/locales
        config_locales_dir = os.path.join(self._directory, "config", "locales")
        
        if os.path.exists(config_locales_dir):
            logger.info("Using 'config/locales' directory structure (Rails i18n)")
            return "config/locales"
        
        # Fallback: check for locale or locales at root (for non-Rails Ruby projects)
        locale_dir = os.path.join(self._directory, "locale")
        locales_dir = os.path.join(self._directory, "locales")
        
        if os.path.exists(locales_dir):
            logger.info("Using 'locales' directory structure")
            return "locales"
        
        if os.path.exists(locale_dir):
            logger.info("Using 'locale' directory structure")
            return "locale"
        
        # Default to config/locales for Rails projects
        logger.info("No locale directory found. Defaulting to 'config/locales' directory structure")
        return "config/locales"

    def set_directory(self, directory):
        """Set a new project directory and reset translation state.
        
        Args:
            directory (str): The new project directory path
        """
        logger.debug(f"Setting new project directory: {directory}")
        self._directory = directory
        # Reset translation state
        self.translations: dict[TranslationKey, TranslationGroup] = {}
        self.written_locales = set()
        self.locales = []
        self.intro_details = {
            "first_author": "AUTHOR NAME <author@example.com>",
            "last_translator": "Translator Name <translator@example.com>",
            "application_name": "APPLICATION",
            "version": "1.0"
        }
        # Note: settings_manager is preserved when changing directory
        # Detect which directory structure is being used
        self._locale_dir = self._detect_locale_directory()
        # Reinitialize file structure manager with new directory
        base_locale_dir = os.path.join(self._directory, self._locale_dir)
        if self._file_structure_manager:
            self._file_structure_manager.reset()
        else:
            self._file_structure_manager = FileStructureManager(base_locale_dir, self.default_locale)
        base_locale_dir = os.path.join(self._directory, self._locale_dir)
        self._file_structure_manager = FileStructureManager(base_locale_dir, self.default_locale)
    
    def _custom_yaml_dump(self, data, stream, original_content=None, **kwargs):
        """Custom YAML dumper that quotes values but not keys, and preserves comments if possible.
        
        Uses ruamel.yaml if available, even for new files to ensure consistent quoting,
        otherwise falls back to PyYAML with custom dumper.
        """
        if RUAMEL_AVAILABLE:
            # Use ruamel.yaml for consistent quoting (even for new files without original_content)
            if original_content:
                # Has original content - preserve comments
                return self._ruamel_yaml_dump(data, stream, original_content, **kwargs)
            else:
                # New file - still use ruamel.yaml to ensure values are quoted consistently
                return self._ruamel_yaml_dump_new_file(data, stream, **kwargs)
        else:
            # Use PyYAML with custom dumper
            return self._pyyaml_dump(data, stream, **kwargs)
    
    def _ruamel_yaml_dump(self, data, stream, original_content, target_locale=None, **kwargs):
        """Dump YAML using ruamel.yaml to preserve comments and quote values.
        
        Args:
            data: The data to write (should be {locale: {...}})
            stream: File stream to write to
            original_content: Original file content to preserve comments
            target_locale: Target locale code (if original_content is from a different locale file)
        """
        ryaml = RuamelYAML()
        ryaml.preserve_quotes = True
        ryaml.width = 1000  # Prevent line wrapping
        ryaml.indent(mapping=2, sequence=4, offset=2)
        # Allow duplicate keys - the last value will be used, duplicates will be removed
        ryaml.allow_duplicate_keys = True
        
        # Load original to preserve structure and comments
        try:
            original_data = ryaml.load(original_content)
            
            # If original_content is from a different locale file (e.g., en.yml used as template for de.yml),
            # we need to replace the locale key in original_data
            if target_locale and isinstance(original_data, dict):
                # Find the default locale key in original_data
                default_locale_key = None
                for key in list(original_data.keys()):  # Use list() to avoid modification during iteration
                    if str(key) == str(self.default_locale):
                        default_locale_key = key
                        break
                
                # If we found the default locale key and it's different from target, replace it
                if default_locale_key and str(default_locale_key) != str(target_locale):
                    # Move the data from default locale to target locale
                    # IMPORTANT: Preserve ruamel.yaml structure to keep comments
                    locale_data = original_data.pop(default_locale_key)
                    # Assign to new key first (preserves structure)
                    original_data[target_locale] = locale_data
                    # Then quote string values in place (preserves comments)
                    self._quote_string_values_in_place(locale_data)
                    logger.debug(f"Replaced locale key '{default_locale_key}' with '{target_locale}' in original data")
            
            # Update with new data while preserving structure
            if isinstance(original_data, dict) and isinstance(data, dict):
                # Extract locale from data (data is {locale: {...}})
                # We need to merge into the same locale in original_data
                if len(data) == 1:
                    locale_key = list(data.keys())[0]
                    if locale_key in original_data:
                        # Merge the locale's data, not the whole structure
                        # This ensures we merge at the correct nesting level
                        # Ensure new values are quoted
                        quoted_data = self._quote_string_values(data[locale_key])
                        self._merge_ruamel_data(original_data[locale_key], quoted_data)
                    else:
                        # Locale doesn't exist in original, add it (with quoted values)
                        quoted_locale_data = self._quote_string_values(data[locale_key])
                        original_data[locale_key] = quoted_locale_data
                else:
                    # Multiple locales - merge each
                    for key, value in data.items():
                        if key in original_data:
                            quoted_value = self._quote_string_values(value)
                            self._merge_ruamel_data(original_data[key], quoted_value)
                        else:
                            original_data[key] = self._quote_string_values(value)
                
                # Dump the merged data
                ryaml.dump(original_data, stream)
            else:
                # New file or structure changed, just dump new data
                # Wrap string values in DoubleQuotedScalarString to force quotes
                quoted_data = self._quote_string_values(data)
                ryaml.dump(quoted_data, stream)
        except Exception as e:
            logger.warning(f"Could not preserve comments with ruamel.yaml: {e}, falling back to PyYAML")
            return self._pyyaml_dump(data, stream, **kwargs)
    
    def _ruamel_yaml_dump_new_file(self, data, stream, **kwargs):
        """Dump YAML using ruamel.yaml for new files (no original content to preserve).
        
        Ensures all string values are quoted consistently, even for new files.
        """
        ryaml = RuamelYAML()
        ryaml.preserve_quotes = True
        ryaml.width = 1000  # Prevent line wrapping
        ryaml.indent(mapping=2, sequence=4, offset=2)
        ryaml.allow_duplicate_keys = True
        
        # Quote all string values to ensure consistency
        quoted_data = self._quote_string_values(data)
        ryaml.dump(quoted_data, stream)
    
    def _merge_ruamel_data(self, original, new):
        """Merge new data into original ruamel.yaml structure.
        
        This performs a deep merge where:
        - If both original[key] and new[key] are dicts, recursively merge them
        - If original[key] exists but is not a dict (or new[key] is not a dict), replace it
        - If key doesn't exist in original, add it
        - String values (including empty strings) are wrapped in DoubleQuotedScalarString to ensure they're quoted
        
        This prevents duplicate keys by always replacing/updating existing keys rather than
        creating new ones.
        """
        if not isinstance(original, dict) or not isinstance(new, dict):
            # If either is not a dict, can't merge - this shouldn't happen in normal flow
            return
        
        for key, value in new.items():
            if key in original:
                # Key exists - need to merge or replace
                if isinstance(original[key], dict) and isinstance(value, dict):
                    # Both are dicts - recursively merge
                    self._merge_ruamel_data(original[key], value)
                else:
                    # One or both are not dicts - replace the value
                    # This handles the case where original has a string and new has a string
                    # or where types don't match (shouldn't happen, but be safe)
                    if isinstance(value, str):
                        # Quote all strings, including empty strings
                        original[key] = DoubleQuotedScalarString(value)
                    elif isinstance(value, dict):
                        # New value is a dict but original wasn't - replace entirely
                        original[key] = self._quote_string_values(value)
                    else:
                        original[key] = value
            else:
                # Key doesn't exist - add it
                if isinstance(value, str):
                    # Quote all strings, including empty strings
                    original[key] = DoubleQuotedScalarString(value)
                elif isinstance(value, dict):
                    original[key] = self._quote_string_values(value)
                else:
                    original[key] = value
    
    def _quote_string_values(self, data):
        """Recursively wrap string values in DoubleQuotedScalarString.
        
        This ensures all string values (including empty strings) are quoted
        when written to YAML files.
        
        Note: This converts ruamel.yaml structures to plain dicts, which loses comments.
        Use _quote_string_values_preserve_structure() if you need to preserve comments.
        """
        if isinstance(data, dict):
            return {k: self._quote_string_values(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._quote_string_values(item) for item in data]
        elif isinstance(data, str):
            # Quote all strings, including empty strings
            return DoubleQuotedScalarString(data)
        else:
            return data
    
    def _quote_string_values_in_place(self, data):
        """Recursively wrap string values in DoubleQuotedScalarString while preserving ruamel.yaml structure.
        
        This modifies the data structure in place, preserving all comments and structure.
        
        Args:
            data: Data structure (may be ruamel.yaml CommentedMap/CommentedSeq or plain dict/list)
        """
        try:
            from ruamel.yaml.comments import CommentedMap, CommentedSeq
        except ImportError:
            # Fallback if ruamel.yaml structure types aren't available
            # Can't modify in place, so return quoted version
            return self._quote_string_values(data)
        
        if isinstance(data, (dict, CommentedMap)):
            # Work directly with the structure to preserve comments
            for k, v in list(data.items()):
                if isinstance(v, str):
                    data[k] = DoubleQuotedScalarString(v)
                elif isinstance(v, (dict, CommentedMap, list, CommentedSeq)):
                    self._quote_string_values_in_place(v)
        elif isinstance(data, (list, CommentedSeq)):
            # Work directly with the structure to preserve comments
            for i, item in enumerate(data):
                if isinstance(item, str):
                    data[i] = DoubleQuotedScalarString(item)
                elif isinstance(item, (dict, CommentedMap, list, CommentedSeq)):
                    self._quote_string_values_in_place(item)
    
    def _pyyaml_dump(self, data, stream, **kwargs):
        """Dump YAML using PyYAML with custom dumper that quotes values but not keys."""
        class QuotedValueDumper(yaml.SafeDumper):
            """Custom dumper that quotes string values but not keys."""
            pass
        
        def str_representer(dumper, data):
            """Represent strings with double quotes."""
            # Force all strings to be quoted
            return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')
        
        QuotedValueDumper.add_representer(str, str_representer)
        
        # Dump with custom dumper
        import io
        import re
        output = io.StringIO()
        yaml.dump(data, output, Dumper=QuotedValueDumper, default_flow_style=False, 
                 allow_unicode=True, sort_keys=False, width=1000, **kwargs)
        content = output.getvalue()
        
        # Post-process to unquote keys (but keep values quoted)
        # The challenge: we need to identify which quoted strings are keys vs values
        # Keys are always followed by ':' on the same line
        # Values are on lines that don't end with ':' (or are indented more)
        
        lines = content.split('\n')
        processed_lines = []
        
        for i, line in enumerate(lines):
            # Check if this line has a quoted key
            # Pattern: (optional spaces) + "key": (possibly with value)
            # We need to handle both top-level keys (no indentation) and nested keys (with indentation)
            
            # Match: "key": value or "key": (with or without leading whitespace)
            # Key pattern: quoted string followed by colon (possibly with space and value)
            key_pattern = r'^(\s*)"([^"]+)":(\s+.*)?$'
            match = re.match(key_pattern, line)
            
            if match:
                # This is a key line - unquote the key
                indent = match.group(1)  # Can be empty for top-level keys
                quoted_key = match.group(2)
                rest = match.group(3) or ''
                key = quoted_key
                processed_lines.append(f"{indent}{key}:{rest}")
            else:
                # Check if this is a value line (indented, starts with quote, doesn't end with :)
                # If it's a value line, keep it quoted
                processed_lines.append(line)
        
        content = '\n'.join(processed_lines)
        stream.write(content)

    def create_mo_files(self, results: TranslationManagerResults):
        """Create compiled translation files.
        
        For Ruby/Rails projects, this is a no-op since Rails doesn't use
        compiled MO files - it loads YAML files directly.
        
        This method intentionally does nothing for Ruby projects. No errors
        are set in results since this is expected behavior, not a failure.
        
        Args:
            results: Results object to track failures (unused for Ruby, no errors set)
        """
        logger.info("Rails projects don't use MO files - YAML files are loaded directly. Skipping compilation step.")
        # No-op for Ruby/Rails projects - this is intentional, not an error

    def _create_ruby_results(self, action: TranslationAction) -> 'TranslationManagerResults':
        """Create TranslationManagerResults for Ruby/Rails YAML-based projects.
        
        For Ruby projects, we interpret:
        - has_pot_file: True if locale directory exists and has any YAML files
        - has_po_file: True if locale has YAML files
        - has_mo_file: Always False (Rails doesn't use MO files)
        """
        from i18n.translation_manager_results import TranslationManagerResults, LocaleStatus
        
        locale_dir = os.path.join(self._directory, self._locale_dir)
        has_locale = os.path.exists(locale_dir) and os.path.isdir(locale_dir)
        
        # Check if there are any YAML files (equivalent to "has POT file")
        has_yaml_files = False
        if has_locale:
            yaml_files = list(Path(locale_dir).rglob("*.yml"))
            has_yaml_files = len(yaml_files) > 0
        
        # Scan for locales (subdirectories in config/locales)
        locale_statuses = {}
        if has_locale:
            for item in os.listdir(locale_dir):
                full_path = os.path.join(locale_dir, item)
                if os.path.isdir(full_path) and not item.startswith('__'):
                    # Check if this locale directory has YAML files
                    yaml_files = list(Path(full_path).rglob("*.yml"))
                    has_yaml = len(yaml_files) > 0
                    
                    # Get the most recent modification time from YAML files
                    last_mod = None
                    if yaml_files:
                        last_mod = datetime.fromtimestamp(max(os.path.getmtime(f) for f in yaml_files))
                    
                    # For Ruby, we use has_po_file to indicate YAML files exist
                    status = LocaleStatus(
                        locale_code=item,
                        has_directory=True,
                        has_po_file=has_yaml,  # YAML files = "PO files" for Ruby
                        has_mo_file=False,    # Rails doesn't use MO files
                        po_file_path=full_path if has_yaml else None,
                        mo_file_path=None,
                        last_modified=last_mod
                    )
                    locale_statuses[item] = status
        
        results = TranslationManagerResults(
            project_dir=self._directory,
            action=action,
            action_timestamp=datetime.now(),
            action_successful=True,
            locale_statuses=locale_statuses,
            failed_locales=[],
            default_locale=self.default_locale,
            has_locale_dir=has_locale,
            has_pot_file=has_yaml_files,  # YAML files = "POT file" for Ruby
            pot_file_path=locale_dir if has_yaml_files else None,
            pot_last_modified=datetime.fromtimestamp(os.path.getmtime(locale_dir)) if has_locale else None,
        )
        return results

    def manage_translations(self, action: TranslationAction = TranslationAction.CHECK_STATUS, modified_locales: set[str] = None):
        """Manage translations based on the specified action.
        
        Args:
            action (TranslationAction): The action to perform. Defaults to CHECK_STATUS.
            modified_locales (set, optional): Set of locales that have been modified and need updating.
            
        Returns:
            TranslationManagerResults: Results of the translation management operation.
        """
        results = self._create_ruby_results(action)
        results.failed_locales = []
        results.action_successful = True
        
        try:
            # Get YAML files for all locales
            yaml_files_by_locale = self.gather_yaml_files()
            logger.debug(f"Found YAML files for {len(yaml_files_by_locale)} locales")
            
            # Only parse files and fill translations during CHECK_STATUS
            if action == TranslationAction.CHECK_STATUS:
                # Parse YAML files to extract translations
                if results.has_locale_dir:
                    self._parse_yaml_files(yaml_files_by_locale)
                    # Populate self.locales from the parsed YAML files
                    # Only include actual locale directories (subdirectories), sorted
                    self.locales = sorted(list(yaml_files_by_locale.keys()))
                    logger.info(f"Populated {len(self.locales)} locales from YAML files: {self.locales}")
                    
                    # Check for file structure discrepancies (logging handled by file structure manager)
                    self.check_file_structure_parity()
                else:
                    logger.warning("No locale directory found, cannot parse YAML files")
            
            # Update statistics
            if self.translations:
                results.total_strings = len(self.translations)
                results.total_locales = len(results.locale_statuses)
                
                # Get invalid translations info
                results.invalid_groups = self.get_invalid_translations()
            
            # Perform requested action
            if action == TranslationAction.WRITE_PO_FILES:
                # Fix any invalid translations that we can before writing files
                if self.fix_invalid_translations():
                    logger.debug("Applied fixes for invalid translations")
                self.write_po_files(modified_locales, results)
            elif action == TranslationAction.WRITE_MO_FILES:
                # Rails doesn't use MO files, so this is a no-op
                logger.info("Rails projects don't use MO files, skipping")
            elif action == TranslationAction.GENERATE_POT:
                if not self.generate_pot_file():
                    results.action_successful = False
                    results.extend_error_message("Failed to generate base translation structure")
            
            results.determine_action_successful()
            return results
        
        except Exception as e:
            results.action_successful = False
            results.error_message = str(e)
            logger.error(f"Error in manage_translations: {e}", exc_info=True)
            return results

    def get_po_file_path(self, locale):
        """Get the path to the translation file for a specific locale.
        
        For Ruby/Rails projects, this returns the locale directory path
        (YAML files are organized in subdirectories).
        
        Args:
            locale: Locale code
            
        Returns:
            str: Path to the locale directory
        """
        return os.path.join(self._directory, self._locale_dir, locale)
    
    def get_pot_file_path(self):
        """Get the path to the base translation directory.
        
        For Ruby/Rails projects, this returns the locales directory path
        (equivalent to POT file location for gettext projects).
        
        Returns:
            str: Path to the locales directory
        """
        return os.path.join(self._directory, self._locale_dir)

    def check_file_structure_parity(self) -> None:
        """Check and log file structure parity across locales."""
        yaml_files_by_locale = self.gather_yaml_files()
        self._file_structure_manager.check_file_structure_parity(
            yaml_files_by_locale, self._directory
        )

    def gather_yaml_files(self) -> dict[str, list[str]]:
        """Gather all YAML translation files organized by locale.
        
        Rails supports two structures:
        1. Directory structure: config/locales/en/application.yml
        2. Flat files: config/locales/en.yml, config/locales/devise.en.yml
        
        Returns:
            dict: Dictionary mapping locale codes to lists of YAML file paths
        """
        locale_dir = os.path.join(self._directory, self._locale_dir)
        yaml_files_by_locale = {}
        
        if not os.path.exists(locale_dir):
            return yaml_files_by_locale
        
        # First, look for locale subdirectories (e.g., config/locales/en/, config/locales/es/)
        for item in os.listdir(locale_dir):
            item_path = os.path.join(locale_dir, item)
            
            if os.path.isdir(item_path) and not item.startswith('__'):
                locale = item
                # Find all YAML files in this locale directory
                locale_yaml_files = list(Path(item_path).rglob("*.yml"))
                
                if locale_yaml_files:
                    if locale not in yaml_files_by_locale:
                        yaml_files_by_locale[locale] = []
                    yaml_files_by_locale[locale].extend([str(f) for f in locale_yaml_files])
                    logger.debug(f"Found {len(locale_yaml_files)} YAML files in locale directory {locale}")
        
        # Second, look for flat YAML files directly in config/locales/
        # Files like en.yml, devise.en.yml contain locale-specific translations
        for item in os.listdir(locale_dir):
            item_path = os.path.join(locale_dir, item)
            
            if os.path.isfile(item_path) and item.endswith('.yml'):
                # Try to extract locale from filename
                # Patterns: en.yml, devise.en.yml, en-GB.yml
                base_name = os.path.splitext(item)[0]
                
                # Check for patterns like "devise.en" or just "en"
                if '.' in base_name:
                    # Pattern: devise.en -> locale is "en"
                    parts = base_name.split('.')
                    # Last part before .yml should be locale
                    potential_locale = parts[-1]
                else:
                    # Pattern: en.yml -> locale is "en"
                    potential_locale = base_name
                
                # Validate it looks like a locale code (2-5 chars, alphanumeric with possible dash/underscore)
                if re.match(r'^[a-z]{2}([-_][A-Z]{2})?$', potential_locale, re.IGNORECASE):
                    locale = potential_locale
                    if locale not in yaml_files_by_locale:
                        yaml_files_by_locale[locale] = []
                    yaml_files_by_locale[locale].append(item_path)
                    logger.debug(f"Found flat YAML file {item} for locale {locale}")
                else:
                    logger.debug(f"Skipping YAML file {item} - couldn't determine locale from filename")
        
        logger.info(f"Gathered YAML files for {len(yaml_files_by_locale)} locales: {list(yaml_files_by_locale.keys())}")
        return yaml_files_by_locale
    
    def gather_files(self):
        """Legacy method for compatibility. For Ruby, use gather_yaml_files() instead."""
        # This method is kept for interface compatibility but shouldn't be used for Ruby
        raise NotImplementedError("Ruby projects use YAML files. Use gather_yaml_files() instead.")

    def _parse_yaml_files(self, yaml_files_by_locale: dict[str, list[str]]):
        """Parse YAML translation files and extract translations.
        
        Rails i18n uses nested YAML structures like:
        en:
          tasks:
            form:
              title: "Task Details"
        
        We flatten these to translation keys like "tasks.form.title" and use
        the locale as the key (e.g., "en").
        
        Also tracks source file paths for each translation key so we can update
        the original files when writing.
        
        Args:
            yaml_files_by_locale: Dictionary mapping locale codes to lists of YAML file paths
        """
        logger.debug(f"Parsing YAML files for {len(yaml_files_by_locale)} locales")
        
        # Track which translation keys exist in the default locale (base)
        default_locale = self.default_locale
        base_keys = set()
        
        # First pass: parse default locale to establish base translations
        if default_locale in yaml_files_by_locale:
            for yaml_file in yaml_files_by_locale[default_locale]:
                try:
                    # Store original file content to preserve comments
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        original_content = f.read()
                        self._file_structure_manager.set_original_content(yaml_file, original_content)
                    
                    # Parse YAML data
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    
                    # Track this file as a default locale file (for replicating structure)
                    self._file_structure_manager.add_default_locale_file(yaml_file)
                    
                    if data and default_locale in data:
                        keys = self._extract_translation_keys(data[default_locale], prefix="")
                        for key in keys:
                            base_keys.add(key)
                            # Create translation group if it doesn't exist
                            translation_key = TranslationKey(key)
                            if translation_key not in self.translations:
                                group = TranslationGroup(key, is_in_base=True)
                                self.translations[group.key] = group
                            # Track source file for this key/locale
                            self._file_structure_manager.set_source_file(key, default_locale, yaml_file)
                            # Add the default locale translation
                            value = self._get_nested_value(data[default_locale], key)
                            if value:
                                self.translations[translation_key].add_translation(default_locale, value)
                except Exception as e:
                    logger.warning(f"Error parsing YAML file {yaml_file}: {e}")
        
        # Second pass: parse all other locales
        for locale, yaml_files in yaml_files_by_locale.items():
            if locale == default_locale:
                continue  # Already processed
            
            for yaml_file in yaml_files:
                try:
                    # Store original file content to preserve comments
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        original_content = f.read()
                        self._file_structure_manager.set_original_content(yaml_file, original_content)
                    
                    # Parse YAML data
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    
                    if data and locale in data:
                        keys = self._extract_translation_keys(data[locale], prefix="")
                        for key in keys:
                            translation_key = TranslationKey(key)
                            # Only add translations for keys in base
                            if key in base_keys or translation_key in self.translations:
                                if translation_key not in self.translations:
                                    # Key exists in this locale but not in base
                                    group = TranslationGroup(key, is_in_base=False)
                                    self.translations[group.key] = group
                                else:
                                    group = self.translations[translation_key]
                                # Track source file for this key/locale
                                self._file_structure_manager.set_source_file(key, locale, yaml_file)
                                value = self._get_nested_value(data[locale], key)
                                if value:
                                    self.translations[group.key].add_translation(locale, value)
                except Exception as e:
                    logger.warning(f"Error parsing YAML file {yaml_file}: {e}")
        
        logger.debug(f"Parsed {len(self.translations)} translation keys")
    
    def _extract_translation_keys(self, data: dict, prefix: str = "") -> list[str]:
        """Recursively extract translation keys from nested YAML structure.
        
        Args:
            data: Dictionary from YAML file
            prefix: Current key prefix (for nested keys)
            
        Returns:
            list: List of flattened translation keys (e.g., ["tasks.form.title"])
        """
        keys = []
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                # Recursively extract keys from nested dictionaries
                keys.extend(self._extract_translation_keys(value, full_key))
            else:
                # Leaf node - this is a translation key
                keys.append(full_key)
        return keys
    
    def _get_nested_value(self, data: dict, key: str) -> str:
        """Get a value from nested dictionary using dot-notation key.
        
        Args:
            data: Dictionary from YAML file
            key: Dot-notation key (e.g., "tasks.form.title")
            
        Returns:
            str: The translation value, or None if not found
        """
        parts = key.split('.')
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return str(current) if current is not None else None

    def get_msgid(self, line):
        msgid = line[7:-2]
        return msgid

    def _get_po_locale(self, PO):
        _dirname1 = os.path.dirname(PO)
        _dirname2 = os.path.dirname(_dirname1)
        return os.path.basename(_dirname2)

    def _parse_po(self, PO, locale):
        """Parse a PO file using polib.
        
        NOTE: This is a legacy method for POT/PO workflow. Not used in YAML workflow.
        
        Args:
            PO (str): Path to the PO file
            locale (str): Locale code
        """
        import polib
        logger.debug(f"Parsing PO file: {PO} for locale: {locale}")
        # Use include_obsolete=True and include_previous=True to ensure comments are parsed
        po = polib.pofile(PO, encoding='utf-8', include_obsolete=True, include_previous=True)
        logger.debug(f"Found {len(po)} entries in PO file")
        
        # Initialize counters
        total_entries = 0
        entries_with_newlines = 0
        entries_with_explicit_newlines = 0
        entries_with_actual_newlines = 0
        total_explicit_newlines = 0
        total_actual_newlines = 0
        entries_with_comments = 0
        explicit_newline = '\\n'
        actual_newline = '\n'
        
        for entry in po:
            if entry.msgid and entry.msgid.strip():
                total_entries += 1
                
                # Debug logging for comment handling
                if entry.comment or entry.tcomment:
                    entries_with_comments += 1
                
                # Debug logging for newline handling
                if entry.msgstr and ('\n' in entry.msgstr or '\\n' in entry.msgstr):
                    entries_with_newlines += 1
                    has_explicit = explicit_newline in entry.msgstr
                    has_actual = actual_newline in entry.msgstr
                    
                    # logger.debug(f"Found newlines in msgstr for msgid '{entry.msgid}':")
                    # logger.debug(f"  Raw msgstr: {repr(entry.msgstr)}")
                    if has_explicit:
                        entries_with_explicit_newlines += 1
                        total_explicit_newlines += entry.msgstr.count(explicit_newline)
                        # logger.debug(f"  Number of '\\n' sequences: {entry.msgstr.count(explicit_newline)}")
                    # else:
                        # logger.debug(f"  Contains '\\n': {has_explicit}")
                    if has_actual:
                        entries_with_actual_newlines += 1
                        total_actual_newlines += entry.msgstr.count(actual_newline)
                        # logger.debug(f"  Number of actual newlines: {entry.msgstr.count(actual_newline)}")
                    # else:
                        # logger.debug(f"  Contains actual newline: {has_actual}")
                
                group = TranslationGroup.from_polib_entry(entry, is_in_base=False)
                if group.key in self.translations:
                    self.translations[group.key].add_translation(locale, entry.msgstr)
                else:
                    group.add_translation(locale, entry.msgstr)
                    self.translations[group.key] = group
        
        # Log summary statistics
        logger.info(f"PO file {PO} statistics:")
        logger.info(f"  Total entries: {total_entries}")
        logger.info(f"  Entries with comments: {entries_with_comments}")
        logger.info(f"  Entries with any newlines: {entries_with_newlines}")
        logger.info(f"  Entries with explicit '\\n': {entries_with_explicit_newlines}")
        logger.info(f"  Total '\\n' sequences: {total_explicit_newlines}")
        logger.info(f"  Entries with actual newlines: {entries_with_actual_newlines}")
        logger.info(f"  Total actual newlines: {total_actual_newlines}")

    def _fill_translations(self, PO_files):
        for PO in PO_files:
            locale = self._get_po_locale(PO)
            if not locale in self.locales:
                self.locales.append(locale)
            self._parse_po(PO, locale)

    def write_new_files(self, PO_files):
        for PO in PO_files:
            locale = self._get_po_locale(PO)
            print(f"Writing new file {locale} to {PO}")
            self.write_po_file(PO, locale)

    def write_po_files(self, modified_locales: set[str], results: TranslationManagerResults):
        """Write YAML translation files for modified locales.
        
        For Ruby/Rails projects, this writes YAML files organized by namespace
        (models, views, etc.) as per Rails i18n conventions.
        
        Args:
            modified_locales (set[str]): Set of locales to update. If None or empty, updates all locales.
            results (TranslationManagerResults): Results object to track failures
        """
        # Determine which locales to update
        if modified_locales:
            # Use specified locales
            locales_to_update = modified_locales
        else:
            # If no specific locales, update all locales that have translations in memory
            # This includes locales from self.locales (parsed from files) and any locales
            # that have translations in memory (e.g., newly added locales)
            locales_to_update = set(self.locales)
            # Also check for any locales that have translations in memory but aren't in self.locales
            for key, group in self.translations.items():
                if group.is_in_base:
                    locales_to_update.update(group.values.keys())
        
        successful_updates = []
        
        for locale in locales_to_update:
            # Write the locale even if it's not in results.locale_statuses
            # (e.g., newly added locales that don't have files yet)
            if self.write_locale_yaml_files(locale):
                successful_updates.append(locale)
                self.written_locales.add(locale)
                logger.info(f"Successfully wrote YAML files for locale {locale}")
            else:
                results.failed_locales.append(locale)
                logger.error(f"Failed to write YAML files for locale {locale}")
                    
        if results.failed_locales:
            results.extend_error_message(f"Failed to write YAML files for locales: {results.failed_locales}")
            
        # Set flag if any files were successfully updated
        if successful_updates:
            results.po_files_updated = True
            results.updated_locales = successful_updates
            logger.info(f"Successfully updated YAML files for {len(successful_updates)} locales: {successful_updates}")

    def write_po_file(self, po_file, locale):
        """Write translations to a PO file for a specific locale using polib.
        
        NOTE: This is a legacy method for POT/PO workflow. Not used in YAML workflow.
        
        Args:
            po_file (str): Path to the PO file
            locale (str): Locale code
        """
        import polib
        try:
            logger.debug(f"Starting to write PO file for locale {locale}: {po_file}")
            
            # Create a new PO file
            po = polib.POFile()
            logger.debug("Created new POFile object")
            
            # Set metadata
            metadata = {
                'Project-Id-Version': self.intro_details["version"],
                'POT-Creation-Date': time.strftime('%Y-%m-%d %H:%M%z'),
                'PO-Revision-Date': time.strftime('%Y-%m-%d %H:%M%z'),
                'Last-Translator': self.intro_details["last_translator"],
                'Language': locale,
                'Language-Team': f"{locale} Team <<EMAIL>>",
                'MIME-Version': '1.0',
                'Content-Type': 'text/plain; charset=UTF-8',
                'Content-Transfer-Encoding': '8bit',
                'Plural-Forms': 'nplurals=2; plural=(n != 1);'
            }
            po.metadata = metadata
            logger.debug(f"Set PO file metadata: {metadata}")
            
            # Add translations
            translation_count = 0
            for key, group in self.translations.items():
                if not group.is_in_base:
                    continue
                msgid = group.key.msgid
                # Extract comments
                comment = None
                tcomment = None
                if group.usage_comment:
                    comment = group.usage_comment.strip('#\n')
                if group.tcomment:
                    tcomment = group.tcomment.strip('#\n')
                # Get the translation and ensure it's properly encoded
                msgstr = group.get_translation_unescaped(locale) or ""
                try:
                    entry = polib.POEntry(
                        msgid=msgid,
                        msgstr=msgstr,
                        comment=comment,
                        tcomment=tcomment,
                        occurrences=group.occurrences  # Include occurrences
                    )
                    po.append(entry)
                    translation_count += 1
                    if translation_count % 100 == 0:  # Log progress every 100 entries
                        logger.debug(f"Added {translation_count} translations so far...")
                except Exception as e:
                    logger.error(f"Error creating POEntry for msgid '{msgid}': {e}")
                    logger.error(f"  msgstr: {repr(msgstr)}")
                    logger.error(f"  comment: {repr(comment)}")
                    logger.error(f"  tcomment: {repr(tcomment)}")
                    logger.error(f"  occurrences: {repr(group.occurrences)}")
                    raise
            
            logger.debug(f"Finished adding {translation_count} translations")
            
            # Save the file
            try:
                logger.debug(f"Attempting to save PO file to: {po_file}")
                po.save(po_file)
                logger.debug("Successfully saved PO file")
            except Exception as e:
                logger.error(f"Error saving PO file: {e}")
                logger.error(f"File path: {po_file}")
                logger.error(f"Number of entries: {translation_count}")
                raise
            
            logger.debug(f"Wrote {translation_count} translations to PO file")
            
            # Mark this locale as having been written to
            self.written_locales.add(locale)
            
            # If all locales have been written to at least once, purge stale translations
            if self.written_locales.issuperset(self.locales):
                self._purge_stale_translations()
                
        except Exception as e:
            logger.error(f"Failed to write PO file for locale {locale}: {e}")
            raise

    def _purge_stale_translations(self):
        """Remove translations that are not in base once all locales have been written."""
        stale_keys = [key for key, group in self.translations.items() if not group.is_in_base]
        for key in stale_keys:
            del self.translations[key]
        if stale_keys:
            logger.debug(f"Purged {len(stale_keys)} stale translations")

    def get_POT_intro_details(self, locale="en", first_author="THOMAS HALL", year=None, application_name="APPLICATION", version="1.0", last_translator=""):
        timestamp = time.strftime('%Y-%m-%d %H:%M%z')
        year = time.strftime('%Y') if year is None else year
        return f'''# {application_name} TRANSLATIONS
# {first_author}, {year}.
#
msgid ""
msgstr ""
"Project-Id-Version: {version}\\n"
"POT-Creation-Date: {timestamp}\\n"
"PO-Revision-Date: {timestamp}\\n"
"Last-Translator: {last_translator}\\n"
"Language: {locale}\\n"
"Language-Team: {locale} Team <<EMAIL>>\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"


'''

    def write_locale_yaml_files(self, locale: str) -> bool:
        """Write YAML translation files for a specific locale.
        
        Ensures file structure parity: all non-default locales will have the same
        file structure as the default locale. Missing files are created, and all
        keys from default locale files are ensured to be present (with empty strings
        if translations are missing).
        
        NOTE: This parity enforcement is still imperfect for projects that already
        have a partially-localized tree (extra/missing files, mixed flat vs.
        directory layouts, etc.). We currently detect discrepancies and try to
        create/update missing files, but there are known edge cases where content
        still ends up only in the flat `de.yml` / `es.yml` / `fr.yml` files instead
        of per-namespace files. This will need a dedicated, more robust \"repair
        parity\" pass in the future.
        
        Updates existing source files when available, otherwise creates new files
        based on namespace heuristics. Preserves existing file structure.
        
        COMMENT PRESERVATION BEHAVIOR:
        =============================
        This method preserves comments in YAML files according to the following priority:
        
        1. **Current Locale File Exists**: If the target locale already has a YAML file,
           comments from that file are preserved. This ensures locale-specific comments
           (e.g., translator notes, locale-specific instructions) are maintained.
        
        2. **Default Locale Template**: If the target locale file does NOT exist, comments
           are transferred from the corresponding default locale file. This allows new
           locale files to inherit helpful comments from the default locale (e.g., "# Load
           structured locale files", "# Models", etc.) while still allowing locale-specific
           files to override with their own comments once created.
        
        3. **New Files**: For completely new files (not based on default locale structure),
           no comments are preserved (new files start without comments).
        
        This behavior ensures that:
        - Existing locale files maintain their own comments
        - New locale files inherit helpful comments from the default locale
        - Comments are never lost when updating existing files
        - Locale-specific comments can be added and will be preserved in future updates
        
        Args:
            locale (str): The locale code to write YAML files for
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            base_locale_dir = os.path.join(self._directory, self._locale_dir)
            locale_dir = os.path.join(base_locale_dir, locale)
            
            # Check if we have flat files for this locale (en.yml directly in config/locales/)
            flat_file = os.path.join(base_locale_dir, f"{locale}.yml")
            has_flat_file = os.path.exists(flat_file)
            
            # For directory structure, create locale_dir if needed
            if not has_flat_file and not os.path.exists(locale_dir):
                os.makedirs(locale_dir, exist_ok=True)
            
            logger.debug(f"Writing YAML files for locale {locale}")
            
            # Organize translations by source file (or determined file)
            translations_by_file = {}  # {file_path: {nested_dict}}
            file_metadata = {}  # {file_path: {'is_flat': bool, 'original_data': dict}}
            skipped_no_value = 0
            skipped_not_in_base = 0
            
            for key, group in self.translations.items():
                if not group.is_in_base:
                    skipped_not_in_base += 1
                    continue
                
                # Extract string key from TranslationKey object for file lookups
                key_str = key.msgid if hasattr(key, 'msgid') else str(key)
                
                # Get translation value for this locale
                # If no translation exists, use empty string (will be written as "")
                value = group.get_translation_unescaped(locale)
                is_empty = not value
                if is_empty:
                    # Use empty string instead of skipping - this ensures all keys are present
                    value = ""
                    skipped_no_value += 1
                    # Log if this key was expected to have a value (for debugging duplicate issues)
                    if self._file_structure_manager.get_default_source_file(key_str):
                        logger.debug(f"Writing empty value for {key_str} in {locale} (no translation found)")
                
                # Determine target file - prefer source file if available
                source_file = self._file_structure_manager.get_source_file(key_str, locale)
                if source_file and os.path.exists(source_file):
                    # Use existing source file for this locale
                    file_path = source_file
                    # Check if it's a flat file (directly in config/locales/, not in locale subdirectory)
                    is_flat = self._file_structure_manager.is_flat_file(source_file)
                else:
                    # No source file for this locale - try to use default locale's source file and convert path
                    default_source_file = self._file_structure_manager.get_default_source_file(key_str)
                    if default_source_file:
                        # Convert default locale file path to target locale file path
                        target_file = self._file_structure_manager.translate_file_path(default_source_file, locale)
                        if target_file:
                            file_path = target_file
                            is_flat = self._file_structure_manager.is_flat_file(target_file)
                        else:
                            # Fallback to heuristics if conversion failed
                            if has_flat_file:
                                file_path = flat_file
                                is_flat = True
                            else:
                                file_path = self._determine_yaml_file_path(key_str, locale_dir)
                                is_flat = False
                    else:
                        # No source file at all - determine new file path using heuristics
                        # If we have a flat file for this locale, use it; otherwise use directory structure
                        if has_flat_file:
                            file_path = flat_file
                            is_flat = True
                        else:
                            file_path = self._determine_yaml_file_path(key_str, locale_dir)
                            is_flat = False
                
                # Load existing file content if it exists (to preserve structure and comments)
                if file_path not in translations_by_file:
                    translations_by_file[file_path] = {}
                    file_metadata[file_path] = {
                        'is_flat': is_flat, 
                        'original_data': None,
                        'original_content': None,
                        'preserve_comments': False
                    }
                    
                    if os.path.exists(file_path):
                        try:
                            # Store original content for comment preservation
                            with open(file_path, 'r', encoding='utf-8') as f:
                                original_content = f.read()
                                file_metadata[file_path]['original_content'] = original_content
                                file_metadata[file_path]['preserve_comments'] = True
                            
                            # Parse YAML data
                            with open(file_path, 'r', encoding='utf-8') as f:
                                existing_data = yaml.safe_load(f) or {}
                                file_metadata[file_path]['original_data'] = existing_data
                                # Extract existing translations for this locale
                                # IMPORTANT: Preserve ALL existing keys, not just ones we're updating
                                if locale in existing_data and isinstance(existing_data[locale], dict):
                                    # Deep copy to preserve all nested structure
                                    import copy
                                    translations_by_file[file_path] = copy.deepcopy(existing_data[locale])
                                normalized_file_path = os.path.normpath(file_path).replace('\\', '/')
                                logger.debug(f"Loaded existing content from {normalized_file_path}")
                        except Exception as e:
                            logger.warning(f"Could not load existing content from {file_path}: {e}")
                    elif self._file_structure_manager.has_original_content(file_path):
                        # Use original content from default locale file if available
                        file_metadata[file_path]['original_content'] = self._file_structure_manager.get_original_content(file_path)
                        file_metadata[file_path]['preserve_comments'] = True
                
                # Add/update translation in nested structure
                # The key format is like "views.tasks.index.select_project"
                # _add_to_nested_dict will overwrite if the key already exists, preventing duplicates
                self._add_to_nested_dict(translations_by_file[file_path], key_str, value)
            
            # For non-default locales, ensure all files from default locale are created/updated
            # This ensures file structure parity: all locales have the same files as the default locale
            if locale != self.default_locale:
                default_locale_dir = os.path.join(base_locale_dir, self.default_locale)
                files_created_for_parity = []
                for default_file in self._file_structure_manager.get_default_locale_files():
                    # Convert default locale file path to target locale file path
                    target_file = self._file_structure_manager.translate_file_path(default_file, locale)
                    
                    # Ensure file exists in translations_by_file (create if missing, even if file exists on disk)
                    # This ensures file structure parity: all locales have the same files as default locale
                    if target_file and target_file not in translations_by_file:
                        # Determine if it's a flat file
                        is_flat = self._file_structure_manager.is_flat_file(target_file)
                        
                        # Initialize file structure (will be populated with translations)
                        translations_by_file[target_file] = {}
                        file_metadata[target_file] = {
                            'is_flat': is_flat,
                            'original_data': None,
                            'original_content': self._file_structure_manager.get_original_content(default_file),
                            'preserve_comments': self._file_structure_manager.has_original_content(default_file)
                        }
                        
                        # If file exists on disk, load its existing content to preserve structure
                        if os.path.exists(target_file):
                            try:
                                with open(target_file, 'r', encoding='utf-8') as f:
                                    existing_content = f.read()
                                    file_metadata[target_file]['original_content'] = existing_content
                                    file_metadata[target_file]['preserve_comments'] = True
                                
                                with open(target_file, 'r', encoding='utf-8') as f:
                                    existing_data = yaml.safe_load(f) or {}
                                    if locale in existing_data and isinstance(existing_data[locale], dict):
                                        import copy
                                        translations_by_file[target_file] = copy.deepcopy(existing_data[locale])
                                        file_metadata[target_file]['original_data'] = existing_data
                                normalized_target = os.path.normpath(target_file).replace('\\', '/')
                                logger.debug(f"Loaded existing content from {normalized_target} for structure parity")
                            except Exception as e:
                                logger.warning(f"Could not load existing content from {target_file}: {e}")
                        
                        # Populate with all translations that belong to this file (from default locale)
                        # This ensures all keys from default locale file are present in target locale file
                        for key, group in self.translations.items():
                            if not group.is_in_base:
                                continue
                            
                            # Extract string key from TranslationKey object
                            key_str = key.msgid if hasattr(key, 'msgid') else str(key)
                            
                            # Check if this key's default locale source file matches default_file
                            default_source = self._file_structure_manager.get_default_source_file(key_str)
                            if default_source == default_file:
                                # Get translation value (use empty string if missing)
                                value = group.get_translation_unescaped(locale)
                                if not value:
                                    value = ""  # Use empty string instead of skipping
                                
                                # Add/update this key in the file (will overwrite existing if present)
                                self._add_to_nested_dict(translations_by_file[target_file], key_str, value)
                        
                        files_created_for_parity.append(target_file)
                
                if files_created_for_parity:
                    logger.info(f"Ensured file structure parity for locale {locale}: created/updated {len(files_created_for_parity)} files to match default locale")
            
            if not translations_by_file:
                logger.warning(f"No translations to write for locale {locale} (skipped {skipped_no_value} with no value, {skipped_not_in_base} not in base)")
                return True
            
            # Write each YAML file
            for file_path, data in translations_by_file.items():
                # Ensure parent directory exists (but don't create locale/ for flat files)
                file_dir = os.path.dirname(file_path)
                if file_dir and file_dir != base_locale_dir:
                    os.makedirs(file_dir, exist_ok=True)
                
                metadata = file_metadata[file_path]
                
                # For flat files, preserve the entire structure (may have multiple locales)
                if metadata['is_flat']:
                    if metadata['original_data']:
                        # Preserve existing structure and update just this locale
                        yaml_data = metadata['original_data'].copy()
                        yaml_data[locale] = data
                    else:
                        # New flat file, just create with this locale
                        yaml_data = {locale: data}
                else:
                    # For directory structure, wrap in locale key
                    yaml_data = {locale: data}
                
                # Write YAML file with custom dumper (quotes values, not keys)
                with open(file_path, 'w', encoding='utf-8') as f:
                    # Use ruamel.yaml if available (for consistent quoting, even for new files)
                    # Pass original_content if available for comment preservation
                    original_content = metadata.get('original_content')
                    # If original_content is from default locale file but we're writing to a different locale,
                    # pass target_locale so we can replace the locale key in the original content
                    # This happens when we're creating new files for non-default locales using the default locale file as a template
                    # Simple check: if we have original_content and we're writing to a non-default locale, replace the key
                    target_locale_for_dump = locale if (original_content and locale != self.default_locale) else None
                    
                    self._custom_yaml_dump(yaml_data, f, original_content=original_content, target_locale=target_locale_for_dump)
                
                # Normalize path for consistent logging (use forward slashes for readability)
                normalized_path = os.path.normpath(file_path).replace('\\', '/')
                logger.debug(f"Wrote YAML file: {normalized_path} ({len(data)} top-level keys, flat={metadata['is_flat']})")
            
            # Count actual empty values written
            empty_values_written = 0
            for file_data in translations_by_file.values():
                def count_empty_values(d):
                    count = 0
                    for v in d.values():
                        if isinstance(v, dict):
                            count += count_empty_values(v)
                        elif v == "":
                            count += 1
                    return count
                empty_values_written += count_empty_values(file_data)
            
            if empty_values_written > 0:
                logger.info(f"Successfully wrote {len(translations_by_file)} YAML files for locale {locale} ({empty_values_written} empty values written)")
            else:
                logger.info(f"Successfully wrote {len(translations_by_file)} YAML files for locale {locale}")
            return True
            
        except Exception as e:
            logger.error(f"Error writing YAML files for locale {locale}: {e}", exc_info=True)
            return False
    
    def _determine_yaml_file_path(self, key: str, locale_dir: str) -> str:
        """Determine which YAML file a translation key should be written to.
        
        Rails i18n organizes files by namespace:
        - "tasks.form.title" -> tasks/_form.yml or tasks/form.yml
        - "models.task.title" -> models/task.yml
        - "priorities.leisure" -> priorities.yml or en.yml (root level)
        
        Args:
            key: Translation key (e.g., "tasks.form.title")
            locale_dir: Base directory for locale files
            
        Returns:
            str: Full path to the YAML file
        """
        parts = key.split('.')
        
        # Simple heuristic: use first part as directory, rest as nested structure
        if len(parts) >= 2:
            # Check if first part is a known namespace (models, views, etc.)
            namespace = parts[0]
            if namespace in ['models', 'views', 'activerecord', 'activemodel']:
                # For models/task.yml or views/tasks/_form.yml
                if len(parts) >= 3:
                    # views.tasks.form -> views/tasks/_form.yml
                    subdir = parts[1]
                    filename = parts[2] if len(parts) == 3 else 'form'
                    return os.path.join(locale_dir, namespace, subdir, f"_{filename}.yml")
                else:
                    # models.task -> models/task.yml
                    filename = parts[1]
                    return os.path.join(locale_dir, namespace, f"{filename}.yml")
            else:
                # For other keys, put in a file named after the first part
                filename = f"{parts[0]}.yml"
                return os.path.join(locale_dir, filename)
        else:
            # Single-part key, put in application.yml or en.yml
            return os.path.join(locale_dir, "application.yml")
    
    def _add_to_nested_dict(self, data: dict, key: str, value: str):
        """Add a value to a nested dictionary using dot-notation key.
        
        Preserves existing nested structure - only updates the specific key,
        doesn't overwrite the entire nested dict.
        
        Args:
            data: Dictionary to add to
            key: Dot-notation key (e.g., "tasks.form.title")
            value: Value to set
        """
        parts = key.split('.')
        current = data
        
        # Navigate/create nested structure
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                # If the path exists but isn't a dict, convert it
                # This shouldn't happen in normal cases, but be safe
                current[part] = {}
            current = current[part]
        
        # Set the final value (this will update existing or create new)
        current[parts[-1]] = value
    
    def write_locale_po_file(self, locale):
        """Legacy method name - redirects to write_locale_yaml_files().
        
        Args:
            locale (str): The locale code
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.write_locale_yaml_files(locale)

    def generate_pot_file(self):
        """Generate base translation structure for Ruby/Rails projects.
        
        For Rails projects, this creates/updates the default locale YAML files
        based on existing translations. For full string extraction from Ruby/ERB files,
        consider using tools like `i18n-tasks`.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # For Ruby/Rails, "generating POT" means ensuring base locale structure exists
            default_locale = self.default_locale
            locale_dir = os.path.join(self._directory, self._locale_dir, default_locale)
            
            # If we have translations in memory, write them to the default locale
            if self.translations:
                logger.info(f"Writing base translation structure for locale {default_locale}")
                return self.write_locale_yaml_files(default_locale)
            else:
                # No translations in memory, create a basic structure
                os.makedirs(locale_dir, exist_ok=True)
                application_yml = os.path.join(locale_dir, "application.yml")
                
                if not os.path.exists(application_yml):
                    # Create a basic application.yml file
                    basic_data = {
                        default_locale: {
                            "application": {
                                "name": "Application Name"
                            }
                        }
                    }
                    with open(application_yml, 'w', encoding='utf-8') as f:
                        yaml.dump(basic_data, f, default_flow_style=False, allow_unicode=True)
                    logger.info(f"Created basic application.yml for locale {default_locale}")
                
                return True
                
        except Exception as e:
            logger.error(f"Error generating base translation structure: {e}", exc_info=True)
            return False

    def _get_project_root(self) -> str:
        """Get the project root directory (one level up from locale dir if needed)
        
        Returns:
            str: Project root directory path
        """
        project_dir = self._directory
        if project_dir.endswith(self._locale_dir):
            project_dir = os.path.dirname(project_dir)
        return project_dir

    def _get_babel_cfg_path(self) -> str:
        """Get the path to a valid babel.cfg file, or empty string if none found.
        
        Returns:
            str: Path to babel.cfg file or empty string if not found
        """
        project_dir = self._get_project_root()
        
        # Check for auto-detected babel.cfg in project root
        auto_detected_path = os.path.join(project_dir, "babel.cfg")
        if os.path.exists(auto_detected_path):
            logger.info(f"Found babel.cfg file: {auto_detected_path}")
            return auto_detected_path
            
        # Check for configured path in settings
        if self.settings_manager:
            configured_path = self.settings_manager.get_project_setting(
                self._directory, 'babel_cfg_path', ''
            )
            if configured_path and os.path.exists(configured_path):
                logger.info(f"Using configured babel.cfg file: {configured_path}")
                return configured_path
                
        return ""

    def _create_catalog(self):
        """Create a new Babel catalog with current project metadata.
        
        NOTE: This is a legacy method for POT file generation. Not used in YAML workflow.
        
        Returns:
            Babel Catalog: New Babel catalog instance
        """
        # Legacy method - not used for YAML-based Ruby projects
        from babel.messages.catalog import Catalog
        now = datetime.now()
        return Catalog(
            project=self.intro_details["application_name"],
            version=self.intro_details["version"],
            copyright_holder=self.intro_details["first_author"],
            msgid_bugs_address=self.intro_details["last_translator"],
            creation_date=now,
            revision_date=now
        )

    def _write_pot_file(self, catalog, method_name: str) -> bool:
        """Write a catalog to a POT file with post-processing.
        
        Args:
            catalog (Catalog): Babel catalog to write
            method_name (str): Name of the method for logging
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Write the catalog to a POT file
            from babel.messages.pofile import write_po
            pot_file = self.get_pot_file_path()
            with open(pot_file, 'wb') as f:
                write_po(f, catalog, width=120)
            
            # Post-process the file to remove format flag lines
            # TODO this is a hack to remove the format flag lines, it's not the right
            # long-term solution, but it's a quick fix.
            with open(pot_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Filter out lines that start with "#, " and write back to the file
            with open(pot_file, 'w', encoding='utf-8') as f:
                for line in lines:
                    if not line.startswith('#, '):
                        f.write(line)
            
            logger.info(f"Successfully generated base.pot file with {method_name}: {len(catalog)} entries")
            return True
            
        except Exception as e:
            logger.error(f"Error writing POT file: {e}")
            return False

    def _generate_pot_file_with_babel(self) -> bool:
        """Generate POT file using Babel configuration file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            import configparser
            
            babel_cfg_path = self._get_babel_cfg_path()
            if not babel_cfg_path:
                logger.error("No babel.cfg file found")
                return False
                
            project_dir = self._get_project_root()
            
            # Ensure locale directory exists
            locale_dir = os.path.join(project_dir, self._locale_dir)
            os.makedirs(locale_dir, exist_ok=True)
            
            logger.info(f"Generating POT file using Babel config: {babel_cfg_path}")
            
            # Parse babel.cfg file to get method_map
            config = configparser.ConfigParser()
            config.read(babel_cfg_path)
            
            # Build method_map from babel.cfg
            method_map = []
            
            # Check for [extractors] section (standard format)
            if 'extractors' in config:
                for pattern, extractor in config['extractors'].items():
                    method_map.append((pattern, extractor))
            
            # Check for [extractor: pattern] format (alternative format)
            for section_name in config.sections():
                if ':' in section_name:
                    # Format: [python: **.py] -> extractor=python, pattern=**.py
                    extractor, pattern = section_name.split(':', 1)
                    method_map.append((pattern.strip(), extractor.strip()))
            
            # If no extractors found, fall back to Python-only
            if not method_map:
                logger.warning("No extractors found in babel.cfg, falling back to Python-only")
                method_map = [('**.py', 'python')]
            
            # Create catalog and extract messages
            catalog = self._create_catalog()
            
            # Extract messages using Babel configuration
            from babel.messages.extract import extract_from_dir
            for filename, lineno, message, comments, context in extract_from_dir(
                project_dir,
                method_map=method_map,
                keywords={'_': None, 'gettext': None, 'ngettext': (1, 2)},
                comment_tags=('TRANSLATORS:',),
                strip_comment_tags=True
            ):
                catalog.add(message, None, [(filename, lineno)], auto_comments=comments, context=context)
            
            return self._write_pot_file(catalog, "Babel config")
            
        except Exception as e:
            logger.error(f"Error generating POT file with Babel: {e}")
            return False

    def _generate_pot_file_with_default(self) -> bool:
        """Generate POT file using the default method for Ruby projects.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            project_dir = self._get_project_root()
                
            # Ensure locale directory exists
            locale_dir = os.path.join(project_dir, self._locale_dir)
            os.makedirs(locale_dir, exist_ok=True)
            
            logger.info(f"Generating POT file in directory: {project_dir}")
            
            # Create catalog and extract messages
            catalog = self._create_catalog()
            
            # Extract messages from Ruby files
            from babel.messages.extract import extract_from_dir
            for filename, lineno, message, comments, context in extract_from_dir(
                project_dir,
                method_map=[('**.rb', 'ruby')],
                keywords={'_': None, 'gettext': None, 'ngettext': (1, 2)},
                comment_tags=('TRANSLATORS:',),
                strip_comment_tags=True,
                # NOTE the below doesn't actually work, it was an attempt to preserve the location
                # with line number and remove the format flags, but it doesn't work.
                # https://babel.pocoo.org/en/latest/messages.html is the relevant documentation,
                # from how they wrote it it's possible the options_map is purely for custom extractors.
                # options_map={
                #     '**.py': {
                #         'no_location': False,
                #         'include_lineno': True,
                #         'include_format_flags': False
                #     }
                # }
            ):
                catalog.add(message, None, [(filename, lineno)], auto_comments=comments, context=context)
            
            return self._write_pot_file(catalog, "default Ruby method")
                
        except Exception as e:
            logger.error(f"Error generating POT file: {e}")
            return False

    def set_babel_cfg_path(self, babel_cfg_path: str) -> bool:
        """Set the path to the babel.cfg file for this project.
        
        Args:
            babel_cfg_path (str): Path to the babel.cfg file
            
        Returns:
            bool: True if successful, False otherwise
        """
        if self.settings_manager:
            return self.settings_manager.save_project_setting(
                self._directory, 'babel_cfg_path', babel_cfg_path
            )
        return False

    def find_translatable_strings(self):
        """Find potential hardcoded strings in Ruby files that might need translation.
        
        This method scans Ruby files in the project directory for strings that:
        1. Are used in UI contexts (e.g., labels, buttons, titles)
        2. Are not already wrapped in translation calls
        3. Contain actual text (not just symbols or empty strings)
        
        Returns:
            dict: A dictionary mapping filenames to lists of potential translatable strings
        """
        # Get the project root directory
        project_dir = self._get_project_root()
            
        # Patterns that suggest UI text in Ruby
        ui_patterns = [
            r'label\(["\']([^"\']+)["\']\)',
            r'button\(["\']([^"\']+)["\']\)',
            r'title\(["\']([^"\']+)["\']\)',
            r'text\(["\']([^"\']+)["\']\)',
            r'placeholder\(["\']([^"\']+)["\']\)',
            r'flash\[["\']([^"\']+)["\']\]\s*=\s*["\']([^"\']+)["\']',
            r'flash\.(?:notice|alert|error)\s*=\s*["\']([^"\']+)["\']',
            r'content_tag\([^,]+,\s*["\']([^"\']+)["\']',
            r'link_to\s*["\']([^"\']+)["\']',
            r'options_for_select\([^,]*,\s*["\']([^"\']+)["\']'
        ]
        
        # Combine patterns
        combined_pattern = '|'.join(ui_patterns)
        
        # Store results
        results = {}
        
        # Walk through Ruby files
        for root, _, files in os.walk(project_dir):
            for file in files:
                if not file.endswith('.rb'):
                    continue
                    
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Find all potential UI strings
                    matches = re.finditer(combined_pattern, content)
                    strings = []
                    
                    for match in matches:
                        # Get all capturing groups from the match
                        groups = [g for g in match.groups() if g]
                        for string in groups:
                            # Skip if already wrapped in translation calls
                            if not re.search(r'_(?:\(["\']' + re.escape(string) + r'["\']\)|["\']' + re.escape(string) + r'["\'])', content):
                                # Skip if already wrapped in Rails i18n calls
                                if not re.search(r't\(["\']' + re.escape(string) + r'["\']\)', content):
                                    # Skip strings that are just whitespace, numbers, or symbols
                                    if string.strip() and not string.strip().isdigit():
                                        strings.append(string)
                    
                    if strings:
                        rel_path = os.path.relpath(file_path, project_dir)
                        results[rel_path] = strings
                        
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    
        return results

    def check_translations_changed(self, include_stale_translations: bool = False) -> bool:
        """Check if translations actually changed by comparing current state with a backup.
        
        This method creates a backup of the current POT file, generates a new one,
        and compares the translation content to determine if there are actual changes
        (ignoring timestamps and line number changes).
        
        Args:
            include_stale_translations (bool): If True, consider stale translations
                (translations that exist in current but not in new) as changes.
                If False (default), only consider new or modified translations as changes.
                
        Returns:
            bool: True if translations changed, False otherwise
        """
        try:
            # Get current POT file path
            pot_file_path = self.get_pot_file_path()
            
            # Check if POT file exists
            if not os.path.exists(pot_file_path):
                # No existing POT file, so any generation would be a change
                return True
                
            # Create backup of current POT file
            backup_pot_path = pot_file_path + ".backup"
            shutil.copy2(pot_file_path, backup_pot_path)
            
            # Store current translations for comparison
            current_translations = self.translations.copy()
            
            # Generate new POT file
            if not self.generate_pot_file():
                logger.error("Failed to generate POT file for comparison")
                return True
            
            # Parse the new POT file
            new_results = self.manage_translations()
            if not new_results.action_successful:
                logger.error(f"Failed to parse newly generated POT file: {new_results.error_message}")
                return True
            
            new_translations = self.translations
            
            # Compare the translation sets
            new_msgids = set(new_translations.keys())
            current_msgids = set(current_translations.keys())
            
            # Check for new translations (in new but not in current)
            new_translations_only = new_msgids - current_msgids
            if new_translations_only:
                logger.debug(f"Found {len(new_translations_only)} new translations")
                return True
            
            # Check for stale translations (in current but not in new) if requested
            if include_stale_translations:
                stale_translations = current_msgids - new_msgids
                if stale_translations:
                    logger.debug(f"Found {len(stale_translations)} stale translations")
                    return True
            
            # Check if any existing translations have changed their content
            for msgid in current_msgids:
                if msgid in new_msgids:
                    new_group = new_translations[msgid]
                    current_group = current_translations[msgid]
                    
                    # Compare actual translation values (not metadata)
                    if current_group.has_translation_changes(new_group):
                        logger.debug(f"Translation values changed for msgid '{msgid}'")
                        return True
            
            logger.debug("No actual translation content changes detected")
            return False
            
        except Exception as e:
            logger.error(f"Error checking translation changes: {e}")
            return True  # Assume changed if comparison fails
        finally:
            # Clean up backup file
            if 'backup_pot_path' in locals() and os.path.exists(backup_pot_path):
                try:
                    os.remove(backup_pot_path)
                except Exception as e:
                    logger.warning(f"Failed to clean up backup file {backup_pot_path}: {e}")

    def _find_python_i18n_tool(self, tool_name: str) -> str:
        """Find a valid Python i18n tool script.
        
        Args:
            tool_name (str): Name of the tool to find (e.g., 'pygettext.py' or 'msgfmt.py')
            
        Returns:
            str: Path to the tool if found, empty string if not found
        """
        python_version = f"Python{sys.version_info.major}{sys.version_info.minor}"
        possible_paths = [
            os.path.join(sys.prefix, "Tools", "i18n", tool_name),  # Current Python installation
            rf"C:\{python_version}\Tools\i18n\{tool_name}",        # Windows specific Python version
            rf"C:\Python310\Tools\i18n\{tool_name}",               # Hardcoded fallback
            tool_name                                              # Assume it's in PATH
        ]
        
        for tool_path in possible_paths:
            try:
                if os.path.exists(tool_path) or tool_path == tool_name:
                    logger.debug(f"Found {tool_name} at {tool_path}")
                    return tool_path
            except Exception as e:
                logger.debug(f"Failed to access {tool_name} at {tool_path}: {e}")
                continue
                
        logger.error(f"Could not find {tool_name} installation")
        return ""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise Exception("No input file specified")
    create_new_po_files = False
    create_mo_files = False
    if len(sys.argv) > 2:
        try: 
            arg = int(sys.argv[2])
        except ValueError as e:
            raise Exception("Invalid argument, must be an integer: " + str(e))
        if arg > 1 or arg < 0:
            raise Exception("Invalid argument, must be either 0 (for new PO files) or 1 (for creation of MO files)")
        if arg == 0:
            create_new_po_files = True
        if arg == 1:
            create_mo_files = True
    sys.exit(RubyI18NManager(sys.argv[1]).manage_translations(create_new_po_files=create_new_po_files, create_mo_files=create_mo_files))


