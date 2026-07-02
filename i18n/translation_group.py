import re
from dataclasses import dataclass, field
from typing import Any, List, Set

from polib import POEntry

from .invalid_character_set import InvalidCharacterSetAnalyzer
from .stop_character_utils import strip_sentence_punct_after_close_paren
from utils.config import config_manager


def _locale_value_as_text(value: Any) -> str:
    """Flatten stored translation to one string; used only by :meth:`TranslationGroup.value_as_text`."""
    if isinstance(value, list):
        return "\n".join(str(x) for x in value)
    if value is None:
        return ""
    return str(value)


def _map_translation_list_strings(items: list, fn) -> list:
    """Apply ``fn`` to each string leaf; recurse into nested lists (YAML sequences)."""
    out: list = []
    for x in items:
        if isinstance(x, list):
            out.append(_map_translation_list_strings(x, fn))
        else:
            s = x if isinstance(x, str) else str(x)
            out.append(fn(s))
    return out


@dataclass
class InvalidTranslationGroupLocales:
    """Container for validation results of a single translation group."""
    missing_locales: List[str] = field(default_factory=list)
    invalid_unicode_locales: List[str] = field(default_factory=list)
    invalid_index_locales: List[str] = field(default_factory=list)
    invalid_brace_locales: List[str] = field(default_factory=list)
    invalid_leading_space_locales: List[str] = field(default_factory=list)
    invalid_newline_locales: List[str] = field(default_factory=list)
    invalid_character_set_locales: List[str] = field(default_factory=list)
    
    @property
    def has_errors(self) -> bool:
        """Check if there are any invalid translations."""
        return (len(self.missing_locales) > 0 or
                len(self.invalid_unicode_locales) > 0 or
                len(self.invalid_index_locales) > 0 or
                len(self.invalid_brace_locales) > 0 or
                len(self.invalid_leading_space_locales) > 0 or
                len(self.invalid_newline_locales) > 0 or
                len(self.invalid_character_set_locales) > 0)
    
    def get_total_errors(self) -> dict[str, int]:
        """Get a count of all error types."""
        return {
            'missing_translations': len(self.missing_locales),
            'invalid_unicode': len(self.invalid_unicode_locales),
            'invalid_indices': len(self.invalid_index_locales),
            'invalid_braces': len(self.invalid_brace_locales),
            'invalid_leading_spaces': len(self.invalid_leading_space_locales),
            'invalid_newlines': len(self.invalid_newline_locales),
            'invalid_character_set': len(self.invalid_character_set_locales),
        }
    
    def get_invalid_locales(self) -> List[str]:
        """Get a list of all invalid locales."""
        return list(set(self.missing_locales) |
                    set(self.invalid_unicode_locales) |
                    set(self.invalid_index_locales) |
                    set(self.invalid_brace_locales) |
                    set(self.invalid_leading_space_locales) |
                    set(self.invalid_newline_locales) |
                    set(self.invalid_character_set_locales))

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


class TranslationKey:
    """Immutable key for a translation entry (context + msgid). Used so the same msgid
    with different context are distinct. Hashable for use as dict key.
    """
    __slots__ = ('context', 'msgid')

    def __init__(self, msgid: str, *, context: str = ''):
        self.msgid = msgid
        self.context = (context or '').strip()

    def __hash__(self):
        return hash((self.context, self.msgid))

    def __eq__(self, other):
        if not isinstance(other, TranslationKey):
            return NotImplemented
        return self.context == other.context and self.msgid == other.msgid

    def __str__(self):
        if self.context:
            return f"{self.context} | {self.msgid}"
        return self.msgid

    def copy(self) -> 'TranslationKey':
        """Return a new TranslationKey with the same msgid and context."""
        return TranslationKey(self.msgid, context=self.context)

    @classmethod
    def from_entry(cls, entry: POEntry) -> 'TranslationKey':
        """Build a TranslationKey from a polib POEntry."""
        context = (getattr(entry, 'msgctxt', None) or '').strip()
        return cls(entry.msgid, context=context)


@dataclass(frozen=True)
class PlaceholderSignature:
    """Normalized interpolation token signature for translation compatibility checks."""

    indexed: tuple[int, ...] = ()
    brace_named: tuple[str, ...] = ()
    ruby_named: tuple[str, ...] = ()
    printf_named: tuple[str, ...] = ()
    printf_positional_count: int = 0
    ruby_interpolation: tuple[str, ...] = ()
    has_malformed_ruby_named: bool = False

    @classmethod
    def from_text(cls, text: str | None) -> "PlaceholderSignature":
        """Build a signature from a translation string."""
        if not text:
            return cls()

        # Strict `%{name}` tokens for i18n interpolation.
        ruby_named_matches = re.findall(r"%\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
        ruby_named = tuple(sorted(ruby_named_matches))

        # Any `%{...}` form; if strict and loose counts differ, syntax is malformed.
        loose_ruby_named_matches = re.findall(r"%\{([^}]*)\}", text)
        has_malformed_ruby_named = len(loose_ruby_named_matches) != len(ruby_named_matches)

        # Handle escaped braces so they do not get treated as placeholders.
        unescaped = text.replace("{{", "").replace("}}", "")
        indexed = tuple(sorted(int(m) for m in re.findall(r"\{([0-9]+)\}", unescaped)))
        brace_named = tuple(sorted(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", unescaped)))

        # Use real printf conversion letters and ensure the token does not spill
        # into an adjacent word (e.g. "100% de" must not count as "%d").
        # Note: the flag class intentionally excludes a bare space. A literal space flag
        # (e.g. "% d") is valid C printf syntax, but in translated prose "<number> % <word>"
        # is extremely common, and short one-letter words that happen to be printf conversion
        # letters (Portuguese "o" = "the", Italian/Portuguese "e" = "and", ...) would otherwise
        # be misparsed as "%o"/"%e" placeholders.
        printf_named_pattern = r"%\(([A-Za-z_][A-Za-z0-9_]*)\)[#0\-+]?(?:\d+)?(?:\.\d+)?[diouxXeEfFgGcrs](?![A-Za-z0-9_])"
        printf_positional_pattern = r"(?<!%)%(?:[#0\-+]?(?:\d+)?(?:\.\d+)?[diouxXeEfFgGcrs])(?![A-Za-z0-9_])"
        printf_named = tuple(sorted(re.findall(printf_named_pattern, text)))
        printf_positional_count = len(re.findall(printf_positional_pattern, text))

        # `#{...}` is Ruby code interpolation (usually invalid for i18n YAML values).
        ruby_interpolation = tuple(sorted(re.findall(r"#\{([A-Za-z_][A-Za-z0-9_]*)\}", text)))

        return cls(
            indexed=indexed,
            brace_named=brace_named,
            ruby_named=ruby_named,
            printf_named=printf_named,
            printf_positional_count=printf_positional_count,
            ruby_interpolation=ruby_interpolation,
            has_malformed_ruby_named=has_malformed_ruby_named,
        )

    def matches(self, reference: "PlaceholderSignature") -> bool:
        """Check placeholder/token compatibility with a reference signature."""
        return (
            self.indexed == reference.indexed and
            self.ruby_named == reference.ruby_named and
            self.brace_named == reference.brace_named and
            self.printf_named == reference.printf_named and
            self.printf_positional_count == reference.printf_positional_count
        )

    def is_invalid_for(self, reference: "PlaceholderSignature") -> bool:
        """Return True when this signature is invalid versus a reference translation."""
        return (
            self.has_malformed_ruby_named or
            bool(self.ruby_interpolation) or
            not self.matches(reference)
        )



class TranslationGroup():
    def __init__(self, msgid, is_in_base=False, usage_comment=None, tcomment=None, context=None):
        self.key = TranslationKey(msgid, context=context or '')
        self.values = {}
        self.is_in_base = is_in_base
        self.usage_comment = usage_comment
        self.tcomment = tcomment
        self.occurrences = []  # Add occurrences field to store file references
        self.default_locale = config_manager.get('translation.default_locale', 'en')

    @classmethod
    def from_polib_entry(cls, entry: POEntry, is_in_base=False):
        """Create a TranslationGroup from a polib.pofile entry.
        
        Args:
            entry (polib.POEntry): The polib entry to create from
            is_in_base (bool): Whether this translation is in the base set
            
        Returns:
            TranslationGroup: A new TranslationGroup instance
        """
        context = (entry.msgctxt or '').strip() if getattr(entry, 'msgctxt', None) is not None else ''
        group = cls(entry.msgid, is_in_base=is_in_base, context=context or None)
        
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
                return self.key.msgid
            return ""

    def get_translation_escaped(self, locale, fail_on_key_error=False):
        translation = self.get_translation(locale, fail_on_key_error)
        if isinstance(translation, list):
            return _map_translation_list_strings(translation, escape_unicode)
        return escape_unicode(translation)

    def get_translation_unescaped(self, locale, fail_on_key_error=False):
        translation = self.get_translation(locale, fail_on_key_error)
        if isinstance(translation, list):
            return _map_translation_list_strings(translation, unescape_unicode)
        return unescape_unicode(translation)

    @staticmethod
    def value_as_text(stored: Any) -> str:
        """Flatten a stored translation (str or list of lines, possibly nested) to one string."""
        return _locale_value_as_text(stored)

    def get_translation_as_text(self, locale, fail_on_key_error=False) -> str:
        return self.value_as_text(self.get_translation(locale, fail_on_key_error))

    def get_translation_escaped_as_text(self, locale, fail_on_key_error=False) -> str:
        return self.value_as_text(self.get_translation_escaped(locale, fail_on_key_error))

    def get_translation_unescaped_as_text(self, locale, fail_on_key_error=False) -> str:
        return self.value_as_text(self.get_translation_unescaped(locale, fail_on_key_error))

    def get_missing_locales(self, expected_locales):
        def _is_empty(v: Any) -> bool:
            if isinstance(v, list):
                return len(v) == 0
            return not str(v).strip()

        return [
            locale
            for locale in expected_locales
            if locale not in self.values or _is_empty(self.values[locale])
        ]

    def get_encoded_unicode_locales(self):
        """Get locales that have non-ASCII characters encoded in UTF-8.
        
        Returns:
            list: List of locales with non-ASCII characters
        """
        encoded_unicode_locales = []
        for locale, translation in self.values.items():
            text = self.value_as_text(translation)
            if re.search("[^\x00-\x7F]+", text):
                encoded_unicode_locales.append(locale)
        return encoded_unicode_locales

    def get_invalid_escaped_unicode_locales(self):
        """Check for locales that have escaped Unicode sequences (\\uXXXX) which is invalid in UTF-8 context.
        
        Returns:
            list: List of locales with escaped Unicode sequences
        """
        invalid_unicode_locales = []
        for locale, translation in self.values.items():
            if "\\u" in self.value_as_text(translation):
                invalid_unicode_locales.append(locale)
        return invalid_unicode_locales

    def get_invalid_encoded_unicode_locales(self):
        """Check for locales that have non-ASCII characters that aren't properly encoded in UTF-8.
        
        Returns:
            list: List of locales with invalid Unicode characters
        """
        invalid_unicode_locales = []
        for locale, translation in self.values.items():
            text = self.value_as_text(translation)
            # Check for non-ASCII characters that aren't properly encoded
            if any(ord(c) > 127 for c in text):
                # Check if the character is a valid UTF-8 character
                try:
                    # Try to encode and decode to verify it's valid UTF-8
                    text.encode('utf-8').decode('utf-8')
                except UnicodeError:
                    invalid_unicode_locales.append(locale)
        return invalid_unicode_locales

    def get_invalid_unicode_locales(self):
        return list(set(self.get_invalid_escaped_unicode_locales()) | set(self.get_invalid_encoded_unicode_locales()))

    def get_invalid_index_locales(self):
        """Check interpolation/token placeholder compatibility against default locale.

        Historically this validated only `{0}` indices, but now also checks named and
        printf-style placeholders to catch runtime interpolation mismatches.
        """
        invalid_index_locales = []
        default_translation = self.get_translation_as_text(self.default_locale)
        default_signature = PlaceholderSignature.from_text(default_translation)

        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue

            this_signature = PlaceholderSignature.from_text(self.value_as_text(translation))
            if this_signature.is_invalid_for(default_signature):
                invalid_index_locales.append(locale)

        return invalid_index_locales

    def get_invalid_brace_locales(self):
        """Check for mismatched structural brackets across locales.

        ``[]``, ``<>``, ``{}``: open/close counts must match the default locale.

        ``()``: usually **balance-only** (open count equals close count) so translators may add or
        drop parentheticals for tone. Exception: when the default **or** the locale string is a
        *full-string parenthetical* (trimmed text starts with ``(``/（, balanced counts, and the
        closing ``)``/） either ends the string or is followed only by sentence punctuation such as
        ``.`` *outside* the paren—e.g. ``(….)`` vs ``(…).``), the other side must match—otherwise the
        locale is invalid.
        """
        invalid_brace_locales = []
        default_translation = self.get_translation_as_text(self.default_locale)

        brace_pairs = [
            ('(', (')', '\uff09')),
            ('[', ']'),
            ('<', '>'),
            ('{', '}'),
        ]

        def _brace_pair_counts(text: str, open_brace: str, close_brace) -> tuple[int, int]:
            """Return (open_count, close_count) for one structural pair.

            For ``(``, ``)`` counts include full-width （ U+FF08 / ） U+FF09 so CJK typography
            matches ASCII.
            """
            if open_brace == '(':
                opens = text.count('(') + text.count('\uff08')
            else:
                opens = text.count(open_brace)
            if isinstance(close_brace, tuple):
                closes = sum(text.count(c) for c in close_brace)
            else:
                closes = text.count(close_brace)
            return opens, closes

        def _is_fully_wrapped_parenthetical(s: str, open_count: int, close_count: int) -> bool:
            """True when the string is a full parenthetical, including ``(...).`` (stop outside ``)``)."""
            t = (s or "").strip()
            if open_count == 0:
                return False
            if len(t) < 2:
                return False
            if t[0] not in ('(', '\uff08'):
                return False
            u = strip_sentence_punct_after_close_paren(t)
            if len(u) < 2:
                return False
            if u[-1] not in (')', '\uff09'):
                return False
            return open_count == close_count and open_count >= 1

        default_counts = {}
        open_paren_count = -1
        close_paren_count = -1
        for open_brace, close_brace in brace_pairs:
            default_counts[open_brace] = _brace_pair_counts(
                default_translation, open_brace, close_brace
            )
            if open_brace == '(':
                open_paren_count = default_counts[open_brace][0]
                close_paren_count = default_counts[open_brace][1]

        if open_paren_count > 0:
            default_full_paren = _is_fully_wrapped_parenthetical(default_translation, open_paren_count, close_paren_count)
        else:
            default_full_paren = False

        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue

            loc_full_paren = False
            text = self.value_as_text(translation)

            for open_brace, close_brace in brace_pairs:
                open_count, close_count = _brace_pair_counts(text, open_brace, close_brace)

                if open_brace == '(':
                    loc_full_paren = _is_fully_wrapped_parenthetical(text, open_count, close_count)
                    if open_count != close_count:
                        invalid_brace_locales.append(locale)
                        break
                    continue

                default_open, default_close = default_counts[open_brace]
                if open_count != default_open or close_count != default_close:
                    invalid_brace_locales.append(locale)
                    break
            else:
                if default_full_paren != loc_full_paren:
                    invalid_brace_locales.append(locale)

        return invalid_brace_locales

    def get_invalid_leading_space_locales(self):
        """Check if leading and trailing spaces match the default locale.
        
        Returns:
            list: List of locales with mismatched leading or trailing spaces compared to default locale
        """
        invalid_space_locales = []
        default_translation = self.get_translation_as_text(self.default_locale)
        
        # Get default locale space counts
        default_leading_spaces = len(default_translation) - len(default_translation.lstrip())
        default_trailing_spaces = len(default_translation) - len(default_translation.rstrip())
        
        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue
                
            text = self.value_as_text(translation)
            # Get this locale's space counts
            leading_spaces = len(text) - len(text.lstrip())
            trailing_spaces = len(text) - len(text.rstrip())
            
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
        default_translation = self.get_translation_as_text(self.default_locale)
        
        # Count explicit newlines in default
        default_explicit_newlines = default_translation.count('\\n')
        default_encoded_newlines = default_translation.count('\n')
        
        for locale, translation in self.values.items():
            if locale == self.default_locale:
                continue
                
            text = self.value_as_text(translation)
            # Count newlines in this locale
            explicit_newlines = text.count('\\n')
            encoded_newlines = text.count('\n')
            
            # Check if counts match default locale
            if explicit_newlines != default_explicit_newlines or encoded_newlines != default_encoded_newlines:
                invalid_newline_locales.append(locale)
                
        return invalid_newline_locales

    def get_invalid_character_set_locales(
        self,
        threshold_percentage=40,
        ignore_patterns: tuple[str, ...] = tuple(),
    ):
        """Get locales whose text script profile mismatches locale expectations.

        Args:
            threshold_percentage (int): Percentage threshold used by character-set checks.

        Returns:
            list: Locales flagged by character-set mismatch rules.
        """
        threshold = max(0, min(100, int(threshold_percentage))) / 100.0
        values_as_text = {loc: self.value_as_text(v) for loc, v in self.values.items()}
        return InvalidCharacterSetAnalyzer.find_invalid_locales(
            values_as_text,
            threshold,
            ignore_patterns=ignore_patterns,
            default_locale=self.default_locale,
        )

    # Backward-compat alias for existing callers while naming migrates.
    def get_invalid_non_latin_locales_for_latin_locales(
        self, threshold_percentage=40, ignore_patterns: tuple[str, ...] = tuple()
    ):
        return self.get_invalid_character_set_locales(threshold_percentage, ignore_patterns)

    def collect_quality_review_findings(
        self,
        default_locale: str,
        locales: List[str],
        excluded_msgids: Set[str],
        latin_ignore_patterns: tuple[str, ...] = tuple(),
        use_builtin_exclusions: bool = True,
    ) -> list:
        """Run advisory quality checks for this group (see :mod:`i18n.translation_quality_review`)."""
        from i18n.translation_quality_review import collect_findings_for_group

        if self.key.msgid in excluded_msgids:
            return []
        return collect_findings_for_group(
            self,
            default_locale,
            locales,
            latin_ignore_patterns=latin_ignore_patterns,
            use_builtin_exclusions=use_builtin_exclusions,
        )

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
        # Check if the key is the same
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
            if locale in invalid_locales and isinstance(self.values[locale], str):
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
                if not isinstance(translation, str):
                    continue
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
            if isinstance(translation, str) and "\\n" in translation:
                self.values[locale] = translation.replace("\\n", "\n")
                fixed = True

        return fixed

    def get_invalid_translations(
        self,
        locales,
        ignore_patterns: tuple[str, ...] = tuple(),
    ) -> InvalidTranslationGroupLocales:
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
        invalid_locales.invalid_character_set_locales = self.get_invalid_character_set_locales(
            ignore_patterns=ignore_patterns
        )
        return invalid_locales