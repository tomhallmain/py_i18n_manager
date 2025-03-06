import glob
import os
import subprocess
import sys
import time
import logging

from i18n.translation_group import TranslationGroup

logger = logging.getLogger(__name__)

class I18NManager():
    MSGID = "msgid"
    MSGSTR = "msgstr"

    def __init__(self, directory, locales=[], intro_details=None):
        logger.debug(f"Initializing I18NManager with directory: {directory}, locales: {locales}")
        self._directory = directory
        self.locales = locales[:]
        self.translations = {}
        # Store intro details if provided, otherwise use defaults
        self.intro_details = intro_details or {
            "first_author": "THOMAS HALL <tomhall.main@gmail.com>",
            "last_translator": "Thomas Hall <tomhall.main@gmail.com>",
            "application_name": "APPLICATION",
            "version": "1.0"
        }

    def create_mo_files(self):
        for locale in self.locales:
            self._create_mo_file(locale)

    def _create_mo_file(self, locale):
        po_directory = os.path.join(self._directory, locale, "LC_MESSAGES")
        os.chdir(po_directory)
        retval = subprocess.call(args=["python", r"C:\Python310\Tools\i18n\msgfmt.py", "-o", "base.mo", "base"], shell=True)
        if retval != 0:
            print("Error while creating mo file for locale " + locale)
            sys.exit(1)
        else:
            print("Created mo for locale " + locale)

    def manage_translations(self, create_new_po_files=False, create_mo_files=False):
        try:
            POT_file, PO_files = self.gather_files()
            print("POT file found: " + POT_file)
            print("PO files found: " + str(len(PO_files)))
            self._parse_pot(POT_file)
        except Exception as e:
            logger.error(f"Error gathering files: {e}")
            return 2

        self._fill_translations(PO_files)

        if create_mo_files:
            self.create_mo_files()
            return 0

        self.print_translations()

        if self.print_invalid_translations():
           return 1

        if create_new_po_files:
            self.write_new_files(PO_files)

        return 0

    def get_po_file_path(self, locale):
        return os.path.join(self._directory, locale, "LC_MESSAGES", "base.po")

    def gather_files(self):
        POT_files = glob.glob(os.path.join(self._directory, "*.pot"))
        if len(POT_files) != 1:
            self._directory = os.path.join(self._directory, "locale")
            if os.path.exists(self._directory):
                POT_files = glob.glob(os.path.join(self._directory, "*.pot"))
            if len(POT_files) != 1:
                raise Exception("Invalid number of POT files found: " + str(len(POT_files)))
        base_name = os.path.splitext(os.path.basename(POT_files[0]))[0]
        PO_files = glob.glob(os.path.join(self._directory, "**/*.po"), recursive=True)
        i = 0
        while i < len(PO_files):
            if os.path.splitext(os.path.basename(PO_files[i]))[0] != base_name:
                print("Invalid PO file found in directory: " + os.path.basename(PO_files[i]))
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

    def _escape_string(self, s):
        """Convert a string to ASCII-encoded Unicode format for PO files.
        
        Args:
            s (str): The string to convert
            
        Returns:
            str: The string in ASCII-encoded Unicode format
        """
        if not isinstance(s, str):
            return str(s)
            
        result = []
        for c in s:
            if ord(c) <= 0x7F:  # ASCII character
                result.append(c)
            else:
                # Get Python's escaped version
                escaped = c.encode('ascii', 'backslashreplace').decode()
                # Convert \x to \u00 for short sequences, \u for long ones
                if len(escaped) < 6:  # e.g., \xE9
                    escaped = escaped.replace('\\x', '\\u00')
                else:  # e.g., \U0001F600
                    escaped = escaped.replace('\\U', '\\u')
                result.append(escaped)
                
        return ''.join(result)
        
    def _unescape_string(self, s):
        """Convert an ASCII-encoded Unicode string back to regular Unicode.
        
        Args:
            s (str): The ASCII-encoded Unicode string to convert
            
        Returns:
            str: The string in regular Unicode format
        """
        if not isinstance(s, str):
            return str(s)
            
        # Replace \u00 with \x for short sequences
        s = s.replace('\\u00', '\\x')
        # Replace \u with \U for long sequences
        s = s.replace('\\u', '\\U')
        
        try:
            # Decode the escaped string back to Unicode
            return s.encode('ascii').decode('unicode_escape')
        except Exception as e:
            logger.warning(f"Error unescaping string: {e}")
            return s

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
                f.write(f'msgid "{self._escape_string(msgid)}"\n')
                
                # Write msgstr
                translation = group.get_translation(locale)
                if translation:
                    if "\n" in translation:
                        f.write(f"{I18NManager.MSGSTR} \"\"\n")
                        for line in translation.split("\n"):
                            if line != "":
                                f.write(f"\"{self._escape_string(line)}\"\n")
                    else:
                        f.write(f"{I18NManager.MSGSTR} \"{self._escape_string(translation)}\"\n")
                else:
                    f.write('msgstr ""\n')
                    
                f.write('\n')
                translation_count += 1
                
            logger.debug(f"Wrote {translation_count} translations to PO file")

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
            # Construct the PO file path
            po_file = os.path.join(self._directory, locale, "LC_MESSAGES", "base.po")
            if not os.path.exists(po_file):
                logger.warning(f"PO file not found for locale {locale}: {po_file}")
                return False
                
            logger.debug(f"Writing PO file for locale {locale}: {po_file}")
            self.write_po_file(po_file, locale)
            return True
        except Exception as e:
            logger.error(f"Error writing PO file for locale {locale}: {e}")
            return False

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


