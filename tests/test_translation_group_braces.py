"""Tests for :meth:`TranslationGroup.get_invalid_brace_locales`."""

import unittest

from i18n.translation_group import TranslationGroup


class TestInvalidBraceLocales(unittest.TestCase):
    def test_full_string_parenthetical_dropped_in_translation_is_invalid(self):
        """When the default is entirely wrapped in ``()``, the translation must be too."""
        g = TranslationGroup("(Unable to parse image prompt information for this file.)")
        g.default_locale = "en"
        g.add_translation(
            "en",
            "(Unable to parse image prompt information for this file.)",
        )
        g.add_translation(
            "fr",
            "Impossible de traiter les informations de la promesse d'image pour ce fichier.",
        )
        self.assertIn("fr", g.get_invalid_brace_locales())

    def test_full_string_parenthetical_ok_when_translation_also_wrapped(self):
        g = TranslationGroup("(Unable to parse image prompt information for this file.)")
        g.default_locale = "en"
        g.add_translation(
            "en",
            "(Unable to parse image prompt information for this file.)",
        )
        g.add_translation(
            "fr",
            "(Impossible de traiter les informations de la promesse d'image pour ce fichier.)",
        )
        self.assertNotIn("fr", g.get_invalid_brace_locales())

    def test_full_string_parenthetical_added_only_in_translation_is_invalid(self):
        """Symmetric: default is not a full parenthetical but translation is."""
        g = TranslationGroup("Status message")
        g.default_locale = "en"
        g.add_translation("en", "Status message")
        g.add_translation("fr", "(Message de statut)")
        self.assertIn("fr", g.get_invalid_brace_locales())

    def test_period_inside_vs_outside_close_paren_both_full_wrap(self):
        """Period before ``)`` (common in EN) vs after ``)`` (common in DE)—both count as full-wrap."""
        g = TranslationGroup(
            "(Open this image as part of a directory to see index details.)"
        )
        g.default_locale = "en"
        g.add_translation(
            "en",
            "(Open this image as part of a directory to see index details.)",
        )
        g.add_translation(
            "de",
            "(Öffnen Sie dieses Bild als Teil eines Verzeichnisses, um Indexdetails zu sehen).",
        )
        self.assertNotIn("de", g.get_invalid_brace_locales())

    def test_cjk_ideographic_period_after_fullwidth_close_paren(self):
        """``）。`` after the closing paren matches EN ``.)`` inside—both full-wrap."""
        g = TranslationGroup(
            "(Open this image as part of a directory to see index details.)"
        )
        g.default_locale = "en"
        g.add_translation(
            "en",
            "(Open this image as part of a directory to see index details.)",
        )
        g.add_translation(
            "ja",
            "(インデックスの詳細を見るには、この画像をディレクトリの一部として開いてください）。",
        )
        self.assertNotIn("ja", g.get_invalid_brace_locales())

    def test_parentheses_loose_when_neither_side_is_full_string_parenthetical(self):
        """Balanced-only: extra or dropped inner parens are allowed if not full-wrap mismatch."""
        g = TranslationGroup("See (details) in the log")
        g.default_locale = "en"
        g.add_translation("en", "See (details) in the log")
        g.add_translation("fr", "Voir les détails dans le journal")
        self.assertNotIn("fr", g.get_invalid_brace_locales())

    def test_curly_braces_still_compared_to_default(self):
        g = TranslationGroup("Hello {name}")
        g.default_locale = "en"
        g.add_translation("en", "Hello {name}")
        g.add_translation("de", "Hallo name")
        self.assertIn("de", g.get_invalid_brace_locales())


if __name__ == "__main__":
    unittest.main()
