import unittest

from i18n.stop_character_utils import (
    SentenceEndingKind,
    normalize_translation_trailing_stop,
    preferred_sentence_ending_for_locale,
    preferred_trailing_sentence_stop_for_locale,
    source_has_trailing_sentence_stop,
    translation_has_stop_inconsistency_vs_source,
)


class TestTrailingSentenceStopHelpers(unittest.TestCase):
    def test_source_has_trailing_sentence_stop_ascii(self):
        self.assertFalse(source_has_trailing_sentence_stop("Hello"))
        self.assertTrue(source_has_trailing_sentence_stop("Hello."))
        self.assertTrue(source_has_trailing_sentence_stop("  Hello.  "))
        self.assertTrue(source_has_trailing_sentence_stop("Really?"))
        self.assertTrue(source_has_trailing_sentence_stop("Go!"))

    def test_source_has_trailing_sentence_stop_cjk(self):
        self.assertTrue(source_has_trailing_sentence_stop("你好。"))
        self.assertTrue(source_has_trailing_sentence_stop("ｔｅｓｔ．"))  # fullwidth .

    def test_preferred_stop_cjk_vs_latin_locale(self):
        self.assertEqual(preferred_trailing_sentence_stop_for_locale("zh_CN"), "。")
        self.assertEqual(preferred_trailing_sentence_stop_for_locale("ja"), "。")
        self.assertEqual(preferred_trailing_sentence_stop_for_locale("de"), ".")

    def test_preferred_korean_uses_ascii_not_ideographic_full_stop(self):
        """Korean UI copy typically uses ASCII . ? ! rather than 。／？／！."""
        self.assertEqual(preferred_trailing_sentence_stop_for_locale("ko"), ".")
        self.assertEqual(preferred_trailing_sentence_stop_for_locale("ko_KR"), ".")
        self.assertEqual(
            normalize_translation_trailing_stop("Go.", "가", "ko_KR"),
            "가.",
        )

    def test_preferred_arabic_script_uses_arabic_question_mark(self):
        """Arabic question mark U+061F is preferred for ``ar``; we still append in *logical* string order.

        In RTL paragraphs the glyph appears on the visually *left* edge (sentence end), but Unicode
        stores Arabic in logical order: the sentence-final punctuation is the *last* code unit in the
        string—the same convention as gettext/ICU and our trailing-punctuation helpers.
        """
        self.assertEqual(
            preferred_sentence_ending_for_locale(SentenceEndingKind.QUESTION, "ar"),
            "\u061f",
        )
        out = normalize_translation_trailing_stop("Really?", "حقا", "ar")
        self.assertEqual(out, "حقا\u061f")
        self.assertTrue(out.endswith("\u061f"), "Sentence-final ؟ is last in logical order, not prepended")

    def test_normalize_keeps_locale_preferred_when_source_has_stop(self):
        self.assertEqual(
            normalize_translation_trailing_stop("Source.", "Ziel.", "de"),
            "Ziel.",
        )
        self.assertEqual(
            normalize_translation_trailing_stop("Source.", "Ziel。", "de"),
            "Ziel.",
        )

    def test_normalize_appends_stop_when_source_has_stop_but_translation_lacks(self):
        self.assertEqual(
            normalize_translation_trailing_stop("Go.", "Geh", "de"),
            "Geh.",
        )
        self.assertEqual(
            normalize_translation_trailing_stop("Go.", "走", "zh_CN"),
            "走。",
        )

    def test_normalize_strips_trailing_stops_when_source_has_none(self):
        self.assertEqual(
            normalize_translation_trailing_stop("Title", "Titel.", "de"),
            "Titel",
        )
        self.assertEqual(
            normalize_translation_trailing_stop("Title", "Titel。。。", "de"),
            "Titel",
        )
        self.assertEqual(
            normalize_translation_trailing_stop("Title", "  Titel.  ", "de"),
            "  Titel",
        )

    def test_normalize_preserves_leading_whitespace(self):
        self.assertEqual(
            normalize_translation_trailing_stop("x", "  y.  ", "de"),
            "  y",
        )

    def test_normalize_empty_translation_when_source_has_stop(self):
        self.assertEqual(normalize_translation_trailing_stop("A.", "", "de"), "")

    def test_normalize_question_and_exclamation(self):
        self.assertEqual(
            normalize_translation_trailing_stop("Really?", "Wirklich", "de"),
            "Wirklich?",
        )
        self.assertEqual(
            normalize_translation_trailing_stop("Go!", "Los", "de"),
            "Los!",
        )
        self.assertEqual(
            normalize_translation_trailing_stop("Really?", "真的", "zh_CN"),
            "真的？",
        )
        self.assertEqual(
            normalize_translation_trailing_stop("Really!", "真的", "zh_CN"),
            "真的！",
        )

    def test_normalize_strips_question_when_source_has_none(self):
        self.assertEqual(
            normalize_translation_trailing_stop("Title", "Titel?", "de"),
            "Titel",
        )

    def test_translation_has_stop_inconsistency_vs_source(self):
        self.assertTrue(
            translation_has_stop_inconsistency_vs_source("Save", "Speichern.", "de")
        )
        self.assertTrue(
            translation_has_stop_inconsistency_vs_source("Save", "保存。", "de")
        )
        self.assertTrue(
            translation_has_stop_inconsistency_vs_source("Save.", "Speichern", "de")
        )
        self.assertTrue(
            translation_has_stop_inconsistency_vs_source("Save.", "Speichern。", "de")
        )
        self.assertTrue(
            translation_has_stop_inconsistency_vs_source("Save.", "Hallo.", "zh_CN")
        )
        self.assertFalse(
            translation_has_stop_inconsistency_vs_source("Save.", "Speichern.", "de")
        )
        self.assertFalse(
            translation_has_stop_inconsistency_vs_source("Save.", "保存。", "zh_CN")
        )
        self.assertFalse(
            translation_has_stop_inconsistency_vs_source("", "Only.", "de")
        )
        self.assertFalse(
            translation_has_stop_inconsistency_vs_source("Save", "Speichern", "de")
        )


if __name__ == "__main__":
    unittest.main()
