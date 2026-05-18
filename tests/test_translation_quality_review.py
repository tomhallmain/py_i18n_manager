import unicodedata as u

from i18n.translation_quality_review import (
    collect_findings_for_group,
    _is_latin_char,
    _has_mixed_script_latin_leakage,
    _has_significant_latin_run,
)
from utils.globals import QualityHeuristicKind


class TestLatinHeuristicsRegression:
    def test_russian_clause_with_single_c_triggers_mixed_script(self):
        text = "После восстановления войдите c новым паролем."
        assert _has_mixed_script_latin_leakage(text, ()), \
            "Expected mixed-script heuristic to flag single Latin 'c' in Russian clause."

    def test_russian_clause_with_ee_confusable_triggers_some_latin_heuristic(self):
        text = "Если вы сбросите MFA, еe можно снова настроить в настройках аккаунта."
        mixed = _has_mixed_script_latin_leakage(text, ("MFA",))
        latin_run = _has_significant_latin_run(text, ("MFA",))
        assert mixed or latin_run, \
            "Expected at least one heuristic (mixed-script or Latin-run) to flag clause with 'еe'."

    def test_exact_runtime_note_is_not_mixed_after_ignoring_mfa(self):
        text = (
            "После восстановления войдите с новым паролем. "
            "Если вы сбросите MFA, ее можно снова настроить в настройках аккаунта."
        )
        assert not _has_mixed_script_latin_leakage(text, ("MFA",))
        assert not _has_significant_latin_run(text, ("MFA",))

    def test_codepoint_clarity_for_confusables(self):
        # Latin 'B' + Cyrillic 'с' in "Bсего"
        # IDE APPLIES PARTIAL HIGHLIGHT FOR PARTIAL CYRILLIC WORD WITH CONFUSABLE CHARACTERS
        sample = "Bсего"
        assert u.name(sample[0]).split()[0] == "LATIN"
        assert u.name(sample[1]).split()[0] == "CYRILLIC"

        # IDE APPLIES FULL HIGHLIGHT FOR FULLY CYRILLIC WORD WITH CONFUSABLE CHARACTERS
        sample = "ее"
        assert u.name(sample[0]).split()[0] == "CYRILLIC"
        assert u.name(sample[1]).split()[0] == "CYRILLIC"
        for c in sample:
            assert u.name(c).split()[0] == "CYRILLIC", f"Character {c} should be CYRILLIC"

        # IDE APPLIES FULL HIGHLIGHT FOR FULLY CYRILLIC WORD WITH CONFUSABLE CHARACTERS
        sample = "Всего"
        for c in sample:
            assert u.name(c).split()[0] == "CYRILLIC", f"Character {c} should be CYRILLIC"

        # IDE APPLIES NO HIGHLIGHT FOR FULLY CYRILLIC WORD OF LENGTH WITH SOME CONFUSABLE CHARACTERS
        sample = "предстоящих"
        for c in sample:
            assert u.name(c).split()[0] == "CYRILLIC"

        # DOES IT MAKE SENSE? NO IT DOES NOT. THE LOGIC HERE IS TENUOUS AND CAN MAKE USERS MORE CONFUSED.

    def test_boundary_mixed_script_in_first_word_is_detected(self):
        # First character is Latin 'B', second is Cyrillic 'о'
        text = "Bо всех гильдиях, где вы состоите"
        assert _has_mixed_script_latin_leakage(text, ())

    def test_boundary_mixed_script_in_another_first_word_is_detected(self):
        # First character is Latin 'B', followed by Cyrillic letters
        text = "Bсего предстоящих"
        assert _has_mixed_script_latin_leakage(text, ())

    def test_other(self):
        text = "Всего предстоящих"
        assert not _has_significant_latin_run(text, ())
        assert not _has_mixed_script_latin_leakage(text, ())

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
        assert QualityHeuristicKind.LATIN_IN_CJK_LOCALE in signals
        assert QualityHeuristicKind.LATIN_MIXED_SCRIPT_IN_NON_LATIN_LOCALE in signals

    def test_accented_portuguese_letters_are_treated_as_latin(self):
        assert _is_latin_char("é")
        assert _is_latin_char("ç")
        assert _is_latin_char("ã")
        assert _has_significant_latin_run("ação", ())

    def test_collect_findings_stop_character_inconsistency_extra(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("ui.save", "")
                self._values = {
                    "en": "Save",
                    "de": "Speichern.",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "de"],
            latin_ignore_patterns=(),
        )
        signals = {f.signal for f in findings if f.locale == "de"}
        assert QualityHeuristicKind.STOP_CHARACTER_INCONSISTENCY in signals

    def test_collect_findings_no_inconsistency_when_stops_match(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("msg.ok", "")
                self._values = {
                    "en": "OK.",
                    "de": "OK.",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "de"],
            latin_ignore_patterns=(),
        )
        assert not any(f.signal == QualityHeuristicKind.STOP_CHARACTER_INCONSISTENCY for f in findings)

    def test_collect_findings_stop_inconsistency_missing_stop(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("msg.line", "")
                self._values = {
                    "en": "Done.",
                    "de": "Fertig",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "de"],
            latin_ignore_patterns=(),
        )
        signals = {f.signal for f in findings if f.locale == "de"}
        assert QualityHeuristicKind.STOP_CHARACTER_INCONSISTENCY in signals

    def test_collect_findings_identical_to_nondefault_when_locales_match(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("greeting.hello", "")
                self._values = {
                    "en": "Hello",
                    "fr": "Bonjour",
                    "de": "Bonjour",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "fr", "de"],
            latin_ignore_patterns=(),
        )
        nond = [
            f
            for f in findings
            if f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT
        ]
        assert len(nond) == 1
        assert nond[0].locale == ""
        assert nond[0].notes == "de, fr"

    def test_collect_findings_one_nondefault_finding_for_many_locales(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("shared.msg", "")
                self._values = {
                    "en": "Hello",
                    "fr": "Bonjour",
                    "de": "Bonjour",
                    "es": "Bonjour",
                    "it": "Bonjour",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "fr", "de", "es", "it"],
            latin_ignore_patterns=(),
        )
        nond = [
            f
            for f in findings
            if f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT
        ]
        assert len(nond) == 1
        assert set(nond[0].notes.split(", ")) == {"de", "es", "fr", "it"}

    def test_collect_findings_skips_nondefault_when_identical_to_default(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("greeting.hello", "")
                self._values = {
                    "en": "Hello",
                    "fr": "Hello",
                    "de": "Hello",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "fr", "de"],
            latin_ignore_patterns=(),
        )
        for loc in ("fr", "de"):
            signals = {f.signal for f in findings if f.locale == loc}
            assert signals == {QualityHeuristicKind.IDENTICAL_TO_DEFAULT}
            assert QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT not in signals
