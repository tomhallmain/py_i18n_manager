"""Tests for InvalidTranslationGroups, TranslationQualityFindings, and QualityReviewFinding."""

import unittest

from i18n.invalid_translation_groups import (
    InvalidTranslationGroups,
    QualityReviewFinding,
    TranslationQualityFindings,
)
from i18n.translation_group import TranslationKey
from utils.globals import QualityHeuristicKind


def _key(msgid: str) -> TranslationKey:
    return TranslationKey(msgid)


class TestInvalidTranslationGroupsHasErrors(unittest.TestCase):
    def test_empty_has_no_errors(self):
        self.assertFalse(InvalidTranslationGroups().has_errors)

    def test_not_in_base_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.not_in_base.append(_key("stale"))
        self.assertTrue(g.has_errors)

    def test_missing_locale_group_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.missing_locale_groups.append((_key("hello"), ["fr"]))
        self.assertTrue(g.has_errors)

    def test_invalid_unicode_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_unicode_locale_groups.append((_key("u"), ["de"]))
        self.assertTrue(g.has_errors)

    def test_invalid_index_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_index_locale_groups.append((_key("i"), ["es"]))
        self.assertTrue(g.has_errors)

    def test_invalid_brace_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_brace_locale_groups.append((_key("b"), ["ja"]))
        self.assertTrue(g.has_errors)

    def test_invalid_leading_space_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_leading_space_locale_groups.append((_key("sp"), ["zh"]))
        self.assertTrue(g.has_errors)

    def test_invalid_newline_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_newline_locale_groups.append((_key("nl"), ["ko"]))
        self.assertTrue(g.has_errors)

    def test_invalid_character_set_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_character_set_locale_groups.append((_key("cs"), ["ru"]))
        self.assertTrue(g.has_errors)


class TestInvalidTranslationGroupsTotalErrors(unittest.TestCase):
    def test_get_total_errors_empty(self):
        counts = InvalidTranslationGroups().get_total_errors()
        self.assertEqual(counts["not_in_base"], 0)
        self.assertEqual(counts["missing_translations"], 0)
        self.assertEqual(counts["invalid_unicode"], 0)
        self.assertEqual(counts["invalid_indices"], 0)
        self.assertEqual(counts["invalid_braces"], 0)
        self.assertEqual(counts["invalid_leading_spaces"], 0)
        self.assertEqual(counts["invalid_newlines"], 0)
        self.assertEqual(counts["invalid_character_set"], 0)

    def test_missing_translations_sums_locales_across_groups(self):
        g = InvalidTranslationGroups()
        g.missing_locale_groups.append((_key("a"), ["fr", "de"]))
        g.missing_locale_groups.append((_key("b"), ["es"]))
        self.assertEqual(g.get_total_errors()["missing_translations"], 3)

    def test_not_in_base_counts_keys(self):
        g = InvalidTranslationGroups()
        g.not_in_base.append(_key("s1"))
        g.not_in_base.append(_key("s2"))
        self.assertEqual(g.get_total_errors()["not_in_base"], 2)

    def test_all_categories_counted(self):
        g = InvalidTranslationGroups()
        g.not_in_base.append(_key("s"))
        g.invalid_unicode_locale_groups.append((_key("u"), ["fr"]))
        g.invalid_index_locale_groups.append((_key("i"), ["de", "es"]))
        g.invalid_brace_locale_groups.append((_key("b"), ["ja"]))
        g.invalid_leading_space_locale_groups.append((_key("sp"), ["zh"]))
        g.invalid_newline_locale_groups.append((_key("nl"), ["ko"]))
        g.invalid_character_set_locale_groups.append((_key("cs"), ["ru"]))
        counts = g.get_total_errors()
        self.assertEqual(counts["not_in_base"], 1)
        self.assertEqual(counts["invalid_unicode"], 1)
        self.assertEqual(counts["invalid_indices"], 2)
        self.assertEqual(counts["invalid_braces"], 1)
        self.assertEqual(counts["invalid_leading_spaces"], 1)
        self.assertEqual(counts["invalid_newlines"], 1)
        self.assertEqual(counts["invalid_character_set"], 1)


class TestInvalidTranslationGroupsInvalidLocales(unittest.TestCase):
    def test_empty_returns_empty_list(self):
        self.assertEqual(InvalidTranslationGroups().get_invalid_locales(), [])

    def test_deduplicates_locale_appearing_in_multiple_categories(self):
        g = InvalidTranslationGroups()
        g.missing_locale_groups.append((_key("a"), ["fr", "de"]))
        g.invalid_index_locale_groups.append((_key("b"), ["fr"]))
        locales = set(g.get_invalid_locales())
        self.assertEqual(locales, {"fr", "de"})

    def test_all_categories_contribute(self):
        g = InvalidTranslationGroups()
        g.missing_locale_groups.append((_key("x"), ["fr"]))
        g.invalid_unicode_locale_groups.append((_key("x"), ["de"]))
        g.invalid_index_locale_groups.append((_key("x"), ["es"]))
        g.invalid_brace_locale_groups.append((_key("x"), ["ja"]))
        g.invalid_leading_space_locale_groups.append((_key("x"), ["zh"]))
        g.invalid_newline_locale_groups.append((_key("x"), ["ko"]))
        g.invalid_character_set_locale_groups.append((_key("x"), ["ru"]))
        locales = set(g.get_invalid_locales())
        self.assertEqual(locales, {"fr", "de", "es", "ja", "zh", "ko", "ru"})


class TestTranslationQualityFindings(unittest.TestCase):
    def _finding(self, locale, signal=QualityHeuristicKind.IDENTICAL_TO_DEFAULT):
        return QualityReviewFinding(
            key_msgid="hello",
            key_context="",
            locale=locale,
            signal=signal,
        )

    def test_has_findings_false_when_empty(self):
        self.assertFalse(TranslationQualityFindings().has_findings)

    def test_has_findings_true_when_populated(self):
        f = TranslationQualityFindings(findings=[self._finding("fr")])
        self.assertTrue(f.has_findings)

    def test_count_by_signal_empty(self):
        self.assertEqual(TranslationQualityFindings().count_by_signal(), {})

    def test_count_by_signal_single_kind(self):
        f = TranslationQualityFindings(findings=[self._finding("fr")])
        counts = f.count_by_signal()
        self.assertEqual(counts.get(QualityHeuristicKind.IDENTICAL_TO_DEFAULT.value), 1)

    def test_count_by_signal_multiple_kinds(self):
        f = TranslationQualityFindings(findings=[
            self._finding("fr", QualityHeuristicKind.IDENTICAL_TO_DEFAULT),
            self._finding("de", QualityHeuristicKind.IDENTICAL_TO_DEFAULT),
            self._finding("ja", QualityHeuristicKind.LATIN_IN_CJK_LOCALE),
        ])
        counts = f.count_by_signal()
        self.assertEqual(counts[QualityHeuristicKind.IDENTICAL_TO_DEFAULT.value], 2)
        self.assertEqual(counts[QualityHeuristicKind.LATIN_IN_CJK_LOCALE.value], 1)


if __name__ == "__main__":
    unittest.main()
