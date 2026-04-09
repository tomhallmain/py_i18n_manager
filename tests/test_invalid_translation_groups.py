"""Tests for InvalidTranslationGroups, TranslationQualityFindings, and QualityReviewFinding."""

from i18n.invalid_translation_groups import (
    InvalidTranslationGroups,
    QualityReviewFinding,
    TranslationQualityFindings,
)
from i18n.translation_group import TranslationKey
from utils.globals import QualityHeuristicKind


def _key(msgid: str) -> TranslationKey:
    return TranslationKey(msgid)


class TestInvalidTranslationGroupsHasErrors:
    def test_empty_has_no_errors(self):
        assert not InvalidTranslationGroups().has_errors

    def test_not_in_base_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.not_in_base.append(_key("stale"))
        assert g.has_errors

    def test_missing_locale_group_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.missing_locale_groups.append((_key("hello"), ["fr"]))
        assert g.has_errors

    def test_invalid_unicode_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_unicode_locale_groups.append((_key("u"), ["de"]))
        assert g.has_errors

    def test_invalid_index_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_index_locale_groups.append((_key("i"), ["es"]))
        assert g.has_errors

    def test_invalid_brace_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_brace_locale_groups.append((_key("b"), ["ja"]))
        assert g.has_errors

    def test_invalid_leading_space_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_leading_space_locale_groups.append((_key("sp"), ["zh"]))
        assert g.has_errors

    def test_invalid_newline_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_newline_locale_groups.append((_key("nl"), ["ko"]))
        assert g.has_errors

    def test_invalid_character_set_triggers_has_errors(self):
        g = InvalidTranslationGroups()
        g.invalid_character_set_locale_groups.append((_key("cs"), ["ru"]))
        assert g.has_errors


class TestInvalidTranslationGroupsTotalErrors:
    def test_get_total_errors_empty(self):
        counts = InvalidTranslationGroups().get_total_errors()
        assert counts["not_in_base"] == 0
        assert counts["missing_translations"] == 0
        assert counts["invalid_unicode"] == 0
        assert counts["invalid_indices"] == 0
        assert counts["invalid_braces"] == 0
        assert counts["invalid_leading_spaces"] == 0
        assert counts["invalid_newlines"] == 0
        assert counts["invalid_character_set"] == 0

    def test_missing_translations_sums_locales_across_groups(self):
        g = InvalidTranslationGroups()
        g.missing_locale_groups.append((_key("a"), ["fr", "de"]))
        g.missing_locale_groups.append((_key("b"), ["es"]))
        assert g.get_total_errors()["missing_translations"] == 3

    def test_not_in_base_counts_keys(self):
        g = InvalidTranslationGroups()
        g.not_in_base.append(_key("s1"))
        g.not_in_base.append(_key("s2"))
        assert g.get_total_errors()["not_in_base"] == 2

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
        assert counts["not_in_base"] == 1
        assert counts["invalid_unicode"] == 1
        assert counts["invalid_indices"] == 2
        assert counts["invalid_braces"] == 1
        assert counts["invalid_leading_spaces"] == 1
        assert counts["invalid_newlines"] == 1
        assert counts["invalid_character_set"] == 1


class TestInvalidTranslationGroupsInvalidLocales:
    def test_empty_returns_empty_list(self):
        assert InvalidTranslationGroups().get_invalid_locales() == []

    def test_deduplicates_locale_appearing_in_multiple_categories(self):
        g = InvalidTranslationGroups()
        g.missing_locale_groups.append((_key("a"), ["fr", "de"]))
        g.invalid_index_locale_groups.append((_key("b"), ["fr"]))
        locales = set(g.get_invalid_locales())
        assert locales == {"fr", "de"}

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
        assert locales == {"fr", "de", "es", "ja", "zh", "ko", "ru"}


class TestTranslationQualityFindings:
    def _finding(self, locale, signal=QualityHeuristicKind.IDENTICAL_TO_DEFAULT):
        return QualityReviewFinding(
            key_msgid="hello",
            key_context="",
            locale=locale,
            signal=signal,
        )

    def test_has_findings_false_when_empty(self):
        assert not TranslationQualityFindings().has_findings

    def test_has_findings_true_when_populated(self):
        f = TranslationQualityFindings(findings=[self._finding("fr")])
        assert f.has_findings

    def test_count_by_signal_empty(self):
        assert TranslationQualityFindings().count_by_signal() == {}

    def test_count_by_signal_single_kind(self):
        f = TranslationQualityFindings(findings=[self._finding("fr")])
        counts = f.count_by_signal()
        assert counts.get(QualityHeuristicKind.IDENTICAL_TO_DEFAULT.value) == 1

    def test_count_by_signal_multiple_kinds(self):
        f = TranslationQualityFindings(findings=[
            self._finding("fr", QualityHeuristicKind.IDENTICAL_TO_DEFAULT),
            self._finding("de", QualityHeuristicKind.IDENTICAL_TO_DEFAULT),
            self._finding("ja", QualityHeuristicKind.LATIN_IN_CJK_LOCALE),
        ])
        counts = f.count_by_signal()
        assert counts[QualityHeuristicKind.IDENTICAL_TO_DEFAULT.value] == 2
        assert counts[QualityHeuristicKind.LATIN_IN_CJK_LOCALE.value] == 1
