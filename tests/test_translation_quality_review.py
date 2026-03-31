import unittest
import sys
import types
import unicodedata as u

if "polib" not in sys.modules:
    fake_polib = types.ModuleType("polib")
    class _POEntry:
        pass
    fake_polib.POEntry = _POEntry
    sys.modules["polib"] = fake_polib

from i18n.translation_quality_review import (
    collect_findings_for_group,
    _is_latin_char,
    _has_mixed_script_latin_leakage,
    _has_significant_latin_run,
)
from utils.globals import QualityHeuristicKind


class TestLatinHeuristicsRegression(unittest.TestCase):
    def test_russian_clause_with_single_c_triggers_mixed_script(self):
        text = "После восстановления войдите c новым паролем."
        self.assertTrue(
            _has_mixed_script_latin_leakage(text, ()),
            "Expected mixed-script heuristic to flag single Latin 'c' in Russian clause.",
        )

    def test_russian_clause_with_ee_confusable_triggers_some_latin_heuristic(self):
        text = "Если вы сбросите MFA, еe можно снова настроить в настройках аккаунта."
        mixed = _has_mixed_script_latin_leakage(text, ("MFA",))
        latin_run = _has_significant_latin_run(text, ("MFA",))
        self.assertTrue(
            mixed or latin_run,
            "Expected at least one heuristic (mixed-script or Latin-run) to flag clause with 'еe'.",
        )

    def test_exact_runtime_note_is_not_mixed_after_ignoring_mfa(self):
        text = (
            "После восстановления войдите с новым паролем. "
            "Если вы сбросите MFA, ее можно снова настроить в настройках аккаунта."
        )
        self.assertFalse(_has_mixed_script_latin_leakage(text, ("MFA",)))
        self.assertFalse(_has_significant_latin_run(text, ("MFA",)))

    def test_codepoint_clarity_for_confusables(self):
        # Latin 'B' + Cyrillic 'с' in "Bсего"
        # IDE APPLIES PARTIAL HIGHLIGHT FOR PARTIAL CYRILLIC WORD WITH CONFUSABLE CHARACTERS
        sample = "Bсего"
        self.assertEqual("LATIN", u.name(sample[0]).split()[0])
        self.assertEqual("CYRILLIC", u.name(sample[1]).split()[0])

        # IDE APPLIES FULL HIGHLIGHT FOR FULLY CYRILLIC WORD WITH CONFUSABLE CHARACTERS
        sample = "ее"
        self.assertEqual("CYRILLIC", u.name(sample[0]).split()[0])
        self.assertEqual("CYRILLIC", u.name(sample[1]).split()[0])
        for c in sample:
            self.assertEqual("CYRILLIC", u.name(c).split()[0], f"Character {c} should be CYRILLIC")

        # IDE APPLIES FULL HIGHLIGHT FOR FULLY CYRILLIC WORD WITH CONFUSABLE CHARACTERS
        sample = "Всего"
        for c in sample:
            self.assertEqual("CYRILLIC", u.name(c).split()[0], f"Character {c} should be CYRILLIC")

        # IDE APPLIES NO HIGHLIGHT FOR FULLY CYRILLIC WORD OF LENGTH WITH SOME CONFUSABLE CHARACTERS
        sample = "предстоящих"
        for c in sample:
            self.assertEqual("CYRILLIC", u.name(c).split()[0])
        
        # DOES IT MAKE SENSE? NO IT DOES NOT. THE LOGIC HERE IS TENUOUS AND CAN MAKE USERS MORE CONFUSED.

    def test_boundary_mixed_script_in_first_word_is_detected(self):
        # First character is Latin 'B', second is Cyrillic 'о'
        text = "Bо всех гильдиях, где вы состоите"
        self.assertTrue(_has_mixed_script_latin_leakage(text, ()))

    def test_boundary_mixed_script_in_another_first_word_is_detected(self):
        # First character is Latin 'B', followed by Cyrillic letters
        text = "Bсего предстоящих"
        self.assertTrue(_has_mixed_script_latin_leakage(text, ()))

    def test_other(self):
        text = "Всего предстоящих"
        self.assertFalse(_has_significant_latin_run(text, ()))
        self.assertFalse(_has_mixed_script_latin_leakage(text, ()))

    def test_collect_findings_emits_both_latin_signals_when_both_match(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("sample.msgid", "")
                self._values = {
                    "en": "Sample English",
                    "ru": "Если вы сбросите MFA, еe можно снова настроить.",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "ru"],
            latin_ignore_patterns=(),
        )
        signals = {f.signal for f in findings if f.locale == "ru"}
        self.assertIn(QualityHeuristicKind.LATIN_IN_CJK_LOCALE, signals)
        self.assertIn(QualityHeuristicKind.LATIN_MIXED_SCRIPT_IN_NON_LATIN_LOCALE, signals)

    def test_accented_portuguese_letters_are_treated_as_latin(self):
        self.assertTrue(_is_latin_char("é"))
        self.assertTrue(_is_latin_char("ç"))
        self.assertTrue(_is_latin_char("ã"))
        self.assertTrue(_has_significant_latin_run("ação", ()))


if __name__ == "__main__":
    unittest.main()
