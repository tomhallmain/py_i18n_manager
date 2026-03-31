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
    ) -> List[str]:
        invalid: List[str] = []
        for locale, text in values_by_locale.items():
            if cls.analyze_locale(locale, text, threshold_ratio, ignore_patterns):
                invalid.append(locale)
        return invalid
