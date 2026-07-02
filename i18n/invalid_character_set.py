import re
from typing import Dict, List, Sequence
import unicodedata

from .text_scrub import scrub_dynamic_segments
from utils.utils import Utils

DEFAULT_THRESHOLD_RATIO = 0.40


class InvalidCharacterSetAnalyzer:
    """Backend detector for locale/script mismatch in translation text."""

    _LANGUAGE_EXPECTED_SCRIPT = {
        # Cyrillic-centric locales
        "ru": "cyrillic",
        "uk": "cyrillic",
        "bg": "cyrillic",
        "be": "cyrillic",
        "mk": "cyrillic",
        "sr": "cyrillic",
        "kk": "cyrillic",
        "ky": "cyrillic",
        "tg": "cyrillic",
        "mn": "cyrillic",
        "ce": "cyrillic",
        # Greek
        "el": "greek",
        # Hebrew
        "he": "hebrew",
        # Arabic-script locales
        "ar": "arabic",
        "fa": "arabic",
        "ur": "arabic",
        "ps": "arabic",
        "ug": "arabic",
        "sd": "arabic",
        "dv": "arabic",
        "ku": "arabic",
        # Devanagari
        "hi": "devanagari",
        "mr": "devanagari",
        "ne": "devanagari",
        "sa": "devanagari",
        # Bengali
        "bn": "bengali",
        "as": "bengali",
        # Gurmukhi
        "pa": "gurmukhi",
        # Gujarati
        "gu": "gujarati",
        # Odia
        "or": "odia",
        # Tamil
        "ta": "tamil",
        # Telugu
        "te": "telugu",
        # Kannada
        "kn": "kannada",
        # Malayalam
        "ml": "malayalam",
        # Sinhala
        "si": "sinhala",
        # Thai
        "th": "thai",
        # Lao
        "lo": "lao",
        # Khmer
        "km": "khmer",
        # Myanmar
        "my": "myanmar",
        # Georgian
        "ka": "georgian",
        # Armenian
        "hy": "armenian",
        # CJK
        "ja": "japanese_cjk",
        "zh": "chinese_cjk",
        "ko": "korean",
    }

    @staticmethod
    def _is_latin_char(ch: str) -> bool:
        if not ch or not ch.isalpha():
            return False
        try:
            return "LATIN" in unicodedata.name(ch)
        except ValueError:
            return False

    @classmethod
    def _non_latin_letter_ratio(cls, text: str) -> float:
        if not text:
            return 0.0
        latin = 0
        non_latin = 0
        for ch in text:
            if not ch.isalpha():
                continue
            if cls._is_latin_char(ch):
                latin += 1
            else:
                non_latin += 1
        total = latin + non_latin
        if total == 0:
            return 0.0
        return non_latin / total

    @staticmethod
    def _locale_expected_script(locale: str) -> str:
        if not locale:
            return "latin"
        language = locale.replace("-", "_").split("_")[0].lower()
        return InvalidCharacterSetAnalyzer._LANGUAGE_EXPECTED_SCRIPT.get(language, "latin")

    @classmethod
    def _character_script_family(cls, ch: str) -> str | None:
        if not ch or not ch.isalpha():
            return None
        if cls._is_latin_char(ch):
            return "latin"
        if "\uac00" <= ch <= "\ud7af":
            return "korean"
        if "\u3040" <= ch <= "\u309f":
            return "hiragana"
        if "\u30a0" <= ch <= "\u30ff":
            return "katakana"
        if "\u4e00" <= ch <= "\u9fff":
            return "han"
        try:
            name = unicodedata.name(ch)
        except ValueError:
            return "other_non_latin"
        if "CYRILLIC" in name:
            return "cyrillic"
        if "GREEK" in name:
            return "greek"
        if "HEBREW" in name:
            return "hebrew"
        if "ARABIC" in name:
            return "arabic"
        if "THAI" in name:
            return "thai"
        if "DEVANAGARI" in name:
            return "devanagari"
        if "BENGALI" in name:
            return "bengali"
        if "GURMUKHI" in name:
            return "gurmukhi"
        if "GUJARATI" in name:
            return "gujarati"
        if "ORIYA" in name or "ODIA" in name:
            return "odia"
        if "TAMIL" in name:
            return "tamil"
        if "TELUGU" in name:
            return "telugu"
        if "KANNADA" in name:
            return "kannada"
        if "MALAYALAM" in name:
            return "malayalam"
        if "SINHALA" in name:
            return "sinhala"
        if "LAO" in name:
            return "lao"
        if "KHMER" in name:
            return "khmer"
        if "MYANMAR" in name:
            return "myanmar"
        if "GEORGIAN" in name:
            return "georgian"
        if "ARMENIAN" in name:
            return "armenian"
        return "other_non_latin"

    @classmethod
    def _script_family_ratios(cls, text: str) -> Dict[str, float]:
        counts: Dict[str, int] = {}
        total_letters = 0
        for ch in text:
            family = cls._character_script_family(ch)
            if not family:
                continue
            counts[family] = counts.get(family, 0) + 1
            total_letters += 1
        if total_letters == 0:
            return {}
        return {family: count / total_letters for family, count in counts.items()}

    @staticmethod
    def _apply_ignore_patterns(text: str, patterns: Sequence[str]) -> str:
        scrubbed = text or ""
        for pattern in patterns:
            p = (pattern or "").strip()
            if not p:
                continue
            try:
                scrubbed = re.sub(p, "", scrubbed)
            except re.error:
                continue
        return scrubbed

    @staticmethod
    def _allowed_script_families(expected_script: str) -> set[str]:
        if expected_script == "japanese_cjk":
            # Japanese allows Han (shared Chinese characters) and kana.
            return {"han", "hiragana", "katakana"}
        if expected_script == "chinese_cjk":
            return {"han"}
        if expected_script == "korean":
            return {"korean"}
        if expected_script == "latin":
            return {"latin"}
        return {expected_script}

    @classmethod
    def _has_expected_script_representation(cls, locale: str, text: str) -> bool:
        expected_script = cls._locale_expected_script(locale)
        allowed = cls._allowed_script_families(expected_script)
        for ch in text:
            family = cls._character_script_family(ch)
            if family and family in allowed:
                return True
        return False

    @staticmethod
    def _extract_ascii_word_tokens(text: str) -> set[str]:
        if not text:
            return set()
        # Focus on compact ASCII words/acronyms often reused intentionally across locales.
        # Leading underscore is allowed so a token like "_edit" is captured whole rather than
        # losing its underscore to a subsequent boundary check (see _IDENTIFIER_RUN_PATTERN).
        return {
            m.group(0).casefold()
            for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]{1,31}", text)
        }

    # Maximal runs of identifier-like characters (letters, digits, underscore). Unlike
    # _extract_ascii_word_tokens (used for cross-locale shared-token suppression), this is
    # evaluated per-locale and per-run so it also catches snake_case/CamelCase identifiers that
    # only appear in one locale's text (e.g. a technical term left untranslated).
    _IDENTIFIER_RUN_PATTERN = re.compile(r"[A-Za-z0-9_]+")
    # A lowercase letter directly followed by an uppercase letter marks a genuine camelCase/
    # PascalCase "hump" (e.g. "RelatedImageCondition"), as opposed to a plain acronym like "PDFs"
    # or "IPAdapter" which only transition uppercase-to-lowercase.
    _CAMEL_CASE_HUMP_PATTERN = re.compile(r"[a-z][A-Z]")

    @classmethod
    def _is_ignorable_identifier_run(cls, run: str) -> bool:
        """Snake_case or CamelCase/PascalCase identifiers are expected to stay untranslated
        verbatim (e.g. config keys, class names), so they should not count toward script-mismatch
        detection."""
        if "_" in run:
            return True
        return bool(cls._CAMEL_CASE_HUMP_PATTERN.search(run))

    @classmethod
    def _strip_ignorable_identifier_runs(cls, text: str) -> str:
        return cls._IDENTIFIER_RUN_PATTERN.sub(
            lambda m: "" if cls._is_ignorable_identifier_run(m.group(0)) else m.group(0),
            text,
        )

    @classmethod
    def _build_shared_token_ignore_patterns(
        cls,
        scrubbed_by_locale: Dict[str, str],
    ) -> tuple[str, ...]:
        token_sets = [cls._extract_ascii_word_tokens(text) for text in scrubbed_by_locale.values()]
        if not token_sets:
            return tuple()
        shared = set.intersection(*token_sets)
        if not shared:
            return tuple()
        # Keep suppression narrow to reusable fragments (acronyms/tech tokens),
        # while allowing practical product/component names like "IPAdapter".
        shared = {tok for tok in shared if 2 <= len(tok) <= 16}
        if not shared:
            return tuple()
        # Use ASCII-token boundaries so tokens still match next to non-ASCII script chars
        # (e.g. "LoRAタグ", "тег-LoRA", etc.).
        return tuple(
            rf"(?i)(?<![A-Za-z0-9_]){re.escape(tok)}(?![A-Za-z0-9_])"
            for tok in sorted(shared)
        )

    @classmethod
    def _is_uniform_latin_only_group(cls, scrubbed_by_locale: Dict[str, str]) -> bool:
        normalized_values = {
            (text or "").strip().casefold() for text in scrubbed_by_locale.values()
        }
        if len(normalized_values) != 1:
            return False
        only_value = next(iter(normalized_values), "")
        if not only_value:
            return False
        ratios = cls._script_family_ratios(only_value)
        if not ratios:
            return False
        return set(ratios.keys()).issubset({"latin"})

    @classmethod
    def _get_uniform_single_non_latin_script(
        cls, scrubbed_by_locale: Dict[str, str]
    ) -> str | None:
        """Return the script family when all locales share identical single-non-Latin-script text.

        Returns ``None`` when values differ, are empty, contain Latin, or span multiple scripts.
        Used to skip the charset check for locales that legitimately expect the shared script
        while still flagging locales that do not.
        """
        normalized_values = {
            (text or "").strip().casefold() for text in scrubbed_by_locale.values()
        }
        if len(normalized_values) != 1:
            return None
        only_value = next(iter(normalized_values), "")
        if not only_value:
            return None
        ratios = cls._script_family_ratios(only_value)
        if not ratios:
            return None
        scripts = set(ratios.keys())
        if "latin" in scripts or len(scripts) != 1:
            return None
        return next(iter(scripts))

    @classmethod
    def analyze_locale(
        cls,
        locale: str,
        text: str,
        threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
        ignore_patterns: Sequence[str] = (),
    ) -> bool:
        if not text or not text.strip():
            return False
        scrubbed = scrub_dynamic_segments(text)
        scrubbed = cls._apply_ignore_patterns(scrubbed, ignore_patterns)
        scrubbed = cls._strip_ignorable_identifier_runs(scrubbed)
        if not scrubbed.strip():
            return False
        threshold_ratio = max(0.0, min(1.0, float(threshold_ratio)))

        non_latin_ratio = cls._non_latin_letter_ratio(scrubbed)

        if (
            not Utils.is_non_latin_script_locale(locale)
            and non_latin_ratio > threshold_ratio
        ):
            return True

        cjk_ratio = Utils.get_cjk_character_ratio(scrubbed)

        if not Utils.is_cjk_locale(locale) and cjk_ratio > threshold_ratio:
            return True

        expected_script = cls._locale_expected_script(locale)
        ratios = cls._script_family_ratios(scrubbed)

        # Locale-specific script expectation check (Cyrillic, Greek, Hebrew, Arabic, Thai, etc.).
        if ratios:
            allowed = cls._allowed_script_families(expected_script)
            unexpected_ratio = sum(
                ratio for family, ratio in ratios.items() if family not in allowed
            )
            if unexpected_ratio > threshold_ratio:
                return True
        return False

    @classmethod
    def find_invalid_locales(
        cls,
        values_by_locale: Dict[str, str],
        threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
        ignore_patterns: Sequence[str] = (),
        default_locale: str | None = None,
    ) -> List[str]:
        return cls.find_invalid_locales_for_group(
            values_by_locale,
            threshold_ratio=threshold_ratio,
            ignore_patterns=ignore_patterns,
            default_locale=default_locale,
        )

    @classmethod
    def find_invalid_locales_for_group(
        cls,
        values_by_locale: Dict[str, str],
        threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
        ignore_patterns: Sequence[str] = (),
        default_locale: str | None = None,
    ) -> List[str]:
        scrubbed_by_locale: Dict[str, str] = {}
        represented_expected_scripts: set[str] = set()
        has_own_script_by_locale: Dict[str, bool] = {}
        for locale, raw_text in values_by_locale.items():
            scrubbed = scrub_dynamic_segments(raw_text or "")
            scrubbed = cls._apply_ignore_patterns(scrubbed, ignore_patterns)
            scrubbed_by_locale[locale] = scrubbed
            has_own_script = cls._has_expected_script_representation(locale, scrubbed)
            has_own_script_by_locale[locale] = has_own_script
            if has_own_script:
                represented_expected_scripts.add(cls._locale_expected_script(locale))

        # If every locale has the same Latin-only text, keep this as a quality-review
        # concern (e.g., identical-to-default) and avoid surfacing as invalid character set.
        if cls._is_uniform_latin_only_group(scrubbed_by_locale):
            return []

        # If every locale shares the same single non-Latin script text (e.g. a Cyrillic proper
        # noun across ru/uk/bg), skip the charset check for any locale that expects that script.
        # Locales that do not expect it (e.g. de in a Cyrillic-uniform group) are still analysed.
        uniform_non_latin_script = cls._get_uniform_single_non_latin_script(scrubbed_by_locale)

        shared_token_patterns: tuple[str, ...] = tuple()
        # Only suppress shared unexpected parts when locale-specific scripts are truly represented.
        if len(represented_expected_scripts) >= 2:
            shared_token_patterns = cls._build_shared_token_ignore_patterns(scrubbed_by_locale)

        # Tokens present verbatim in the default/source locale's text (e.g. "Enter", "Escape",
        # a brand name). Requiring a match against *every* locale (shared_token_patterns above)
        # is fragile: one unrelated locale phrasing a word differently breaks suppression for
        # every other locale, even ones that legitimately kept the same source word. So a token
        # is also allowed per-locale if it appears in the default locale's text -- but only for
        # locales that already show some of their own expected script (has_own_script_by_locale),
        # so a locale whose value is just an untouched copy of the source text is not masked.
        default_tokens: set[str] = set()
        if default_locale and default_locale in scrubbed_by_locale:
            default_tokens = {
                tok
                for tok in cls._extract_ascii_word_tokens(scrubbed_by_locale[default_locale])
                if 2 <= len(tok) <= 16
            }

        base_ignore_patterns = tuple(ignore_patterns) + shared_token_patterns
        invalid: List[str] = []
        for locale, text in values_by_locale.items():
            if uniform_non_latin_script is not None:
                allowed = cls._allowed_script_families(cls._locale_expected_script(locale))
                if uniform_non_latin_script in allowed:
                    continue
            merged_ignore_patterns = base_ignore_patterns
            if default_tokens and locale != default_locale and has_own_script_by_locale.get(locale):
                local_tokens = cls._extract_ascii_word_tokens(scrubbed_by_locale[locale])
                locale_shared_with_default = local_tokens & default_tokens
                if locale_shared_with_default:
                    merged_ignore_patterns = merged_ignore_patterns + tuple(
                        rf"(?i)(?<![A-Za-z0-9_]){re.escape(tok)}(?![A-Za-z0-9_])"
                        for tok in sorted(locale_shared_with_default)
                    )
            if cls.analyze_locale(locale, text, threshold_ratio, merged_ignore_patterns):
                invalid.append(locale)
        return invalid
