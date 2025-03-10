import glob
import os
import subprocess
import sys
import time
import logging
import re

from i18n.translation_group import TranslationGroup
from .translation_manager_results import TranslationManagerResults, TranslationAction, LocaleStatus

logger = logging.getLogger(__name__)

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

    def __init__(self, directory, locales=[], intro_details=None):
        logger.debug(f"Initializing I18NManager with directory: {directory}, locales: {locales}")
        self._directory = directory
        self.locales = locales[:]
        self.translations = {}
        self.written_locales = set()  # Track which locales have been written to
        # Store intro details if provided, otherwise use defaults
        self.intro_details = intro_details or {
            "first_author": "AUTHOR NAME <author@example.com>",
            "last_translator": "Translator Name <translator@example.com>",
            "application_name": "APPLICATION",
            "version": "1.0"
        }

    def set_directory(self, directory):
        """Set a new project directory and reset translation state.
        
        Args:
            directory (str): The new project directory path
        """
        logger.debug(f"Setting new project directory: {directory}")
        self._directory = directory
        # Reset translation state
        self.translations = {}
        self.written_locales = set()
        self.locales = []
        self.intro_details = {
            "first_author": "AUTHOR NAME <author@example.com>",
            "last_translator": "Translator Name <translator@example.com>",
            "application_name": "APPLICATION",
            "version": "1.0"
        }

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
        try:
            po_directory = os.path.join(self._directory, "locale", locale, "LC_MESSAGES")
            os.chdir(po_directory)
            
            # Find msgfmt.py
            msgfmt_path = self._find_python_i18n_tool("msgfmt.py")
            if not msgfmt_path:
                return False
                
            retval = subprocess.call(args=["python", msgfmt_path, "-o", "base.mo", "base"], shell=True)
            if retval != 0:
                print("Error while creating mo file for locale " + locale)
                return False
            else:
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
        results.default_locale = self.intro_details.get('translation.default_locale', 'en')
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
                not_in_base, missing_locale_groups, invalid_unicode_groups, invalid_index_groups = self.get_invalid_translations()
                results.stale_translations = len(not_in_base)
                results.missing_translations = len(missing_locale_groups)
                results.invalid_unicode = len(invalid_unicode_groups)
                results.invalid_indices = len(invalid_index_groups)
            
            # Perform requested action
            if action == TranslationAction.WRITE_PO_FILES:
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
        return os.path.join(self._directory, "locale", locale, "LC_MESSAGES", "base.po")

    def gather_files(self):
        POT_files = glob.glob(os.path.join(self._directory, "*.pot"))
        if len(POT_files) != 1:
            locale_dir = os.path.join(self._directory, "locale")
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
        with open(POT, "r", encoding="utf8") as f:
            usage_comment = ""
            in_usage_comment = False
            for line in f:
                if line.startswith(I18NManager.MSGID):
                    msgid = self.get_msgid(line)
                    # Skip empty or whitespace-only msgids (including the header entry with empty msgid)
                    if msgid and msgid.strip():
                        group = TranslationGroup(msgid, is_in_base=True, usage_comment=usage_comment)
                        self.translations[msgid] = group
                    usage_comment = ""
                    in_usage_comment = False
                elif line.startswith("#") or in_usage_comment:
                    in_usage_comment = True
                    usage_comment += line

    def get_msgid(self, line):
        msgid = line[7:-2]
        return msgid

    def _get_po_locale(self, PO):
        _dirname1 = os.path.dirname(PO)
        _dirname2 = os.path.dirname(_dirname1)
        return os.path.basename(_dirname2)

    def _parse_po(self, PO, locale):
        with open(PO, "r", encoding="utf8") as f:
            msgid = None
            usage_comment = ""
            msgstr = ""
            is_in_msgstr = False
            for line in f:
                if line.startswith("#"):
                    usage_comment = line
                    msgstr = ""
                elif line.startswith(I18NManager.MSGID):
                    msgid = self.get_msgid(line)
                    msgstr = ""
                    is_in_msgstr = True
                elif line.startswith(I18NManager.MSGSTR):
                    if not is_in_msgstr or msgid is None:
                        print("Invalid PO file found in directory: " + PO)
                        print("Line: " + line)
                    msgstr += line[8:-2]
                elif line.strip() == "" and msgstr != "":
                    if msgid and msgid.strip():
                        if msgid in self.translations:
                            self.translations[msgid].add_translation(locale, msgstr)
                        else:
                            group = TranslationGroup(msgid, is_in_base=False, usage_comment=usage_comment)
                            group.add_translation(locale, msgstr)
                            self.translations[msgid] = group
                    is_in_msgstr = False
                    msgstr = ""
                    usage_comment = ""
                elif is_in_msgstr: # NOTE multi-line translation value
                    msgstr += "\n" + line[1:-2]

    def _fill_translations(self, PO_files):
        for PO in PO_files:
            locale = self._get_po_locale(PO)
            if not locale in self.locales:
                self.locales.append(locale)
            self._parse_po(PO, locale)

    def get_invalid_translations(self):
        """Calculate invalid translations and return them in a structured format.
        
        Returns:
            tuple: (not_in_base, missing_locale_groups, invalid_unicode_locale_groups, invalid_index_locale_groups)
        """
        not_in_base = []
        missing_locale_groups = []
        invalid_unicode_locale_groups = []
        invalid_index_locale_groups = []
        
        for msgid, group in self.translations.items():
            if not group.is_in_base:
                # Only report not_in_base if we haven't written to all locales yet
                if not self.written_locales.issuperset(self.locales):
                    not_in_base.append(msgid)
            else:
                missing_locales = group.get_missing_locales(self.locales)
                if len(missing_locales) > 0:
                    missing_locale_groups.append((msgid, missing_locales))
                    
                invalid_unicode_locales = group.get_invalid_unicode_locales()
                if len(invalid_unicode_locales) > 0:
                    invalid_unicode_locale_groups.append((msgid, invalid_unicode_locales))
                    
                invalid_index_locales = group.get_invalid_index_locales()
                if len(invalid_index_locales) > 0:
                    invalid_index_locale_groups.append((msgid, invalid_index_locales))
                    
        return not_in_base, missing_locale_groups, invalid_unicode_locale_groups, invalid_index_locale_groups

    def print_invalid_translations(self):
        """Print invalid translations to the console."""
        not_in_base, missing_locale_groups, invalid_unicode_locale_groups, invalid_index_locale_groups = self.get_invalid_translations()
        
        one_invalid_translation_found = False
        
        for msgid in not_in_base:
            print(f"Not in base: \"{msgid}\"")
            one_invalid_translation_found = True

        for msgid, missing_locales in missing_locale_groups:
            print(f"Missing translations: \"{msgid}\"")
            found_locales = list(set(self.locales) - set(missing_locales))
            if len(found_locales) > 0:
                print(f"Missing in locales: {missing_locales} - Found in locales: {found_locales}")
            else:
                print("Missing in ALL locales.")
            one_invalid_translation_found = True

        for msgid, invalid_locales in invalid_unicode_locale_groups:
            print(f"Invalid unicode: \"{msgid}\" in locales: {invalid_locales}")
            self.translations[msgid].fix_encoded_unicode_escape_strings(invalid_locales)
            one_invalid_translation_found = True

        for msgid, invalid_locales in invalid_index_locale_groups:
            print(f"Invalid indices: \"{msgid}\" in locales: {invalid_locales}")
            one_invalid_translation_found = True

        if not one_invalid_translation_found:
            print("No invalid translations found.")
            return False

        return False  # not a problem if there are invalid translations, we will overwrite them in the new POs

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
        """Write translations to a PO file for a specific locale.
        
        Args:
            po_file (str): Path to the PO file
            locale (str): Locale code
        """
        logger.debug(f"Writing PO file for locale {locale}: {po_file}")
        # Get intro details with current locale
        intro_details = self.get_POT_intro_details(
            locale=locale,
            first_author=self.intro_details["first_author"],
            last_translator=self.intro_details["last_translator"],
            application_name=self.intro_details["application_name"],
            version=self.intro_details["version"]
        )
        
        with open(po_file, 'w', encoding='utf-8') as f:
            # Write header
            f.write(intro_details)
            
            # Write translations
            translation_count = 0
            for msgid, group in self.translations.items():
                if not group.is_in_base:
                    continue
                    
                # Write usage comment if present
                if group.usage_comment:
                    f.write(group.usage_comment)
                    
                # Write msgid
                f.write(f'msgid "{msgid}"\n')
                
                # Write msgstr
                translation = group.get_translation_escaped(locale)
                if translation:
                    if "\n" in translation:
                        f.write(f"{I18NManager.MSGSTR} \"\"\n")
                        for line in translation.split("\n"):
                            if line != "":
                                f.write(f"\"{line}\"\n")
                    else:
                        f.write(f"{I18NManager.MSGSTR} \"{translation}\"\n")
                else:
                    f.write('msgstr ""\n')
                    
                f.write('\n')
                translation_count += 1
                
            logger.debug(f"Wrote {translation_count} translations to PO file")
            # Mark this locale as having been written to
            self.written_locales.add(locale)
            
            # If all locales have been written to at least once, purge stale translations
            if self.written_locales.issuperset(self.locales):
                self._purge_stale_translations()
                
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
"Content-Type: text/plain; charset=cp1252\\n"
"Content-Transfer-Encoding: 8bit\\n"


'''

    def update_po_files(self, modified_locales=None):
        """Update PO files for modified locales.
        
        Args:
            modified_locales (set, optional): Set of locale codes to update. If None, updates all locales.
        """
        try:
            if modified_locales is None:
                modified_locales = set(self.locales)
            else:
                # Create a copy to avoid modification during iteration
                modified_locales = set(modified_locales)
                
            logger.debug(f"Starting PO file update for locales: {modified_locales}")
            
            for locale in modified_locales:
                if locale not in self.locales:
                    logger.warning(f"Locale {locale} not found in project")
                    continue
                    
                po_file = self.get_po_file_path(locale)
                if not po_file:
                    logger.warning(f"Could not determine PO file path for locale {locale}")
                    continue
                    
                logger.debug(f"Writing updated translations to PO file: {po_file}")
                if self.write_po_file(po_file, locale):
                    logger.info(f"Successfully updated PO file for locale {locale}")
                else:
                    logger.error(f"Failed to update PO file for locale {locale}")
                    
            return True
            
        except Exception as e:
            logger.error(f"Error updating PO files: {e}")
            logger.exception("Full traceback:")
            return False

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
        """Generate the base.pot file using pygettext.py.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get the project root directory (one level up from locale dir if needed)
            project_dir = self._directory
            if project_dir.endswith('locale'):
                project_dir = os.path.dirname(project_dir)
                
            # Ensure locale directory exists
            locale_dir = os.path.join(project_dir, 'locale')
            os.makedirs(locale_dir, exist_ok=True)
            
            logger.info(f"Generating POT file in directory: {project_dir}")
            
            # Find pygettext.py
            pygettext_path = self._find_python_i18n_tool("pygettext.py")
            if not pygettext_path:
                return False
                
            result = subprocess.run(
                ["python", pygettext_path, "-d", "base", "-o", "locale\\base.pot", "."],
                cwd=project_dir,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                logger.info(f"Successfully generated base.pot file using {pygettext_path}")
                return True
                
            return False
                
        except Exception as e:
            logger.error(f"Error generating POT file: {e}")
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
        project_dir = self._directory
        if project_dir.endswith('locale'):
            project_dir = os.path.dirname(project_dir)
            
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


