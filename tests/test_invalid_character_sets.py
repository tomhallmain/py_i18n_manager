import sys
import types
import unittest

if "polib" not in sys.modules:
    fake_polib = types.ModuleType("polib")

    class _POEntry:
        pass

    fake_polib.POEntry = _POEntry
    sys.modules["polib"] = fake_polib

from i18n.translation_group import TranslationGroup
from i18n.invalid_character_set import (
    InvalidCharacterSetAnalyzer,
)
from test_utils import get_default_script_ignore_patterns


class TestInvalidCharacterSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.default_ignore_patterns = get_default_script_ignore_patterns()

    def test_analyzer_accepts_expanded_language_family_samples(self):
        accepted_cases = [
            ("ru", "Привет мир"),
            ("mn", "Сайн байна уу"),
            ("el", "Καλημέρα κόσμε"),
            ("he", "שלום עולם"),
            ("ar", "مرحبا بالعالم"),
            ("ur", "اسلام علیکم دنیا"),
            ("fa", "سلام دنیا"),
            ("hi", "नमस्ते दुनिया"),
            ("mr", "नमस्कार जग"),
            ("ne", "नमस्ते संसार"),
            ("bn", "হ্যালো বিশ্ব"),
            ("as", "হেল্ল' বিশ্ব"),
            ("pa", "ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਦੁਨੀਆ"),
            ("gu", "હેલો વિશ્વ"),
            ("or", "ନମସ୍କାର ବିଶ୍ୱ"),
            ("ta", "வணக்கம் உலகம்"),
            ("te", "హలో వరల్డ్"),
            ("kn", "ಹಲೋ ವಿಶ್ವ"),
            ("ml", "ഹലോ ലോകം"),
            ("si", "හෙලෝ ලෝකය"),
            ("th", "สวัสดีโลก"),
            ("lo", "ສະບາຍດີໂລກ"),
            ("km", "សួស្តីពិភពលោក"),
            ("my", "မင်္ဂလာပါ ကမ္ဘာ"),
            ("ka", "გამარჯობა მსოფლიო"),
            ("hy", "Բարեւ աշխարհ"),
            ("ja", "こんにちは世界"),
            ("zh", "你好世界"),
            ("ko", "안녕하세요 세계"),
            ("vi", "Xin chao the gioi"),
        ]
        for locale, text in accepted_cases:
            with self.subTest(locale=locale):
                self.assertFalse(InvalidCharacterSetAnalyzer.analyze_locale(locale, text))

    def test_analyzer_flags_expanded_language_family_mismatches(self):
        mismatched_cases = [
            ("mn", "مرحبا بالعالم"),
            ("fa", "שלום עולם"),
            ("hi", "Καλημέρα κόσμε"),
            ("mr", "שלום עולם"),
            ("ne", "สวัสดีโลก"),
            ("bn", "Привет мир"),
            ("as", "مرحبا بالعالم"),
            ("pa", "שלום עולם"),
            ("gu", "こんにちは世界"),
            ("or", "Привет мир"),
            ("ta", "שלום עולם"),
            ("te", "Καλημέρα κόσμε"),
            ("kn", "Привет мир"),
            ("ml", "مرحبا بالعالم"),
            ("si", "Καλημέρα κόσμε"),
            ("lo", "שלום עולם"),
            ("km", "Привет мир"),
            ("my", "שלום עולם"),
            ("ka", "مرحبا بالعالم"),
            ("hy", "สวัสดีโลก"),
        ]
        for locale, text in mismatched_cases:
            with self.subTest(locale=locale):
                self.assertTrue(InvalidCharacterSetAnalyzer.analyze_locale(locale, text))

    def test_analyzer_accepts_russian_cyrillic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "Привет мир",
        )
        self.assertFalse(has_issue)

    def test_analyzer_flags_russian_locale_with_greek_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "Καλημέρα κόσμε",
        )
        self.assertTrue(has_issue)

    def test_analyzer_accepts_greek_text_for_greek_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "el",
            "Καλημέρα κόσμε",
        )
        self.assertFalse(has_issue)

    def test_analyzer_flags_greek_locale_with_hebrew_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "el",
            "שלום עולם",
        )
        self.assertTrue(has_issue)

    def test_analyzer_accepts_hebrew_text_for_hebrew_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "he",
            "שלום עולם",
        )
        self.assertFalse(has_issue)

    def test_analyzer_flags_hebrew_locale_with_arabic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "he",
            "مرحبا بالعالم",
        )
        self.assertTrue(has_issue)

    def test_analyzer_accepts_arabic_text_for_arabic_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ar",
            "مرحبا بالعالم",
        )
        self.assertFalse(has_issue)

    def test_analyzer_accepts_arabic_script_for_urdu_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ur",
            "اسلام علیکم دنیا",
        )
        self.assertFalse(has_issue)

    def test_analyzer_flags_urdu_locale_with_cyrillic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ur",
            "Привет мир",
        )
        self.assertTrue(has_issue)

    def test_analyzer_accepts_thai_text_for_thai_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "th",
            "สวัสดีโลก",
        )
        self.assertFalse(has_issue)

    def test_analyzer_flags_thai_locale_with_greek_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "th",
            "Καλημέρα κόσμε",
        )
        self.assertTrue(has_issue)

    def test_analyzer_accepts_vietnamese_latin_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "vi",
            "Xin chao the gioi va chuc mung nam moi",
        )
        self.assertFalse(has_issue)

    def test_analyzer_flags_vietnamese_locale_with_arabic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "vi",
            "مرحبا بالعالم",
        )
        self.assertTrue(has_issue)

    def test_analyzer_accepts_japanese_locale_with_han_only_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja",
            "世界設定翻訳",
        )
        self.assertFalse(has_issue)

    def test_analyzer_accepts_japanese_locale_with_kana_and_han(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja",
            "こんにちは世界",
        )
        self.assertFalse(has_issue)

    def test_analyzer_accepts_chinese_locale_with_han_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "zh",
            "你好世界",
        )
        self.assertFalse(has_issue)

    def test_analyzer_flags_chinese_locale_with_katakana_heavy_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "zh",
            "カタカナテキスト",
        )
        self.assertTrue(has_issue)

    def test_analyzer_ignores_placeholder_only_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "de",
            "%{count} %(name)s %2$s {0}",
        )
        self.assertFalse(has_issue)

    def test_analyzer_ignores_markup_and_placeholders(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja",
            "<b>%{count}</b> こんにちは %{name}",
        )
        self.assertFalse(has_issue)

    def test_analyzer_still_flags_real_mismatch_with_placeholders(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "%{count} Καλημέρα %{name}",
        )
        self.assertTrue(has_issue)

    def test_analyzer_allows_token_list_after_ignore_patterns(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "CSV HTML JSON",
            ignore_patterns=(r"(?i)\bCSV\b", r"(?i)\bHTML\b", r"(?i)\bJSON\b"),
        )
        self.assertFalse(has_issue)

    def test_analyzer_allows_key_combo_after_ignore_patterns(self):
        text = "Ctrl+Shift+P"
        self.assertTrue(InvalidCharacterSetAnalyzer.analyze_locale("ru", text))
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        self.assertFalse(has_issue)

    def test_analyzer_allows_ok_style_acronyms_after_ignore_patterns(self):
        text = "OK FAQ ETA"
        self.assertTrue(InvalidCharacterSetAnalyzer.analyze_locale("ru", text))
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        self.assertFalse(has_issue)

    def test_analyzer_allows_common_file_extensions_after_ignore_patterns(self):
        text = ".json .zip .csv"
        self.assertTrue(InvalidCharacterSetAnalyzer.analyze_locale("ru", text))
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        self.assertFalse(has_issue)

    def test_flags_latin_locale_when_non_latin_letters_dominate(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("fr", "Привет мир")  # non-Latin in a Latin-script locale

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        self.assertIn("fr", invalid)

    def test_does_not_flag_non_latin_script_locale(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ru", "Привет мир")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        self.assertNotIn("ru", invalid)

    def test_does_not_flag_when_non_latin_ratio_is_below_threshold(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("fr", "Version 2 Привет")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=80)
        self.assertNotIn("fr", invalid)

    def test_flags_non_cjk_locale_when_cjk_dominate(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("de", "こんにちは世界")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        self.assertIn("de", invalid)

    def test_flags_korean_locale_when_non_korean_cjk_dominate(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ko", "こんにちは世界")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        self.assertIn("ko", invalid)

    def test_does_not_flag_korean_locale_when_hangul_dominates(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ko", "안녕하세요 세계")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        self.assertNotIn("ko", invalid)

    def test_group_invalid_translations_includes_character_set_result(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("de", "こんにちは")  # non-Latin in Latin-script locale

        invalid_locales = group.get_invalid_translations(locales=["en", "de"])
        self.assertIn("de", invalid_locales.invalid_character_set_locales)

    def test_group_character_set_respects_ignore_patterns(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ru", "CSV HTML JSON")

        invalid = group.get_invalid_character_set_locales(
            threshold_percentage=40,
            ignore_patterns=(r"(?i)\bCSV\b", r"(?i)\bHTML\b", r"(?i)\bJSON\b"),
        )
        self.assertNotIn("ru", invalid)

    def test_group_character_set_respects_key_combo_ignore_pattern(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ru", "Cmd+Shift+P")

        invalid = group.get_invalid_character_set_locales(
            threshold_percentage=40,
            ignore_patterns=self.default_ignore_patterns,
        )
        self.assertNotIn("ru", invalid)

    def test_find_invalid_locales_with_mixed_locale_matrix(self):
        values = {
            "ru": "Привет мир",
            "el": "Καλημέρα κόσμε",
            "he": "שלום עולם",
            "ar": "مرحبا بالعالم",
            "ur": "اسلام علیکم دنیا",
            "ja": "こんにちは世界",
            "zh": "你好世界",
            "th": "สวัสดีโลก",
            "vi": "Xin chao the gioi",
            "de": "こんにちは",
            "ko": "こんにちは世界",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)

        # Good-matches should stay clean.
        for locale in ("ru", "el", "he", "ar", "ur", "ja", "zh", "th", "vi"):
            self.assertNotIn(locale, invalid)
        # Known mismatches should be flagged.
        self.assertIn("de", invalid)  # CJK-heavy text in non-CJK locale
        self.assertIn("ko", invalid)  # Korean locale with non-Korean CJK-heavy text


if __name__ == "__main__":
    unittest.main()
