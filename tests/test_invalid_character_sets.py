from i18n.translation_group import TranslationGroup
from i18n.invalid_character_set import (
    InvalidCharacterSetAnalyzer,
)
from test_utils import get_default_script_ignore_patterns


class TestInvalidCharacterSet:
    @classmethod
    def setup_class(cls):
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
            assert not InvalidCharacterSetAnalyzer.analyze_locale(locale, text)

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
            assert InvalidCharacterSetAnalyzer.analyze_locale(locale, text)

    def test_analyzer_accepts_russian_cyrillic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "Привет мир",
        )
        assert not has_issue

    def test_analyzer_flags_russian_locale_with_greek_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "Καλημέρα κόσμε",
        )
        assert has_issue

    def test_analyzer_accepts_greek_text_for_greek_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "el",
            "Καλημέρα κόσμε",
        )
        assert not has_issue

    def test_analyzer_flags_greek_locale_with_hebrew_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "el",
            "שלום עולם",
        )
        assert has_issue

    def test_analyzer_accepts_hebrew_text_for_hebrew_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "he",
            "שלום עולם",
        )
        assert not has_issue

    def test_analyzer_flags_hebrew_locale_with_arabic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "he",
            "مرحبا بالعالم",
        )
        assert has_issue

    def test_analyzer_accepts_arabic_text_for_arabic_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ar",
            "مرحبا بالعالم",
        )
        assert not has_issue

    def test_analyzer_accepts_arabic_script_for_urdu_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ur",
            "اسلام علیکم دنیا",
        )
        assert not has_issue

    def test_analyzer_flags_urdu_locale_with_cyrillic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ur",
            "Привет мир",
        )
        assert has_issue

    def test_analyzer_accepts_thai_text_for_thai_locale(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "th",
            "สวัสดีโลก",
        )
        assert not has_issue

    def test_analyzer_flags_thai_locale_with_greek_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "th",
            "Καλημέρα κόσμε",
        )
        assert has_issue

    def test_analyzer_accepts_vietnamese_latin_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "vi",
            "Xin chao the gioi va chuc mung nam moi",
        )
        assert not has_issue

    def test_analyzer_flags_vietnamese_locale_with_arabic_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "vi",
            "مرحبا بالعالم",
        )
        assert has_issue

    def test_analyzer_accepts_japanese_locale_with_han_only_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja",
            "世界設定翻訳",
        )
        assert not has_issue

    def test_analyzer_accepts_japanese_locale_with_kana_and_han(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja",
            "こんにちは世界",
        )
        assert not has_issue

    def test_analyzer_accepts_chinese_locale_with_han_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "zh",
            "你好世界",
        )
        assert not has_issue

    def test_analyzer_flags_chinese_locale_with_katakana_heavy_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "zh",
            "カタカナテキスト",
        )
        assert has_issue

    def test_analyzer_ignores_placeholder_only_text(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "de",
            "%{count} %(name)s %2$s {0}",
        )
        assert not has_issue

    def test_analyzer_ignores_markup_and_placeholders(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja",
            "<b>%{count}</b> こんにちは %{name}",
        )
        assert not has_issue

    def test_analyzer_still_flags_real_mismatch_with_placeholders(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "%{count} Καλημέρα %{name}",
        )
        assert has_issue

    def test_analyzer_allows_token_list_after_ignore_patterns(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            "CSV HTML JSON",
            ignore_patterns=(r"(?i)\bCSV\b", r"(?i)\bHTML\b", r"(?i)\bJSON\b"),
        )
        assert not has_issue

    def test_analyzer_allows_key_combo_after_ignore_patterns(self):
        text = "Ctrl+Shift+P"
        assert InvalidCharacterSetAnalyzer.analyze_locale("ru", text)
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert not has_issue

    def test_analyzer_allows_ok_style_acronyms_after_ignore_patterns(self):
        text = "OK FAQ ETA"
        assert InvalidCharacterSetAnalyzer.analyze_locale("ru", text)
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert not has_issue

    def test_analyzer_allows_common_file_extensions_after_ignore_patterns(self):
        text = ".json .zip .csv"
        assert InvalidCharacterSetAnalyzer.analyze_locale("ru", text)
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert not has_issue

    def test_analyzer_allows_pdf_gif_terms_after_default_ignore_patterns(self):
        text = "PDF GIF PDFs GIFs"
        assert InvalidCharacterSetAnalyzer.analyze_locale("ru", text)
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert not has_issue

    def test_analyzer_allows_common_media_doc_terms_after_default_ignore_patterns(self):
        text = "PDF PNG JPEG GIF MP4 WAV"
        assert InvalidCharacterSetAnalyzer.analyze_locale("ru", text)
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert not has_issue

    def test_analyzer_allows_common_config_terms_after_default_ignore_patterns(self):
        text = "JSON YAML TOML INI CFG XML CSV"
        assert InvalidCharacterSetAnalyzer.analyze_locale("ru", text)
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert not has_issue

    def test_analyzer_uppercase_term_ignore_does_not_hide_lowercase_plain_tokens(self):
        text = "pdf gif"
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ru",
            text,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert has_issue

    def test_flags_latin_locale_when_non_latin_letters_dominate(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("fr", "Привет мир")  # non-Latin in a Latin-script locale

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        assert "fr" in invalid

    def test_does_not_flag_non_latin_script_locale(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ru", "Привет мир")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        assert "ru" not in invalid

    def test_does_not_flag_when_non_latin_ratio_is_below_threshold(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("fr", "Version 2 Привет")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=80)
        assert "fr" not in invalid

    def test_flags_non_cjk_locale_when_cjk_dominate(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("de", "こんにちは世界")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        assert "de" in invalid

    def test_flags_korean_locale_when_non_korean_cjk_dominate(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ko", "こんにちは世界")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        assert "ko" in invalid

    def test_does_not_flag_korean_locale_when_hangul_dominates(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ko", "안녕하세요 세계")

        invalid = group.get_invalid_character_set_locales(threshold_percentage=40)
        assert "ko" not in invalid

    def test_group_invalid_translations_includes_character_set_result(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("de", "こんにちは")  # non-Latin in Latin-script locale

        invalid_locales = group.get_invalid_translations(locales=["en", "de"])
        assert "de" in invalid_locales.invalid_character_set_locales

    def test_group_character_set_respects_ignore_patterns(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ru", "CSV HTML JSON")

        invalid = group.get_invalid_character_set_locales(
            threshold_percentage=40,
            ignore_patterns=(r"(?i)\bCSV\b", r"(?i)\bHTML\b", r"(?i)\bJSON\b"),
        )
        assert "ru" not in invalid

    def test_group_character_set_respects_key_combo_ignore_pattern(self):
        group = TranslationGroup("sample.key", is_in_base=True)
        group.add_translation("en", "Sample text")
        group.add_translation("ru", "Cmd+Shift+P")

        invalid = group.get_invalid_character_set_locales(
            threshold_percentage=40,
            ignore_patterns=self.default_ignore_patterns,
        )
        assert "ru" not in invalid

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
            assert locale not in invalid
        # Known mismatches should be flagged.
        assert "de" in invalid  # CJK-heavy text in non-CJK locale
        assert "ko" in invalid  # Korean locale with non-Korean CJK-heavy text

    def test_group_shared_token_in_all_locales_is_suppressed_when_scripts_diverse(self):
        values = {
            "de": "LoRA Tags",
            "ru": "Теги LoRA",
            "ja": "LoRAタグ",
            "ko": "LoRA 태그",
            "zh": "LoRA 标签",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        for locale in ("ru", "ja", "ko", "zh"):
            assert locale not in invalid

    def test_group_lora_shared_across_all_locales_is_excluded_from_consideration(self):
        values = {
            "de": "LoRA-Stichworte",
            "es": "Etiquetas LoRA",
            "fr": "Etiquettes LoRA",
            "ja": "LoRAタグ",
            "ko": "LoRA 태그",
            "pt": "Etiquetas LoRA",
            "ru": "Теги LoRA",
            "zh": "LoRA 标签",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_group_ipadapter_shared_across_all_locales_is_excluded_from_consideration(self):
        values = {
            "de": "Dateien IPAdapter",
            "es": "Archivos IPAdapter",
            "fr": "Fichiers IPAdapter",
            "ja": "IPAdapter ファイル",
            "ko": "IPAdapter 파일",
            "pt": "Ficheiros IPAdapter",
            "ru": "Файлы IPAdapter",
            "zh": "IPAdapter 文件",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_group_shared_identifier_file_browser_find_is_excluded(self):
        values = {
            "de": "Der file_browser.find() ist ungueltig.",
            "es": "El file_browser.find() no es valido.",
            "fr": "Le file_browser.find() est invalide.",
            "it": "Il file_browser.find() non e valido.",
            "ja": "file_browser.find()が無効です。",
            "ko": "file_browser.find()이(가) 유효하지 않습니다.",
            "pt": "O file_browser.find() e invalido.",
            "ru": "file_browser.find() недопустим.",
            "zh": "file_browser.find() 无效。",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_group_identical_latin_only_values_are_not_invalid_character_set(self):
        values = {
            "de": "LoRA",
            "es": "LoRA",
            "fr": "LoRA",
            "ja": "LoRA",
            "ko": "LoRA",
            "pt": "LoRA",
            "ru": "LoRA",
            "zh": "LoRA",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_group_uniform_lora_tags_is_not_invalid_when_any_locale_expects_script(self):
        values = {
            "de": "LoRA Tags",
            "ru": "LoRA Tags",
            "ja": "LoRA Tags",
            "ko": "LoRA Tags",
            "zh": "LoRA Tags",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_group_partial_shared_token_does_not_suppress_invalid_locale(self):
        values = {
            "de": "SD Workflows",
            "ru": "SD Workflows",
            "ja": "ワークフローを実行",
            "ko": "SD Workflow",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        # Token is not shared by all locales; invalid findings should remain.
        assert "ru" in invalid
        assert "ko" in invalid

    def test_group_shared_token_still_flags_real_locale_script_mismatch(self):
        values = {
            "de": "SD-Workflows ausfuhren",
            "es": "Ejecutar flujos de trabajo SD",
            "fr": "Executer les flux de travail SD",
            "ja": "SDワークフローを実行",
            "ko": "SDワークフロー 실행",
            "pt": "Executar fluxos de trabalho SD",
            "ru": "Запуск рабочих процессов SD",
            "zh": "运行SD工作流",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        # Shared "SD" token appears in all locales and should be suppressed,
        # but Korean text still contains dominant Japanese script and must remain invalid.
        assert "ko" in invalid

    # --- Uniform non-Latin single-script group suppression ---

    def test_uniform_cyrillic_all_cyrillic_locales_not_flagged(self):
        # A Cyrillic proper noun appearing identically across all Cyrillic-script locales
        # is a quality-review concern (identical values), not a charset concern.
        values = {
            "ru": "Яндекс",
            "uk": "Яндекс",
            "bg": "Яндекс",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_uniform_cyrillic_flags_non_cyrillic_locales(self):
        # When a Latin-script locale is in the group, it must still be flagged even
        # though all values are identical Cyrillic.
        values = {
            "ru": "Яндекс",
            "uk": "Яндекс",
            "de": "Яндекс",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert "de" in invalid
        assert "ru" not in invalid
        assert "uk" not in invalid

    def test_uniform_arabic_all_arabic_script_locales_not_flagged(self):
        values = {
            "ar": "مرحبا",
            "fa": "مرحبا",
            "ur": "مرحبا",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_uniform_arabic_flags_non_arabic_locale(self):
        values = {
            "ar": "مرحبا",
            "fa": "مرحبا",
            "de": "مرحبا",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert "de" in invalid
        assert "ar" not in invalid
        assert "fa" not in invalid

    def test_uniform_greek_all_greek_locale_not_flagged(self):
        values = {
            "el": "Ελληνικά",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_uniform_greek_flags_non_greek_locale(self):
        values = {
            "el": "Ελληνικά",
            "de": "Ελληνικά",
            "fr": "Ελληνικά",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert "de" in invalid
        assert "fr" in invalid
        assert "el" not in invalid

    def test_uniform_devanagari_all_devanagari_locales_not_flagged(self):
        values = {
            "hi": "नमस्ते",
            "mr": "नमस्ते",
            "ne": "नमस्ते",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert invalid == []

    def test_uniform_devanagari_flags_non_devanagari_locale(self):
        values = {
            "hi": "नमस्ते",
            "mr": "नमस्ते",
            "de": "नमस्ते",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert "de" in invalid
        assert "hi" not in invalid
        assert "mr" not in invalid

    def test_mixed_script_uniform_group_not_suppressed_by_non_latin_path(self):
        # Mixed Cyrillic+Latin text (e.g. "Привет PDF") spans two scripts;
        # the non-Latin suppression must not apply; normal analysis runs.
        values = {
            "ru": "Привет PDF",
            "uk": "Привет PDF",
            "de": "Привет PDF",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        # de should still be flagged because it has dominant Cyrillic
        assert "de" in invalid

    # --- Underscore / CamelCase identifier suppression ---

    def test_leading_underscore_token_not_flagged(self):
        # Regression: "_edit" was previously extracted as the shared token "edit" (losing the
        # underscore), so the boundary check blocked the suppression and "_edit" stayed invalid.
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale("ja", "例: _edit")
        assert not has_issue

    def test_snake_case_identifier_not_flagged(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja", "ノード {0}: RelatedImageCondition に edit_suffix がありません。"
        )
        assert not has_issue

    def test_pascal_case_identifier_not_flagged(self):
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja", "ノード {0}: NodeResultCondition に node_name がありません。"
        )
        assert not has_issue

    def test_underscore_only_value_not_flagged(self):
        # "de" differs slightly from the other locales so the group is not uniform (which would
        # otherwise short-circuit before per-locale analysis runs); this exercises the
        # identifier-run stripping inside analyze_locale directly.
        values = {
            "en": "group1_catA,group1_catB; group2_catA,group2_catB",
            "de": "group1_catA, group1_catB; group2_catA, group2_catB",
            "ja": "group1_catA,group1_catB; group2_catA,group2_catB",
            "zh": "group1_catA,group1_catB; group2_catA,group2_catB",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert "ja" not in invalid
        assert "zh" not in invalid

    def test_camel_case_lora_alone_not_flagged(self):
        # "LoRA" has a lower-to-upper hump ("oR"), so it now qualifies as CamelCase-ignorable
        # independent of the shared-token-across-all-locales mechanism.
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale("ja", "LoRA")
        assert not has_issue

    def test_plain_capitalized_word_still_counts_toward_ratio(self):
        # A single capitalized word with no hump (e.g. "Node") is not an identifier and should
        # still be treated as ordinary untranslated Latin text.
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale("ja", "Node Node Node Node")
        assert has_issue

    def test_allcaps_acronym_still_flagged_when_dominant(self):
        # ALLCAPS acronyms (e.g. "GENERATE") are intentionally NOT treated as ignorable
        # identifiers by this heuristic; only snake_case and CamelCase/PascalCase are.
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale("ja", "GENERATE GENERATE GENERATE")
        assert has_issue

    def test_genuinely_untranslated_sentence_still_flagged(self):
        # Regression guard: identifier-run suppression must not accidentally suppress a fully
        # untranslated plain-English sentence with no underscores or CamelCase words.
        has_issue = InvalidCharacterSetAnalyzer.analyze_locale(
            "ja", "Cannot cut at or past the end of the video."
        )
        assert has_issue

    # --- Default-locale token matching (vs. requiring every locale to match) ---

    def test_word_shared_with_default_locale_suppressed_even_if_one_sibling_locale_differs(self):
        # Regression: "fr" phrases "Enter" differently for this key ("Entrer"), which broke the
        # old all-locales-must-match intersection and left "ko"/"zh" flagged even though they
        # both legitimately kept the literal source word "Enter" alongside real translated text.
        values = {
            "en": "Drag to select crop, Enter to confirm, Escape to cancel",
            "fr": "Faites glisser pour recadrer, Entrer pour confirmer, Echap pour annuler",
            "ko": "드래그하여 자르기 선택, Enter로 확인, Escape로 취소",
            "zh": "拖动选择裁剪，Enter 确认，Escape 取消",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values, default_locale="en")
        assert "ko" not in invalid
        assert "zh" not in invalid

    def test_default_locale_matching_does_not_mask_a_fully_untranslated_locale(self):
        # Safety net: a locale whose value is just an unmodified copy of the source text has no
        # characters of its own expected script, so default-locale token matching must not apply
        # to it (every word would otherwise match the source and get scrubbed away entirely).
        # "de" is genuinely translated so the group isn't uniform (which would otherwise
        # short-circuit before per-locale analysis even runs).
        values = {
            "en": "Cannot cut at or past the end of the video.",
            "de": "Sie können nicht am oder nach dem Ende des Videos schneiden.",
            "ja": "Cannot cut at or past the end of the video.",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values, default_locale="en")
        assert "ja" in invalid

    def test_default_locale_matching_is_a_noop_when_default_locale_not_supplied(self):
        # Backward compatibility: omitting default_locale keeps the original strict
        # all-locales-must-match behavior.
        values = {
            "en": "Drag to select crop, Enter to confirm, Escape to cancel",
            "fr": "Faites glisser pour recadrer, Entrer pour confirmer, Echap pour annuler",
            "ko": "드래그하여 자르기 선택, Enter로 확인, Escape로 취소",
            "zh": "拖动选择裁剪，Enter 确认，Escape 取消",
        }
        invalid = InvalidCharacterSetAnalyzer.find_invalid_locales(values)
        assert "ko" in invalid
        assert "zh" in invalid
