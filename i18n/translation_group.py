import re
from dataclasses import dataclass, field
from typing import List

from polib import POEntry

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
    # If the string already contains Unicode escape sequences, return as is
    if '\\u' in s or '\\U' in s:
        return s
        
    ret = []
    for c in s:
        n = ord(c)
        if n > 0x7F:
            # For characters above 0x7F, use Unicode escape sequence
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
    try:
        # Split the string into parts, handling each escape sequence separately
        parts = []
        current = 0
        while current < len(s):
            if s[current:current+2] == '\\u': # NOTE: this will only be run on longer unicode sequences
                # Found a Unicode escape sequence
                hex_str = s[current+2:current+6]
                if len(hex_str) == 4:  # Valid hex sequence
                    try:
                        # Convert hex to integer and then to character
                        char = chr(int(hex_str, 16))
                        parts.append(char)
                        current += 6
                        continue
                    except ValueError:
                        pass
            # If we get here, either no escape sequence or invalid one
            parts.append(s[current])
            current += 1
        return ''.join(parts)
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
    def __init__(self, msgid, is_in_base=False, usage_comment=None, tcomment=None):
        self.key = msgid
        self.values = {}
        self.is_in_base = is_in_base
        self.usage_comment = usage_comment
        self.tcomment = tcomment
        self.occurrences = []  # Add occurrences field to store file references
        self.default_locale = config.get('translation.default_locale', 'en')
    
    @classmethod
    def from_polib_entry(cls, entry: POEntry, is_in_base=False):
        """Create a TranslationGroup from a polib.pofile entry.
        
        Args:
            entry (polib.POEntry): The polib entry to create from
            is_in_base (bool): Whether this translation is in the base set
            
        Returns:
            TranslationGroup: A new TranslationGroup instance
        """
        group = cls(entry.msgid, is_in_base=is_in_base)
        
        # Handle comments
        if entry.comment:
            group.usage_comment = str(entry.comment)
        if entry.tcomment:
            group.tcomment = str(entry.tcomment)
            
        # Handle occurrences (file references)
        if entry.occurrences:
            group.occurrences = list(entry.occurrences)
            
        return group

    def add_translation(self, locale, msgstr):
        self.values[locale] = msgstr
    
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

    def get_encoded_unicode_locales(self):
        """Get locales that have non-ASCII characters encoded in UTF-8.
        
        Returns:
            list: List of locales with non-ASCII characters
        """
        encoded_unicode_locales = []
        for locale, translation in self.values.items():
            if re.search("[^\x00-\x7F]+", translation):
                encoded_unicode_locales.append(locale)
        return encoded_unicode_locales

    def get_invalid_escaped_unicode_locales(self):
        """Check for locales that have escaped Unicode sequences (\\uXXXX) which is invalid in UTF-8 context.
        
        Returns:
            list: List of locales with escaped Unicode sequences
        """
        invalid_unicode_locales = []
        for locale, translation in self.values.items():
            if "\\u" in translation:
                invalid_unicode_locales.append(locale)
        return invalid_unicode_locales

    def get_invalid_encoded_unicode_locales(self):
        """Check for locales that have non-ASCII characters that aren't properly encoded in UTF-8.
        
        Returns:
            list: List of locales with invalid Unicode characters
        """
        invalid_unicode_locales = []
        for locale, translation in self.values.items():
            # Check for non-ASCII characters that aren't properly encoded
            if any(ord(c) > 127 for c in translation):
                # Check if the character is a valid UTF-8 character
                try:
                    # Try to encode and decode to verify it's valid UTF-8
                    translation.encode('utf-8').decode('utf-8')
                except UnicodeError:
                    invalid_unicode_locales.append(locale)
        return invalid_unicode_locales

    def get_invalid_unicode_locales(self):
        return list(set(self.get_invalid_escaped_unicode_locales()) | set(self.get_invalid_encoded_unicode_locales()))

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
        # Include Unicode close parenthesis \uff09 as alternative to )
        brace_pairs = [
            ('(', (')', '\uff09')),  # Parentheses - only check closure, unicode close parenthsis is valid
            ('[', ']'),  # Square brackets - check against default
            ('<', '>'),  # Angle brackets - check against default
            ('{', '}')   # Curly braces - check against default
        ]
        
        # Get default locale brace counts for non-parentheses braces
        default_counts = {}
        for open_brace, close_brace in brace_pairs:
            # Calculate total count of close braces (handling both single and tuple cases)
            close_brace_count = 0
            if isinstance(close_brace, tuple):
                for close_brace_variant in close_brace:
                    close_brace_count += default_translation.count(close_brace_variant)
            else:
                close_brace_count = default_translation.count(close_brace)
            
            # Store the open count and total close count
            default_counts[open_brace] = (
                default_translation.count(open_brace),
                close_brace_count
            )
        
        # Check each locale
        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue
                
            for open_brace, close_brace in brace_pairs:
                open_count = translation.count(open_brace)
                
                # Calculate total count of close braces (handling both single and tuple cases)
                close_count = 0
                if isinstance(close_brace, tuple):
                    for close_brace_variant in close_brace:
                        close_count += translation.count(close_brace_variant)
                else:
                    close_count = translation.count(close_brace)
                
                if open_brace == '(':  # Parentheses - only check closure
                    if open_count != close_count:
                        invalid_brace_locales.append(locale)
                        break
                else:  # Other braces - check against default
                    default_open, default_close = default_counts[open_brace]
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

    def has_translation_changes(self, other: 'TranslationGroup') -> bool:
        """Compare this translation group with another to check if translations have changed.
        
        This method compares the actual translation values, ignoring metadata like
        occurrences, comments, etc. Only changes to the actual translation strings
        are considered meaningful changes.
        
        Args:
            other (TranslationGroup): The other translation group to compare with
            
        Returns:
            bool: True if any translation values have changed, False otherwise
        """
        # Check if the msgid is the same
        if self.key != other.key:
            return True
        
        # Get all unique locales from both groups
        all_locales = set(self.values.keys()) | set(other.values.keys())
        
        # Compare translation values for each locale
        for locale in all_locales:
            self_translation = self.get_translation(locale)
            other_translation = other.get_translation(locale)
            
            if self_translation != other_translation:
                return True
        
        return False

    def fix_ensure_encoded_unicode(self, invalid_locales):
        for locale in self.values:
            if locale in invalid_locales:
                self.values[locale] = unescape_unicode(self.values[locale])

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

    def fix_invalid_explicit_newlines(self):
        """Fix invalid newlines in translations by replacing explicit newlines with actual newlines."""
        fixed = False

        for locale, translation in self.values.items():
            if "\\n" in translation:
                self.values[locale] = translation.replace("\\n", "\n")
                fixed = True

        return fixed

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