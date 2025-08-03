from datetime import datetime
import glob
import os
import shutil
import sys
import time
import re
import polib
from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.pofile import write_po

from i18n.translation_group import TranslationGroup
from .translation_manager_results import TranslationManagerResults, TranslationAction, LocaleStatus
from .invalid_translation_groups import InvalidTranslationGroups

from utils.logging_setup import get_logger

logger = get_logger("i18n_manager")

class I18NManager():
    """Manages the Python internationalization (i18n) workflow for translation files.
    
    TODO: Add support for additional file formats:
    - Java properties files (.properties)
    - JavaScript common i18n formats:
      * JSON format (e.g., react-i18next)
      * YAML format
      * ICU MessageFormat
      * Angular i18n XLIFF format
    
    The workflow for managing Python translations consists of several steps:
    
    1. POT File Generation:
       - Using pygettext.py, scan Python source files for translatable strings
       - Generate base.pot file containing all extracted strings
       - Each string becomes a msgid in the POT file
    
    2. Base Translation Set:
       - Parse the POT file to establish the base set of translations
       - Each msgid from POT becomes a TranslationGroup marked as 'in_base'
       - This represents the current, valid set of strings needing translation
    
    3. Locale Translations:
       - Parse existing PO files for each locale (e.g., fr/LC_MESSAGES/base.po)
       - Each PO file may contain:
         * Translations for current base strings
         * Missing translations (empty msgstr)
         * Stale translations (msgid not in current base)
         * Invalid translations (Unicode/format string issues)
    
    4. Translation Management:
       - Track missing translations for each locale
       - Identify invalid Unicode sequences
       - Identify invalid format string indices
       - Allow user to fix/add translations via UI
    
    5. PO File Updates:
       - Write updated PO files for each locale
       - Include only translations for current base strings
       - Exclude stale translations not in current base
       - Maintain proper headers and metadata
    
    The class provides methods to handle each step of this workflow and maintains
    the state of translations in memory between file operations.
    """
    
    MSGID = "msgid"
    MSGSTR = "msgstr"

    def __init__(self, directory, locales=[], intro_details=None, settings_manager=None):
        logger.debug(f"Initializing I18NManager with directory: {directory}, locales: {locales}")
        self._directory = directory
        self.locales = locales[:]
        self.translations: dict[str, TranslationGroup] = {}
        self.written_locales = set()  # Track which locales have been written to
        # Store intro details if provided, otherwise use defaults
        self.intro_details = intro_details or {
            "first_author": "AUTHOR NAME <author@example.com>",
            "last_translator": "Translator Name <translator@example.com>",
            "application_name": "APPLICATION",
            "version": "1.0"
        }
        # Store settings manager for project-specific settings
        self.settings_manager = settings_manager
        # Detect which directory structure is being used
        self._locale_dir = self._detect_locale_directory()
        
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
        """Detect which directory structure is being used (locale or locales).
        
        Returns:
            str: The name of the locale directory being used ('locale' or 'locales')
        """
        locale_dir = os.path.join(self._directory, "locale")
        locales_dir = os.path.join(self._directory, "locales")
        
        # Check if both directories exist
        if os.path.exists(locale_dir) and os.path.exists(locales_dir):
            logger.warning("Both 'locale' and 'locales' directories exist. Using 'locale' by default.")
            return "locale"
        
        # Check if locale directory exists
        if os.path.exists(locale_dir):
            logger.info("Using 'locale' directory structure")
            return "locale"
        
        # Check if locales directory exists
        if os.path.exists(locales_dir):
            logger.info("Using 'locales' directory structure")
            return "locales"
        
        # If neither exists, default to 'locale'
        logger.info("No locale directory found. Defaulting to 'locale' directory structure")
        return "locale"

    def set_directory(self, directory):
        """Set a new project directory and reset translation state.
        
        Args:
            directory (str): The new project directory path
        """
        logger.debug(f"Setting new project directory: {directory}")
        self._directory = directory
        # Reset translation state
        self.translations: dict[str, TranslationGroup] = {}
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

    def create_mo_files(self, results: TranslationManagerResults):
        for locale in results.locale_statuses:
            if results.locale_statuses[locale].has_po_file:
                if not self._create_mo_file(locale):
                    results.failed_locales.append(locale)
            else:
                results.failed_locales.append(locale)
        if results.failed_locales:
            results.extend_error_message(f"Failed to create MO files for locales: {results.failed_locales}")

    def _create_mo_file(self, locale: str):
        """Create a MO file from a PO file using polib.
        
        Args:
            locale (str): Locale code
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            po_directory = os.path.join(self._directory, self._locale_dir, locale, "LC_MESSAGES")
            po_file = os.path.join(po_directory, "base.po")
            mo_file = os.path.join(po_directory, "base.mo")
            
            # Load PO file and save as MO
            po = polib.pofile(po_file, encoding='utf-8')
            po.save_as_mofile(mo_file)
            
            print("Created mo for locale " + locale)
            return True
            
        except Exception as e:
            print("Error while creating mo file for locale " + locale + ": " + str(e))
            return False

    def manage_translations(self, action: TranslationAction = TranslationAction.CHECK_STATUS, modified_locales: set[str] = None):
        """Manage translations based on the specified action.
        
        Args:
            action (TranslationAction): The action to perform. Defaults to CHECK_STATUS.
            modified_locales (set, optional): Set of locales that have been modified and need updating.
            
        Returns:
            TranslationManagerResults: Results of the translation management operation.
        """
        results = TranslationManagerResults.create(self._directory, action)
        results.default_locale = self.default_locale
        results.failed_locales = []
        results.action_successful = True
        
        try:
            # Get POT and PO files
            pot_file, po_files = self.gather_files()
            logger.debug(f"Found POT file: {pot_file}")
            logger.debug(f"Found PO files: {len(po_files)}")
            
            # TODO: Investigate false positives in status check after PO updates
            # Possible causes to check:
            # 1. Translation state not being properly reset between write and check
            # 2. Cache/memory state of translations persisting after file updates
            # 3. File system delays in updating PO files before status check
            # 4. Stale translations not being properly purged after writes
            # 5. Locale status tracking getting out of sync with file state
            
            # Only parse files and fill translations during CHECK_STATUS
            if action == TranslationAction.CHECK_STATUS:
                # Parse POT file if it exists
                if results.has_pot_file:
                    self._parse_pot(pot_file)
                
                # Parse existing PO files
                if results.has_locale_dir:
                    self._fill_translations(po_files)
            
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
                self.create_mo_files(results)
            elif action == TranslationAction.GENERATE_POT:
                if not self.generate_pot_file():
                    results.action_successful = False
                    results.extend_error_message("Failed to generate POT file")
            
            results.determine_action_successful()
            return results
        
        except Exception as e:
            results.action_successful = False
            results.error_message = str(e)
            return results

    def get_po_file_path(self, locale):
        return os.path.join(self._directory, self._locale_dir, locale, "LC_MESSAGES", "base.po")
    
    def get_pot_file_path(self):
        """Get the path to the POT file for this project.
        
        Returns:
            str: Path to the POT file
        """
        return os.path.join(self._directory, self._locale_dir, "base.pot")

    def gather_files(self):
        POT_files = glob.glob(os.path.join(self._directory, "*.pot"))
        if len(POT_files) != 1:
            locale_dir = os.path.join(self._directory, self._locale_dir)
            if os.path.exists(locale_dir):
                POT_files = glob.glob(os.path.join(locale_dir, "*.pot"))
            if len(POT_files) != 1:
                raise Exception("Invalid number of POT files found: " + str(len(POT_files)))
        base_name = os.path.splitext(os.path.basename(POT_files[0]))[0]
        search_dir = os.path.dirname(POT_files[0])  # Use the directory where POT was found
        PO_files = glob.glob(os.path.join(search_dir, "**/*.po"), recursive=True)
        i = 0
        while i < len(PO_files):
            if os.path.splitext(os.path.basename(PO_files[i]))[0] != base_name:
                logger.warning(f"Invalid PO file found in directory: {os.path.basename(PO_files[i])}")
                PO_files.remove(PO_files[i])
            else:
                i += 1
        return POT_files[0], PO_files

    def _parse_pot(self, POT):
        """Parse a POT file using polib.
        
        Args:
            POT (str): Path to the POT file
        """
        logger.debug(f"Parsing POT file: {POT}")
        # Use include_obsolete=True and include_previous=True to ensure comments are parsed
        po = polib.pofile(POT, encoding='utf-8', include_obsolete=True, include_previous=True)
        logger.debug(f"Found {len(po)} entries in POT file")
        
        for entry in po:
            if entry.msgid and entry.msgid.strip():
                group = TranslationGroup.from_polib_entry(entry, is_in_base=True)
                self.translations[entry.msgid] = group

    def get_msgid(self, line):
        msgid = line[7:-2]
        return msgid

    def _get_po_locale(self, PO):
        _dirname1 = os.path.dirname(PO)
        _dirname2 = os.path.dirname(_dirname1)
        return os.path.basename(_dirname2)

    def _parse_po(self, PO, locale):
        """Parse a PO file using polib.
        
        Args:
            PO (str): Path to the PO file
            locale (str): Locale code
        """
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
                
                if entry.msgid in self.translations:
                    self.translations[entry.msgid].add_translation(locale, entry.msgstr)
                else:
                    group = TranslationGroup.from_polib_entry(entry, is_in_base=False)
                    group.add_translation(locale, entry.msgstr)
                    self.translations[entry.msgid] = group
        
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

    def fix_invalid_translations(self):
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
        for msgid, group in self.translations.items():
            print(msgid)
            for locale, msgstr in group.values.items():
                print(f"\t{locale}: {msgstr}")
            print()

    def write_new_files(self, PO_files):
        for PO in PO_files:
            locale = self._get_po_locale(PO)
            print(f"Writing new file {locale} to {PO}")
            self.write_po_file(PO, locale)

    def write_po_files(self, modified_locales: set[str], results: TranslationManagerResults):
        """Write PO files for modified locales.
        
        Args:
            modified_locales (set[str]): Set of locales to update. If None, updates all locales.
            results (TranslationManagerResults): Results object to track failures
        """
        locales_to_update = modified_locales or results.locale_statuses.keys()
        successful_updates = []
        
        for locale in locales_to_update:
            if locale in results.locale_statuses:
                if self.write_locale_po_file(locale):
                    successful_updates.append(locale)
                else:
                    results.failed_locales.append(locale)
                    
        if results.failed_locales:
            results.extend_error_message(f"Failed to write PO files for locales: {results.failed_locales}")
            
        # Set flag if any PO files were successfully updated
        if successful_updates:
            results.po_files_updated = True
            results.updated_locales = successful_updates

    def write_po_file(self, po_file, locale):
        """Write translations to a PO file for a specific locale using polib.
        
        Args:
            po_file (str): Path to the PO file
            locale (str): Locale code
        """
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
            for msgid, group in self.translations.items():
                if not group.is_in_base:
                    continue
                    
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
        stale_msgids = [msgid for msgid, group in self.translations.items() if not group.is_in_base]
        for msgid in stale_msgids:
            del self.translations[msgid]
        if stale_msgids:
            logger.debug(f"Purged {len(stale_msgids)} stale translations")

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

    def write_locale_po_file(self, locale):
        """Write the PO file for a specific locale.
        
        Args:
            locale (str): The locale code to write the PO file for
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            po_file = self.get_po_file_path(locale)
            if not os.path.exists(po_file):
                logger.warning(f"PO file not found for locale {locale}: {po_file}")
                return False
                
            self.write_po_file(po_file, locale)
            return True
        except Exception as e:
            logger.error(f"Error writing PO file for locale {locale}: {e}")
            return False

    def generate_pot_file(self):
        """Generate the base.pot file using Babel.
        TODO double check that polib doesn't actually support this out of the box
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if we should use Babel configuration
            if self._get_babel_cfg_path() != "":
                return self._generate_pot_file_with_babel()
            else:
                return self._generate_pot_file_with_default()
        except Exception as e:
            logger.error(f"Error generating POT file: {e}")
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

    def _create_catalog(self) -> Catalog:
        """Create a new Babel catalog with current project metadata.
        
        Returns:
            Catalog: New Babel catalog instance
        """
        now = datetime.now()
        return Catalog(
            project=self.intro_details["application_name"],
            version=self.intro_details["version"],
            copyright_holder=self.intro_details["first_author"],
            msgid_bugs_address=self.intro_details["last_translator"],
            creation_date=now,
            revision_date=now
        )

    def _write_pot_file(self, catalog: Catalog, method_name: str) -> bool:
        """Write a catalog to a POT file with post-processing.
        
        Args:
            catalog (Catalog): Babel catalog to write
            method_name (str): Name of the method for logging
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Write the catalog to a POT file
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
        """Generate POT file using the default method (current implementation).
        
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
            
            # Extract messages from Python files
            for filename, lineno, message, comments, context in extract_from_dir(
                project_dir,
                method_map=[('**.py', 'python')],
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
            
            return self._write_pot_file(catalog, "default method")
                
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
        """Find potential hardcoded strings in Python files that might need translation.
        
        This method scans Python files in the project directory for strings that:
        1. Are used in UI contexts (e.g., QLabel, QPushButton, setWindowTitle)
        2. Are not already wrapped in _() translation calls
        3. Contain actual text (not just symbols or empty strings)
        
        Returns:
            dict: A dictionary mapping filenames to lists of potential translatable strings
        """
        # Get the project root directory
        project_dir = self._get_project_root()
            
        # Patterns that suggest UI text
        ui_patterns = [
            r'QLabel\(["\']([^"\']+)["\']\)',
            r'QPushButton\(["\']([^"\']+)["\']\)',
            r'setWindowTitle\(["\']([^"\']+)["\']\)',
            r'setText\(["\']([^"\']+)["\']\)',
            r'setTitle\(["\']([^"\']+)["\']\)',
            r'setPlaceholderText\(["\']([^"\']+)["\']\)',
            r'QMessageBox\.(?:information|warning|critical|question)\([^,]+,["\']([^"\']+)["\'],["\']([^"\']+)["\']\)',
            r'addTab\([^,]+,["\']([^"\']+)["\']\)'
        ]
        
        # Combine patterns
        combined_pattern = '|'.join(ui_patterns)
        
        # Store results
        results = {}
        
        # Walk through Python files
        for root, _, files in os.walk(project_dir):
            for file in files:
                if not file.endswith('.py'):
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
                            # Skip if already wrapped in _()
                            if not re.search(r'_\(["\']' + re.escape(string) + r'["\']\)', content):
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
    sys.exit(I18NManager(sys.argv[1]).manage_translations(create_new_po_files=create_new_po_files, create_mo_files=create_mo_files))


