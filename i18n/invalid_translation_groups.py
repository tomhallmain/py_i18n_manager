from dataclasses import dataclass, field
from typing import List, Tuple, Dict

from .translation_group import TranslationKey


@dataclass
class InvalidTranslationGroups:
    """Container for all types of invalid translations found in a project.
    Keys are always TranslationKey (group.key from translations).
    """
    not_in_base: List[TranslationKey] = field(default_factory=list)
    missing_locale_groups: List[Tuple[TranslationKey, List[str]]] = field(default_factory=list)
    invalid_unicode_locale_groups: List[Tuple[TranslationKey, List[str]]] = field(default_factory=list)
    invalid_index_locale_groups: List[Tuple[TranslationKey, List[str]]] = field(default_factory=list)
    invalid_brace_locale_groups: List[Tuple[TranslationKey, List[str]]] = field(default_factory=list)
    invalid_leading_space_locale_groups: List[Tuple[TranslationKey, List[str]]] = field(default_factory=list)
    invalid_newline_locale_groups: List[Tuple[TranslationKey, List[str]]] = field(default_factory=list)
    invalid_cjk_locale_groups: List[Tuple[TranslationKey, List[str]]] = field(default_factory=list)
    
    @property
    def has_errors(self) -> bool:
        """Check if there are any invalid translations."""
        return (len(self.not_in_base) > 0 or
                len(self.missing_locale_groups) > 0 or
                len(self.invalid_unicode_locale_groups) > 0 or
                len(self.invalid_index_locale_groups) > 0 or
                len(self.invalid_brace_locale_groups) > 0 or
                len(self.invalid_leading_space_locale_groups) > 0 or
                len(self.invalid_newline_locale_groups) > 0 or
                len(self.invalid_cjk_locale_groups) > 0)

    def get_total_errors(self) -> Dict[str, int]:
        """Get a count of all error types."""
        return {
            'not_in_base': len(self.not_in_base),
            'missing_translations': sum(len(locales) for _, locales in self.missing_locale_groups),
            'invalid_unicode': sum(len(locales) for _, locales in self.invalid_unicode_locale_groups),
            'invalid_indices': sum(len(locales) for _, locales in self.invalid_index_locale_groups),
            'invalid_braces': sum(len(locales) for _, locales in self.invalid_brace_locale_groups),
            'invalid_leading_spaces': sum(len(locales) for _, locales in self.invalid_leading_space_locale_groups),
            'invalid_newlines': sum(len(locales) for _, locales in self.invalid_newline_locale_groups),
            'invalid_cjk': sum(len(locales) for _, locales in self.invalid_cjk_locale_groups)
        }

    def get_invalid_locales(self) -> List[str]:
        """Get a list of all invalid locales."""
        return list(set(loc for _, locs in self.missing_locale_groups for loc in locs) |
                    set(loc for _, locs in self.invalid_unicode_locale_groups for loc in locs) |
                    set(loc for _, locs in self.invalid_index_locale_groups for loc in locs) |
                    set(loc for _, locs in self.invalid_brace_locale_groups for loc in locs) |
                    set(loc for _, locs in self.invalid_leading_space_locale_groups for loc in locs) |
                    set(loc for _, locs in self.invalid_newline_locale_groups for loc in locs) |
                    set(loc for _, locs in self.invalid_cjk_locale_groups for loc in locs))


