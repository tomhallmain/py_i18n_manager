import glob
import os
import subprocess
import sys
import time


from i18n.translation_group import TranslationGroup


class I18NManager():
    MSGID = "msgid"
    MSGSTR = "msgstr"

    def __init__(self, directory, locales=[]):
        self._directory = directory
        self.locales = locales[:]
        self.translations = {}
        self.POT_Intro_Details = self.get_POT_intro_details()

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
        POT_file, PO_files = self.gather_files()
        print("POT file found: " + POT_file)
        print("PO files found: " + str(len(PO_files)))
        self._parse_pot(POT_file)
        self._fill_translations(PO_files)

        if create_mo_files:
            self.create_mo_files()
            return

        self.print_translations()

        if self.print_invalid_translations():
           return 1

        if create_new_po_files:
            self.write_new_files(PO_files)

        return 0

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

    def print_invalid_translations(self):
        one_invalid_translation_found = False
        not_in_base = []
        missing_locale_groups = []
        invalid_unicode_locale_groups = []
        invalid_index_locale_groups = []
        for msgid, group in self.translations.items():
            if not group.is_in_base:
                not_in_base.append(msgid)
                one_invalid_translation_found = True
            else:
                missing_locales = group.get_missing_locales(self.locales)
                if len(missing_locales) > 0:
                    missing_locale_groups.append((msgid, missing_locales))
#                    one_invalid_translation_found = True # NOTE these should be written as empty in self.write_new_files()
                invalid_unicode_locales = group.get_invalid_unicode_locales()
                if len(invalid_unicode_locales) > 0:
                    invalid_unicode_locale_groups.append((msgid, invalid_unicode_locales))
                    one_invalid_translation_found = True
                invalid_index_locales = group.get_invalid_index_locales()
                if len(invalid_index_locales) > 0:
                    invalid_index_locale_groups.append((msgid, invalid_index_locales))
                    one_invalid_translation_found = True

        for msgid in not_in_base:
            print(f"Not in base: \"{msgid}\"")
            print("Found in locales: " + str(list(group.values.keys())))

        for msgid, missing_locales in missing_locale_groups:
            print(f"Missing translations: \"{msgid}\"")
            found_locales = list(set(group.values.keys()) - set(missing_locales))
            if len(found_locales) > 0:
                print(f"Missing in locales: {missing_locales}")
                print(f"Found in locales: {found_locales}")
            else:
                print("Missing in ALL locales.")

        for msgid, invalid_locales in invalid_unicode_locale_groups:
            print(f"Invalid unicode: \"{msgid}\"")
            print(f"Invalid in locales: {invalid_locales}")
            self.translations[msgid].fix_encoded_unicode_escape_strings(invalid_locales)

        for msgid, invalid_locales in invalid_index_locale_groups:
            print(f"Invalid indices: \"{msgid}\"")
            print(f"Invalid in locales: {invalid_locales}")

        if not one_invalid_translation_found:
            print("No invalid translations found.")
            return False

        return False # not a problem if there are invalid translations, we will overwrite them in the new POs

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
            intro_details = self.POT_Intro_Details.replace("$LANG", locale)
            with open(PO, "w", encoding="utf8") as f:
                f.write(intro_details)
                for msgid, group in self.translations.items():
                    if msgid == "" or not group.is_in_base:
                        continue
                    f.write(group.usage_comment)
                    f.write(f"{I18NManager.MSGID} \"{msgid}\"\n")
                    msgstr = group.get_translation(locale)
                    if "\n" in msgstr:
                        f.write(f"{I18NManager.MSGSTR} \"\"\n")
                        for line in msgstr.split("\n"):
                            if line != "":
                                f.write(f"\"{line}\"\n")
                    else:
                        f.write(f"{I18NManager.MSGSTR} \"{msgstr}\"\n")
                    f.write("\n")

    def get_POT_intro_details(self):
        timestamp = time.strftime('%Y-%m-%d %H:%M%z')
        return f'''# APPLICATION TRANSLATIONS
# Copyright (C) YEAR ORGANIZATION
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\\n"
"POT-Creation-Date: {timestamp}\\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"
"Last-Translator: Thomas Hall <tomhall.main@gmail.com>\\n"
"Language-Team: $LANG Team <<EMAIL>>\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=cp1252\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Generated-By: pygettext.py 1.5\\n"


'''


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


