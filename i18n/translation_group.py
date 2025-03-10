import re
from utils.config import ConfigManager

# Initialize config manager
config = ConfigManager()

def escape_unicode(s):
    """Convert a string to ASCII-encoded Unicode format for PO files.
    
    Args:
        s (str): The string to convert
        
    Returns:
        str: The string in ASCII-encoded Unicode format
    """
    ret = []
    for c in s:
        n = ord(c)
        if n > 0x7F:
            ret.append("\\u{:04x}".format(n))
        else:
            ret.append(c)
    return "".join(ret)


def unescape_unicode(s):
    """Convert an ASCII-encoded Unicode string back to regular Unicode.
    
    Args:
        s (str): The ASCII-encoded Unicode string to convert
        
    Returns:
        str: The string in regular Unicode format
    """
    # Replace \u00 with \x for short sequences
    s = s.replace('\\u00', '\\x')
    # Replace \u with \U for long sequences
    s = s.replace('\\u', '\\U')
    
    try:
        # Decode the escaped string back to Unicode
        return s.encode('ascii').decode('unicode_escape')
    except Exception as e:
        print(f"Error unescaping string: {e}")
        return s



def get_string_format_indices(s):
    indices = []
    for match in re.finditer(r"{[0-9]+}", s):
        match_text = match.group()
        idx = int(match_text[1:-1])
        indices.append(idx)
    indices.sort()
    return tuple(indices)


class TranslationGroup():
    def __init__(self, key, is_in_base, usage_comment):
        self.key = key
        self.usage_comment = usage_comment
        self.is_in_base = is_in_base
        self.values = {}
        self.default_locale = config.get('translation.default_locale', 'en')
    
    def add_translation(self, locale, translation):
        self.values[locale] = translation
    
    def get_translation(self, locale, fail_on_key_error=False):
        try:
            return self.values[locale]
        except KeyError as e:
            if fail_on_key_error:
               raise e
            if locale == self.default_locale:
                return self.key
            return ""

    def get_translation_escaped(self, locale, fail_on_key_error=False):
        translation = self.get_translation(locale, fail_on_key_error)
        return escape_unicode(translation)

    def get_translation_unescaped(self, locale, fail_on_key_error=False):
        translation = self.get_translation(locale, fail_on_key_error)
        return unescape_unicode(translation)

    def get_missing_locales(self, expected_locales):
        return [locale for locale in expected_locales if not locale in self.values or self.values[locale].strip() == '']

    def get_invalid_unicode_locales(self):
        invalid_unicode_locales = []
        for locale, translation in self.values.items():
            if re.search("[^\x00-\x7F]+", translation):
                invalid_unicode_locales.append(locale)
        return invalid_unicode_locales

    def get_invalid_index_locales(self):
        invalid_index_locales = []
        default_translation = self.get_translation(self.default_locale)
        if "{0}" in default_translation:
            default_indices = get_string_format_indices(default_translation)
            for locale, translation in self.values.items():
                if locale == self.default_locale:
                    continue
                this_locale_indices = get_string_format_indices(translation)
                if default_indices != this_locale_indices:
                    invalid_index_locales.append(locale)
        return invalid_index_locales

    def fix_encoded_unicode_escape_strings(self, invalid_locales):
        for locale in self.values:
            if locale in invalid_locales:
                self.values[locale] = escape_unicode(self.values[locale])