import re
from dataclasses import dataclass, field
from typing import List
from utils.config import ConfigManager

# Initialize config manager
config = ConfigManager()

@dataclass
class InvalidTranslationGroupLocales:
    """Container for validation results of a single translation group."""
    missing_locales: List[str] = field(default_factory=list)
    invalid_unicode_locales: List[str] = field(default_factory=list)
    invalid_index_locales: List[str] = field(default_factory=list)
    invalid_brace_locales: List[str] = field(default_factory=list)
    invalid_leading_space_locales: List[str] = field(default_factory=list)
    invalid_newline_locales: List[str] = field(default_factory=list)
    
    @property
    def has_errors(self) -> bool:
        """Check if there are any invalid translations."""
        return (len(self.missing_locales) > 0 or
                len(self.invalid_unicode_locales) > 0 or
                len(self.invalid_index_locales) > 0 or
                len(self.invalid_brace_locales) > 0 or
                len(self.invalid_leading_space_locales) > 0 or
                len(self.invalid_newline_locales) > 0)
    
    def get_total_errors(self) -> dict[str, int]:
        """Get a count of all error types."""
        return {
            'missing_translations': len(self.missing_locales),
            'invalid_unicode': len(self.invalid_unicode_locales),
            'invalid_indices': len(self.invalid_index_locales),
            'invalid_braces': len(self.invalid_brace_locales),
            'invalid_leading_spaces': len(self.invalid_leading_space_locales),
            'invalid_newlines': len(self.invalid_newline_locales)
        }
    
    def get_invalid_locales(self) -> List[str]:
        """Get a list of all invalid locales."""
        return list(set(self.missing_locales) |
                    set(self.invalid_unicode_locales) |
                    set(self.invalid_index_locales) |
                    set(self.invalid_brace_locales) |
                    set(self.invalid_leading_space_locales) |
                    set(self.invalid_newline_locales))

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

    def get_invalid_brace_locales(self):
        """Check for mismatched open/close brace counts across all locales.
        
        Returns:
            list: List of locales with mismatched brace counts compared to default locale
        """
        invalid_brace_locales = []
        default_translation = self.get_translation(self.default_locale)
        
        # Define structural brace pairs to check
        # Parentheses are treated more leniently (only check closure)
        # Other braces are checked against default locale
        brace_pairs = [
            ('(', ')'),  # Parentheses - only check closure
            ('[', ']'),  # Square brackets - check against default
            ('<', '>'),  # Angle brackets - check against default
            ('{', '}')   # Curly braces - check against default
        ]
        
        # Get default locale brace counts for non-parentheses braces
        default_counts = {}
        for open_brace, close_brace in brace_pairs[1:]:  # Skip parentheses
            default_counts[(open_brace, close_brace)] = (
                default_translation.count(open_brace),
                default_translation.count(close_brace)
            )
        
        # Check each locale
        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue
                
            for open_brace, close_brace in brace_pairs:
                open_count = translation.count(open_brace)
                close_count = translation.count(close_brace)
                
                if open_brace == '(':  # Parentheses - only check closure
                    if open_count != close_count:
                        invalid_brace_locales.append(locale)
                        break
                else:  # Other braces - check against default
                    default_open, default_close = default_counts[(open_brace, close_brace)]
                    if open_count != default_open or close_count != default_close:
                        invalid_brace_locales.append(locale)
                        break
                    
        return invalid_brace_locales

    def get_invalid_leading_space_locales(self):
        """Check if leading and trailing spaces match the default locale.
        
        Returns:
            list: List of locales with mismatched leading or trailing spaces compared to default locale
        """
        invalid_space_locales = []
        default_translation = self.get_translation(self.default_locale)
        
        # Get default locale space counts
        default_leading_spaces = len(default_translation) - len(default_translation.lstrip())
        default_trailing_spaces = len(default_translation) - len(default_translation.rstrip())
        
        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue
                
            # Get this locale's space counts
            leading_spaces = len(translation) - len(translation.lstrip())
            trailing_spaces = len(translation) - len(translation.rstrip())
            
            # Check if either leading or trailing spaces don't match default
            if (leading_spaces != default_leading_spaces or 
                trailing_spaces != default_trailing_spaces):
                invalid_space_locales.append(locale)
                
        return invalid_space_locales

    def get_invalid_newline_locales(self):
        """Check if newline characters match the default locale.
        
        Returns:
            list: List of locales with mismatched newline characters compared to default locale
        """
        invalid_newline_locales = []
        default_translation = self.get_translation(self.default_locale)
        
        # Count explicit newlines in default
        default_explicit_newlines = default_translation.count('\\n')
        default_encoded_newlines = default_translation.count('\n')
        
        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue
                
            # Count newlines in this locale
            explicit_newlines = translation.count('\\n')
            encoded_newlines = translation.count('\n')
            
            # Check if counts match default locale
            if explicit_newlines != default_explicit_newlines or encoded_newlines != default_encoded_newlines:
                invalid_newline_locales.append(locale)
                
        return invalid_newline_locales

    def fix_encoded_unicode_escape_strings(self, invalid_locales):
        for locale in self.values:
            if locale in invalid_locales:
                self.values[locale] = escape_unicode(self.values[locale])

    def fix_leading_and_trailing_spaces(self, invalid_locales):
        """Fix leading and trailing spaces in translations to match the default locale.
        
        Args:
            invalid_locales (list): List of locales to fix
        """
        default_translation = self.get_translation(self.default_locale)
        default_leading_spaces = len(default_translation) - len(default_translation.lstrip())
        default_trailing_spaces = len(default_translation) - len(default_translation.rstrip())
        
        for locale in self.values:
            if locale in invalid_locales and locale != self.default_locale:
                translation = self.values[locale]
                # Get current space counts
                current_leading_spaces = len(translation) - len(translation.lstrip())
                current_trailing_spaces = len(translation) - len(translation.rstrip())
                
                # Calculate how many spaces to add/remove
                leading_diff = default_leading_spaces - current_leading_spaces
                trailing_diff = default_trailing_spaces - current_trailing_spaces
                
                # Apply the fixes
                if leading_diff > 0:
                    translation = " " * leading_diff + translation.lstrip()
                elif leading_diff < 0:
                    translation = translation[abs(leading_diff):]
                    
                if trailing_diff > 0:
                    translation = translation.rstrip() + " " * trailing_diff
                elif trailing_diff < 0:
                    translation = translation[:len(translation) + trailing_diff]
                    
                self.values[locale] = translation

    def get_invalid_translations(self, locales) -> InvalidTranslationGroupLocales:
        """Get all invalid translation locales for this group.
        
        Returns:
            InvalidTranslationGroupLocales: Container with all types of invalid translations
        """
        invalid_locales = InvalidTranslationGroupLocales()
        invalid_locales.missing_locales = self.get_missing_locales(locales)
        invalid_locales.invalid_unicode_locales = self.get_invalid_unicode_locales()
        invalid_locales.invalid_index_locales = self.get_invalid_index_locales()
        invalid_locales.invalid_brace_locales = self.get_invalid_brace_locales()
        invalid_locales.invalid_leading_space_locales = self.get_invalid_leading_space_locales()
        invalid_locales.invalid_newline_locales = self.get_invalid_newline_locales()
        return invalid_locales