"""Tests for :class:`PlaceholderSignature` and :meth:`TranslationGroup.get_invalid_index_locales`.

Covers all placeholder formats parsed by PlaceholderSignature:
  - Indexed curly braces: {0}, {1}, …
  - Named curly braces:   {name}, {var}
  - Ruby named:           %{name}
  - Printf positional:    %s, %d, %f, …
  - Printf named:         %(name)s, %(count)d, …
  - Ruby interpolation:   #{name}  (always invalid in i18n strings)
  - Malformed ruby named: %{} / %{123}
"""

import unittest

from i18n.translation_group import PlaceholderSignature, TranslationGroup


# ---------------------------------------------------------------------------
# PlaceholderSignature.from_text — parsing unit tests
# ---------------------------------------------------------------------------

class TestPlaceholderSignatureParsing(unittest.TestCase):

    # -- indexed {0} ---------------------------------------------------------

    def test_indexed_single(self):
        sig = PlaceholderSignature.from_text("Hello {0}")
        self.assertEqual(sig.indexed, (0,))

    def test_indexed_multiple_sorted(self):
        sig = PlaceholderSignature.from_text("{1} and {0} and {2}")
        self.assertEqual(sig.indexed, (0, 1, 2))

    def test_indexed_duplicate_preserved(self):
        # Same index twice — both occurrences are kept (sorted, not deduplicated)
        sig = PlaceholderSignature.from_text("{0} then {0} again")
        self.assertEqual(sig.indexed, (0, 0))

    def test_escaped_double_braces_not_indexed(self):
        sig = PlaceholderSignature.from_text("100%% done {{0}}")
        self.assertEqual(sig.indexed, ())

    # -- named curly braces {name} -------------------------------------------

    def test_brace_named_single(self):
        sig = PlaceholderSignature.from_text("Hello {name}")
        self.assertEqual(sig.brace_named, ("name",))

    def test_brace_named_multiple_sorted(self):
        sig = PlaceholderSignature.from_text("{count} items for {user}")
        self.assertEqual(sig.brace_named, ("count", "user"))

    def test_brace_named_not_confused_with_indexed(self):
        sig = PlaceholderSignature.from_text("{0} and {name}")
        self.assertEqual(sig.indexed, (0,))
        self.assertEqual(sig.brace_named, ("name",))

    # -- ruby named %{name} --------------------------------------------------

    def test_ruby_named_single(self):
        sig = PlaceholderSignature.from_text("Hello %{name}")
        self.assertEqual(sig.ruby_named, ("name",))

    def test_ruby_named_multiple_sorted(self):
        sig = PlaceholderSignature.from_text("%{count} items for %{user}")
        self.assertEqual(sig.ruby_named, ("count", "user"))

    def test_ruby_named_malformed_empty_braces(self):
        sig = PlaceholderSignature.from_text("%{}")
        self.assertTrue(sig.has_malformed_ruby_named)

    def test_ruby_named_malformed_numeric_key(self):
        sig = PlaceholderSignature.from_text("%{123}")
        self.assertTrue(sig.has_malformed_ruby_named)

    def test_ruby_named_well_formed_not_malformed(self):
        sig = PlaceholderSignature.from_text("%{count}")
        self.assertFalse(sig.has_malformed_ruby_named)

    # -- printf positional %s / %d / etc. ------------------------------------

    def test_printf_positional_s(self):
        sig = PlaceholderSignature.from_text("Hello %s")
        self.assertEqual(sig.printf_positional_count, 1)

    def test_printf_positional_d(self):
        sig = PlaceholderSignature.from_text("Found %d items")
        self.assertEqual(sig.printf_positional_count, 1)

    def test_printf_positional_multiple(self):
        sig = PlaceholderSignature.from_text("%s has %d items")
        self.assertEqual(sig.printf_positional_count, 2)

    def test_printf_positional_float(self):
        sig = PlaceholderSignature.from_text("Value: %.2f")
        self.assertEqual(sig.printf_positional_count, 1)

    def test_printf_positional_zero_when_none(self):
        sig = PlaceholderSignature.from_text("No placeholders here")
        self.assertEqual(sig.printf_positional_count, 0)

    def test_printf_positional_not_triggered_by_word_boundary(self):
        # "100% de" — percent followed by a word char should NOT match
        sig = PlaceholderSignature.from_text("100% de réduction")
        self.assertEqual(sig.printf_positional_count, 0)

    def test_printf_positional_not_triggered_by_double_percent(self):
        sig = PlaceholderSignature.from_text("50%% off")
        self.assertEqual(sig.printf_positional_count, 0)

    # -- printf named %(name)s -----------------------------------------------

    def test_printf_named_single(self):
        sig = PlaceholderSignature.from_text("Hello %(name)s")
        self.assertEqual(sig.printf_named, ("name",))

    def test_printf_named_multiple_sorted(self):
        sig = PlaceholderSignature.from_text("%(count)d of %(total)d")
        self.assertEqual(sig.printf_named, ("count", "total"))

    def test_printf_named_not_confused_with_ruby_named(self):
        sig = PlaceholderSignature.from_text("%{ruby} %(py)s")
        self.assertEqual(sig.ruby_named, ("ruby",))
        self.assertEqual(sig.printf_named, ("py",))

    # -- ruby interpolation #{name} ------------------------------------------

    def test_ruby_interpolation_detected(self):
        sig = PlaceholderSignature.from_text("Hello #{name}")
        self.assertEqual(sig.ruby_interpolation, ("name",))

    def test_ruby_interpolation_multiple(self):
        sig = PlaceholderSignature.from_text("#{a} and #{b}")
        self.assertEqual(sig.ruby_interpolation, ("a", "b"))

    def test_ruby_interpolation_absent(self):
        sig = PlaceholderSignature.from_text("No interpolation here")
        self.assertEqual(sig.ruby_interpolation, ())

    # -- empty / None input --------------------------------------------------

    def test_empty_string_returns_empty_signature(self):
        sig = PlaceholderSignature.from_text("")
        self.assertEqual(sig, PlaceholderSignature())

    def test_none_returns_empty_signature(self):
        sig = PlaceholderSignature.from_text(None)
        self.assertEqual(sig, PlaceholderSignature())


# ---------------------------------------------------------------------------
# PlaceholderSignature.matches / is_invalid_for — compatibility unit tests
# ---------------------------------------------------------------------------

class TestPlaceholderSignatureMatching(unittest.TestCase):

    def test_identical_signatures_match(self):
        a = PlaceholderSignature.from_text("{0} %s %{name}")
        self.assertTrue(a.matches(a))

    def test_different_indexed_do_not_match(self):
        a = PlaceholderSignature.from_text("{0}")
        b = PlaceholderSignature.from_text("{0} {1}")
        self.assertFalse(a.matches(b))

    def test_different_printf_count_do_not_match(self):
        a = PlaceholderSignature.from_text("%s")
        b = PlaceholderSignature.from_text("%s %d")
        self.assertFalse(a.matches(b))

    def test_different_printf_named_do_not_match(self):
        a = PlaceholderSignature.from_text("%(name)s")
        b = PlaceholderSignature.from_text("%(user)s")
        self.assertFalse(a.matches(b))

    def test_ruby_interpolation_is_invalid_regardless_of_match(self):
        ref = PlaceholderSignature.from_text("Hello #{name}")
        sig = PlaceholderSignature.from_text("Hello #{name}")
        # Even if they match structurally, ruby interpolation is always invalid
        self.assertTrue(sig.is_invalid_for(ref))

    def test_malformed_ruby_named_is_invalid(self):
        ref = PlaceholderSignature.from_text("%{name}")
        sig = PlaceholderSignature.from_text("%{}")
        self.assertTrue(sig.is_invalid_for(ref))

    def test_valid_signatures_not_invalid_for_each_other(self):
        ref = PlaceholderSignature.from_text("Hello %{name}, you have %d messages")
        sig = PlaceholderSignature.from_text("Bonjour %{name}, vous avez %d messages")
        self.assertFalse(sig.is_invalid_for(ref))


# ---------------------------------------------------------------------------
# TranslationGroup.get_invalid_index_locales — integration tests
# ---------------------------------------------------------------------------

class TestGetInvalidIndexLocales(unittest.TestCase):

    def _make_group(self, en_text, translations: dict) -> TranslationGroup:
        g = TranslationGroup(en_text)
        g.default_locale = "en"
        g.add_translation("en", en_text)
        for locale, text in translations.items():
            g.add_translation(locale, text)
        return g

    # -- indexed {0} ---------------------------------------------------------

    def test_indexed_missing_in_translation_is_invalid(self):
        g = self._make_group("Item {0} of {1}", {"fr": "Élément de"})
        self.assertIn("fr", g.get_invalid_index_locales())

    def test_indexed_present_in_translation_is_valid(self):
        g = self._make_group("Item {0} of {1}", {"fr": "Élément {0} sur {1}"})
        self.assertNotIn("fr", g.get_invalid_index_locales())

    def test_indexed_extra_in_translation_is_invalid(self):
        g = self._make_group("Item {0}", {"fr": "Élément {0} sur {1}"})
        self.assertIn("fr", g.get_invalid_index_locales())

    # -- named curly braces {name} -------------------------------------------

    def test_brace_named_missing_in_translation_is_invalid(self):
        g = self._make_group("Hello {name}", {"de": "Hallo"})
        self.assertIn("de", g.get_invalid_index_locales())

    def test_brace_named_present_in_translation_is_valid(self):
        g = self._make_group("Hello {name}", {"de": "Hallo {name}"})
        self.assertNotIn("de", g.get_invalid_index_locales())

    def test_brace_named_different_name_is_invalid(self):
        g = self._make_group("Hello {name}", {"de": "Hallo {user}"})
        self.assertIn("de", g.get_invalid_index_locales())

    # -- ruby named %{name} --------------------------------------------------

    def test_ruby_named_missing_in_translation_is_invalid(self):
        g = self._make_group("%{count} items", {"es": "artículos"})
        self.assertIn("es", g.get_invalid_index_locales())

    def test_ruby_named_present_in_translation_is_valid(self):
        g = self._make_group("%{count} items", {"es": "%{count} artículos"})
        self.assertNotIn("es", g.get_invalid_index_locales())

    def test_ruby_named_malformed_in_translation_is_invalid(self):
        g = self._make_group("%{count} items", {"es": "%{} artículos"})
        self.assertIn("es", g.get_invalid_index_locales())

    # -- printf positional %s / %d -------------------------------------------

    def test_printf_s_missing_in_translation_is_invalid(self):
        g = self._make_group("Hello %s", {"fr": "Bonjour"})
        self.assertIn("fr", g.get_invalid_index_locales())

    def test_printf_s_present_in_translation_is_valid(self):
        g = self._make_group("Hello %s", {"fr": "Bonjour %s"})
        self.assertNotIn("fr", g.get_invalid_index_locales())

    def test_printf_d_missing_in_translation_is_invalid(self):
        g = self._make_group("Found %d results", {"de": "Ergebnisse gefunden"})
        self.assertIn("de", g.get_invalid_index_locales())

    def test_printf_count_mismatch_is_invalid(self):
        g = self._make_group("%s has %d items", {"ja": "%s のアイテム"})
        self.assertIn("ja", g.get_invalid_index_locales())

    def test_printf_count_matches_is_valid(self):
        g = self._make_group("%s has %d items", {"ja": "%s は %d 個のアイテムがあります"})
        self.assertNotIn("ja", g.get_invalid_index_locales())

    def test_printf_word_boundary_not_false_positive(self):
        # "100% de" should not count as a %d token
        g = self._make_group("100% done", {"fr": "100% terminé"})
        self.assertNotIn("fr", g.get_invalid_index_locales())

    def test_printf_no_placeholders_in_default_is_valid(self):
        g = self._make_group("Save 50% today", {"fr": "Économisez 50% aujourd'hui"})
        self.assertNotIn("fr", g.get_invalid_index_locales())

    # -- printf named %(name)s -----------------------------------------------

    def test_printf_named_missing_in_translation_is_invalid(self):
        g = self._make_group("Hello %(name)s", {"fr": "Bonjour"})
        self.assertIn("fr", g.get_invalid_index_locales())

    def test_printf_named_present_in_translation_is_valid(self):
        g = self._make_group("Hello %(name)s", {"fr": "Bonjour %(name)s"})
        self.assertNotIn("fr", g.get_invalid_index_locales())

    def test_printf_named_wrong_key_is_invalid(self):
        g = self._make_group("%(count)d items", {"fr": "%(total)d éléments"})
        self.assertIn("fr", g.get_invalid_index_locales())

    # -- ruby interpolation #{name} ------------------------------------------

    def test_ruby_interpolation_in_translation_is_invalid(self):
        g = self._make_group("Hello %{name}", {"fr": "Bonjour #{name}"})
        self.assertIn("fr", g.get_invalid_index_locales())

    # -- default locale excluded ---------------------------------------------

    def test_default_locale_never_flagged(self):
        g = self._make_group("Hello %s", {})
        self.assertNotIn("en", g.get_invalid_index_locales())

    # -- no placeholders anywhere --------------------------------------------

    def test_no_placeholders_all_valid(self):
        g = self._make_group("Simple string", {"fr": "Chaîne simple", "de": "Einfache Zeichenkette"})
        self.assertEqual(g.get_invalid_index_locales(), [])


if __name__ == "__main__":
    unittest.main()
