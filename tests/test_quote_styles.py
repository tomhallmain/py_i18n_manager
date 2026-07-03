"""Tests for i18n.quote_styles: quote-character-style detection and per-locale defaults."""

from i18n.quote_styles import (
    QuoteStyle,
    compute_dominant_quote_style_by_locale,
    default_valid_quote_style,
    detect_quote_style,
)
from i18n.translation_group import TranslationGroup


class TestDetectQuoteStyleDoubleQuotes:
    def test_straight_double_quotes(self):
        assert detect_quote_style('He said "hello" to me.') == QuoteStyle.STRAIGHT

    def test_curly_double_quotes(self):
        assert detect_quote_style("She said “hello” to me.") == QuoteStyle.CURLY

    def test_guillemets(self):
        assert detect_quote_style("Il a dit «bonjour».") == QuoteStyle.GUILLEMETS

    def test_reversed_guillemets(self):
        assert detect_quote_style("»Hallo« sagte er.") == QuoteStyle.GUILLEMETS_REVERSED

    def test_low_high_9_9_german_style(self):
        assert detect_quote_style("Er sagte „Hallo“ zu mir.") == QuoteStyle.LOW_HIGH_9_9

    def test_low_high_9_0_polish_style(self):
        assert detect_quote_style("Powiedział „Cześć” do mnie.") == QuoteStyle.LOW_HIGH_9_0

    def test_cjk_corner_brackets(self):
        assert detect_quote_style("彼は「こんにちは」と言った。") == QuoteStyle.CJK_CORNER

    def test_no_quotes_returns_none(self):
        assert detect_quote_style("No quotes in this sentence at all.") is None

    def test_empty_string_returns_none(self):
        assert detect_quote_style("") is None

    def test_none_returns_none(self):
        assert detect_quote_style(None) is None

    def test_two_conflicting_double_styles_is_ambiguous(self):
        text = 'He said "hello" and she said «bonjour».'
        assert detect_quote_style(text) is None


class TestDetectQuoteStyleSingleQuotes:
    def test_straight_single_quotes_when_no_double_present(self):
        assert detect_quote_style("He said 'hi' to me.") == QuoteStyle.STRAIGHT

    def test_curly_single_quotes(self):
        assert detect_quote_style("She said ‘hi’ to me.") == QuoteStyle.CURLY

    def test_straight_double_and_single_pairs_together_are_still_just_straight(self):
        # Double and single forms of the same style are the same evidence, not two signals to
        # reconcile -- both map to QuoteStyle.STRAIGHT, so this is unambiguous.
        text = 'He said "hello" and also \'hi\' there.'
        assert detect_quote_style(text) == QuoteStyle.STRAIGHT

    def test_double_and_single_pairs_of_different_styles_is_ambiguous(self):
        # A straight double pair and a curly single pair point to two different styles, so this
        # is genuinely mixed and neither form should silently win over the other.
        text = "He said \"hello\" and also ‘hi’ there."
        assert detect_quote_style(text) is None

    def test_contraction_alone_is_not_a_quote(self):
        assert detect_quote_style("Don't do that.") is None

    def test_possessive_alone_is_not_a_quote(self):
        assert detect_quote_style("The cats' toys were everywhere.") is None

    def test_real_single_quote_pair_detected_despite_nearby_contractions(self):
        text = "Don't use 'quotes' carelessly, don't."
        assert detect_quote_style(text) == QuoteStyle.STRAIGHT


class TestDefaultValidQuoteStyle:
    def test_german_defaults_to_low_high_9_9(self):
        assert default_valid_quote_style("de") == QuoteStyle.LOW_HIGH_9_9

    def test_locale_variant_is_normalized(self):
        assert default_valid_quote_style("de-DE") == QuoteStyle.LOW_HIGH_9_9
        assert default_valid_quote_style("de_DE") == QuoteStyle.LOW_HIGH_9_9

    def test_french_defaults_to_guillemets(self):
        assert default_valid_quote_style("fr") == QuoteStyle.GUILLEMETS

    def test_spanish_defaults_to_guillemets(self):
        # Real Academia Espanola prescribes comillas angulares («») as the primary quotation
        # mark, with "" / '' reserved for quotes nested inside a guillemet-quoted span.
        assert default_valid_quote_style("es") == QuoteStyle.GUILLEMETS

    def test_japanese_defaults_to_cjk_corner(self):
        assert default_valid_quote_style("ja") == QuoteStyle.CJK_CORNER

    def test_polish_defaults_to_low_high_9_0(self):
        assert default_valid_quote_style("pl") == QuoteStyle.LOW_HIGH_9_0

    def test_uncurated_language_returns_none(self):
        assert default_valid_quote_style("it") is None

    def test_empty_locale_returns_none(self):
        assert default_valid_quote_style("") is None


class TestComputeDominantQuoteStyleByLocale:
    def _group(self, msgid: str, values: dict) -> TranslationGroup:
        g = TranslationGroup(msgid, is_in_base=True)
        g.default_locale = "en"
        for locale, text in values.items():
            g.add_translation(locale, text)
        return g

    def test_majority_style_wins(self):
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "de": f'Sagt "Hallo Nr {i}".'})
            groups[g.key] = g
        outlier = self._group("key.outlier", {"en": "hi", "de": "Sagt „Hallo“."})
        groups[outlier.key] = outlier

        dominant = compute_dominant_quote_style_by_locale(groups, ["en", "de"], "en")
        assert dominant["de"] == QuoteStyle.STRAIGHT

    def test_locale_with_no_quotes_anywhere_is_omitted(self):
        g = self._group("key.a", {"en": "hi", "fr": "Bonjour, pas de guillemets ici."})
        dominant = compute_dominant_quote_style_by_locale({g.key: g}, ["en", "fr"], "en")
        assert "fr" not in dominant

    def test_default_locale_excluded_from_counting(self):
        # Default locale text uses straight quotes but must not be counted toward "de".
        g = self._group("key.a", {"en": '"hello"', "de": "Sagt „Hallo“."})
        dominant = compute_dominant_quote_style_by_locale({g.key: g}, ["en", "de"], "en")
        assert dominant["de"] == QuoteStyle.LOW_HIGH_9_9
