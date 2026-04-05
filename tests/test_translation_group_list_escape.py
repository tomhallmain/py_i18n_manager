"""Tests for list-valued translations: escaped/unescaped apply per element."""

import unittest

from i18n.translation_group import TranslationGroup, escape_unicode, unescape_unicode


class TestTranslationGroupListEscape(unittest.TestCase):
    def test_escaped_applies_escape_unicode_to_each_element(self):
        g = TranslationGroup("home.features", is_in_base=True)
        g.add_translation("en", ["café", "naïve"])
        out = g.get_translation_escaped("en")
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], escape_unicode("café"))
        self.assertEqual(out[1], escape_unicode("naïve"))

    def test_unescaped_applies_unescape_to_each_element(self):
        g = TranslationGroup("k", is_in_base=True)
        g.add_translation("en", [r"caf\u00e9", "x"])
        out = g.get_translation_unescaped("en")
        self.assertIsInstance(out, list)
        self.assertEqual(out[0], unescape_unicode(r"caf\u00e9"))
        self.assertEqual(out[1], "x")


if __name__ == "__main__":
    unittest.main()
