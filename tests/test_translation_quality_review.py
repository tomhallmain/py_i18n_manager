import unicodedata as u

from i18n.translation_group import TranslationGroup
from i18n.translation_quality_review import (
    collect_findings_for_group,
    collect_project_quality_findings,
    collect_quote_style_findings,
    _is_allowed_identical_copy,
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
        # Grouped findings use locale="" + notes listing the affected locale(s) (see
        # _grouped_locale_finding), mirroring IDENTICAL_TO_DEFAULT/IDENTICAL_TO_NONDEFAULT.
        signals = {f.signal for f in findings if "ru" in f.notes}
        assert QualityHeuristicKind.LATIN_IN_CJK_LOCALE in signals
        assert QualityHeuristicKind.LATIN_MIXED_SCRIPT_IN_NON_LATIN_LOCALE in signals

    def test_collect_findings_one_latin_in_cjk_finding_for_many_locales(self):
        # Same untranslated Latin term left in place across several CJK/Cyrillic locales should
        # collapse into a single grouped row (locale="", notes=affected locales), the same shape
        # already used for IDENTICAL_TO_DEFAULT / IDENTICAL_TO_NONDEFAULT.
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("shared.term", "")
                self._values = {
                    "en": "Enable LoRA",
                    "ja": "LoRA を有効にする Extra",
                    "ko": "LoRA 활성화 Extra",
                    "zh": "启用 LoRA Extra",
                    "ru": "Включить LoRA Extra",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "ja", "ko", "zh", "ru"],
            latin_ignore_patterns=(),
        )
        latin_findings = [
            f for f in findings if f.signal == QualityHeuristicKind.LATIN_IN_CJK_LOCALE
        ]
        assert len(latin_findings) == 1
        assert latin_findings[0].locale == ""
        assert set(latin_findings[0].notes.split(", ")) == {"ja", "ko", "zh", "ru"}

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
        signals = {f.signal for f in findings if "de" in f.notes}
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
        signals = {f.signal for f in findings if "de" in f.notes}
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
        default_findings = [
            f for f in findings if f.signal == QualityHeuristicKind.IDENTICAL_TO_DEFAULT
        ]
        assert len(default_findings) == 1
        assert default_findings[0].locale == ""
        assert set(default_findings[0].notes.split(", ")) == {"de", "fr"}
        assert QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT not in {
            f.signal for f in findings
        }

    def test_collect_findings_default_not_nondefault_when_values_match_default(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("msg.ok", "")
                self._values = {
                    "en": "Confirm:",
                    "de": "Confirm:",
                    "it": "Confirm:",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "de", "it"],
            latin_ignore_patterns=(),
        )
        assert [
            f for f in findings if f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT
        ] == []
        default_findings = [
            f for f in findings if f.signal == QualityHeuristicKind.IDENTICAL_TO_DEFAULT
        ]
        assert len(default_findings) == 1
        assert set(default_findings[0].notes.split(", ")) == {"de", "it"}

    def test_collect_findings_skips_globally_shared_scientific_units(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("units.temp", "")
                self._values = {
                    "en": "Fahrenheit",
                    "de": "Fahrenheit",
                    "es": "Fahrenheit",
                    "fr": "Fahrenheit",
                    "it": "Fahrenheit",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "de", "es", "fr", "it"],
            latin_ignore_patterns=(),
        )
        assert not findings

    def test_collect_findings_skips_nondefault_when_cross_language_allowlist(self):
        cases = [
            (
                "good.msg",
                {"en": "Good", "es": "Bien", "fr": "Bien"},
                ["en", "es", "fr"],
            ),
            (
                "profile.msg",
                {"en": "Profile", "de": "Profil", "fr": "Profil"},
                ["en", "de", "fr"],
            ),
            (
                "share.msg",
                {"en": "Share", "es": "Compartir", "it": "Compartir"},
                ["en", "es", "it"],
            ),
        ]
        for msgid, values, locales in cases:
            class _FakeKey:
                def __init__(self, mid: str, context: str = ""):
                    self.msgid = mid
                    self.context = context

            class _FakeGroup:
                def __init__(self, mid: str, vals: dict):
                    self.key = _FakeKey(mid, "")
                    self._values = vals

                def get_translation(self, locale: str):
                    return self._values.get(locale, "")

            findings = collect_findings_for_group(
                _FakeGroup(msgid, values),
                default_locale="en",
                locales=locales,
                latin_ignore_patterns=(),
            )
            assert QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT not in {
                f.signal for f in findings
            }, msgid

    def test_collect_findings_skips_name_with_sort_suffix_via_de_loanword(self):
        class _FakeKey:
            def __init__(self, msgid: str, context: str = ""):
                self.msgid = msgid
                self.context = context

        class _FakeGroup:
            def __init__(self):
                self.key = _FakeKey("sort.name", "")
                self._values = {
                    "en": "Name (A-Z)",
                    "de": "Name (A-Z)",
                }

            def get_translation(self, locale: str):
                return self._values.get(locale, "")

        findings = collect_findings_for_group(
            _FakeGroup(),
            default_locale="en",
            locales=["en", "de"],
            latin_ignore_patterns=(),
        )
        assert not findings


class TestUseBuiltinExclusionsToggle:
    """The use_builtin_exclusions flag gates GLOBALLY_SHARED, EN_SHARED, and CROSS_LANGUAGE checks."""

    # ── _is_allowed_identical_copy: globally-shared terms ────────────────────

    def test_globally_shared_term_allowed_when_builtins_on(self):
        # "PDF" is in GLOBALLY_SHARED → allowed immediately
        assert _is_allowed_identical_copy("en", "de", "PDF", use_builtin_exclusions=True)

    def test_globally_shared_term_not_allowed_when_builtins_off(self):
        # With builtins off, "PDF" has Latin letters and no strips apply → not allowed
        assert not _is_allowed_identical_copy("en", "de", "PDF", use_builtin_exclusions=False)

    def test_globally_shared_ok_allowed_when_builtins_on(self):
        assert _is_allowed_identical_copy("en", "ru", "OK", use_builtin_exclusions=True)

    def test_globally_shared_ok_not_allowed_when_builtins_off(self):
        assert not _is_allowed_identical_copy("en", "ru", "OK", use_builtin_exclusions=False)

    def test_globally_shared_api_allowed_when_builtins_on(self):
        assert _is_allowed_identical_copy("en", "ja", "API", use_builtin_exclusions=True)

    def test_globally_shared_api_not_allowed_when_builtins_off(self):
        assert not _is_allowed_identical_copy("en", "ja", "API", use_builtin_exclusions=False)

    # ── _is_allowed_identical_copy: EN_SHARED per-language terms ─────────────

    def test_en_shared_de_loanword_allowed_when_builtins_on(self):
        # "browser" is in EN_SHARED for "de"
        assert _is_allowed_identical_copy("en", "de", "browser", use_builtin_exclusions=True)

    def test_en_shared_de_loanword_not_allowed_when_builtins_off(self):
        assert not _is_allowed_identical_copy("en", "de", "browser", use_builtin_exclusions=False)

    def test_en_shared_nl_loanword_allowed_when_builtins_on(self):
        assert _is_allowed_identical_copy("en", "nl", "dashboard", use_builtin_exclusions=True)

    def test_en_shared_nl_loanword_not_allowed_when_builtins_off(self):
        assert not _is_allowed_identical_copy("en", "nl", "dashboard", use_builtin_exclusions=False)

    def test_en_shared_ru_term_allowed_when_builtins_on(self):
        # "json" is in EN_SHARED for "ru"
        assert _is_allowed_identical_copy("en", "ru", "json", use_builtin_exclusions=True)

    def test_en_shared_ru_term_not_allowed_when_builtins_off(self):
        assert not _is_allowed_identical_copy("en", "ru", "json", use_builtin_exclusions=False)

    # ── User regex patterns are always honoured regardless of toggle ──────────

    def test_user_pattern_still_suppresses_when_builtins_off(self):
        # A user-configured pattern for "PDF" strips all Latin; should be allowed
        # even when built-in exclusions are disabled.
        assert _is_allowed_identical_copy(
            "en", "de", "PDF",
            latin_ignore_patterns=(r"(?i)\bPDF\b",),
            use_builtin_exclusions=False,
        )

    # ── collect_findings_for_group: IDENTICAL_TO_DEFAULT signal ──────────────

    def test_globally_shared_translation_no_finding_when_builtins_on(self):
        class _K:
            def __init__(self):
                self.msgid = "fmt.export"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "JSON", "de": "JSON", "fr": "JSON"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "de", "fr"],
            use_builtin_exclusions=True,
        )
        assert not any(f.signal == QualityHeuristicKind.IDENTICAL_TO_DEFAULT for f in findings)

    def test_globally_shared_translation_emits_finding_when_builtins_off(self):
        class _K:
            def __init__(self):
                self.msgid = "fmt.export"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "JSON", "de": "JSON", "fr": "JSON"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "de", "fr"],
            use_builtin_exclusions=False,
        )
        assert any(f.signal == QualityHeuristicKind.IDENTICAL_TO_DEFAULT for f in findings)

    def test_en_shared_loanword_no_finding_when_builtins_on(self):
        class _K:
            def __init__(self):
                self.msgid = "nav.browser"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "browser", "de": "browser"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "de"],
            use_builtin_exclusions=True,
        )
        assert not any(f.signal == QualityHeuristicKind.IDENTICAL_TO_DEFAULT for f in findings)

    def test_en_shared_loanword_emits_finding_when_builtins_off(self):
        class _K:
            def __init__(self):
                self.msgid = "nav.browser"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "browser", "de": "browser"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "de"],
            use_builtin_exclusions=False,
        )
        assert any(f.signal == QualityHeuristicKind.IDENTICAL_TO_DEFAULT for f in findings)

    # ── collect_findings_for_group: IDENTICAL_TO_NONDEFAULT signal ───────────

    def test_cross_locale_cluster_no_finding_when_builtins_on(self):
        # es and pt sharing "banco" is in the allowed {es, pt} group
        class _K:
            def __init__(self):
                self.msgid = "label.banco"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "bank content", "es": "banco", "pt": "banco"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "es", "pt"],
            use_builtin_exclusions=True,
        )
        assert not any(f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT for f in findings)

    def test_cross_locale_cluster_emits_finding_when_builtins_off(self):
        class _K:
            def __init__(self):
                self.msgid = "label.digital"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "digital content", "es": "digital", "pt": "digital"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "es", "pt"],
            use_builtin_exclusions=False,
        )
        assert any(f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT for f in findings)

    def test_globally_shared_nondefault_cluster_no_finding_when_builtins_on(self):
        # All non-default locales sharing "OK" — globally shared, no finding
        class _K:
            def __init__(self):
                self.msgid = "btn.confirm"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "Confirm", "de": "OK", "fr": "OK", "es": "OK"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "de", "fr", "es"],
            use_builtin_exclusions=True,
        )
        assert not any(f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT for f in findings)

    def test_globally_shared_nondefault_cluster_emits_finding_when_builtins_off(self):
        class _K:
            def __init__(self):
                self.msgid = "btn.confirm"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "Confirm", "de": "OK", "fr": "OK", "es": "OK"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "de", "fr", "es"],
            use_builtin_exclusions=False,
        )
        assert any(f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT for f in findings)

    # ── Sub-cluster splitting ─────────────────────────────────────────────────

    def test_partial_cluster_outsider_alone_suppressed(self):
        # es/pt sharing "banco" is approved; de is the only outsider → no finding
        # (IDENTICAL_TO_NONDEFAULT requires 2+ unapproved locales)
        class _K:
            def __init__(self):
                self.msgid = "tag.banco"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "bank media", "es": "banco", "pt": "banco", "de": "banco"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "es", "pt", "de"],
            use_builtin_exclusions=True,
        )
        assert not any(f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT for f in findings)

    def test_partial_cluster_two_outsiders_flagged(self):
        # es/pt sharing "banco" is approved; de and fr are both outsiders → finding for de+fr
        class _K:
            def __init__(self):
                self.msgid = "tag.banco"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {
                    "en": "bank media",
                    "es": "banco", "pt": "banco",
                    "de": "banco", "fr": "banco",
                }

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "es", "pt", "de", "fr"],
            use_builtin_exclusions=True,
        )
        nondefault = [f for f in findings if f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT]
        assert len(nondefault) == 1
        notes = nondefault[0].notes
        assert "de" in notes
        assert "fr" in notes
        # Approved pair should NOT appear in the finding
        assert "es" not in notes
        assert "pt" not in notes

    def test_partial_cluster_outsiders_flagged_builtins_off_shows_full_cluster(self):
        # Same data as above but builtins off → full cluster flagged (no splitting)
        class _K:
            def __init__(self):
                self.msgid = "tag.digital"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {
                    "en": "digital media",
                    "es": "digital", "pt": "digital",
                    "de": "digital", "fr": "digital",
                }

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "es", "pt", "de", "fr"],
            use_builtin_exclusions=False,
        )
        nondefault = [f for f in findings if f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT]
        assert len(nondefault) == 1
        notes = nondefault[0].notes
        assert "es" in notes
        assert "pt" in notes
        assert "de" in notes
        assert "fr" in notes


class TestCollectQuoteStyleFindings:
    """Tests for i18n.translation_quality_review.collect_quote_style_findings.

    "de" has a built-in valid style (LOW_HIGH_9_9, i.e. „…“) per
    i18n.quote_styles.DEFAULT_VALID_QUOTE_STYLE_BY_LANGUAGE; "it" is deliberately not curated,
    so its expected style falls back to whatever is dominant in the catalog.
    """

    def _group(self, msgid: str, values: dict) -> TranslationGroup:
        g = TranslationGroup(msgid, is_in_base=True)
        g.default_locale = "en"
        for locale, text in values.items():
            g.add_translation(locale, text)
        return g

    def test_no_findings_when_locale_matches_its_valid_style(self):
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "de": f"Er sagte „Hallo {i}“."})
            groups[g.key] = g

        findings = collect_quote_style_findings(groups, ["en", "de"], "en")
        assert findings == []

    def test_rule_3_dominant_disagrees_with_valid_flags_every_dominant_instance(self):
        # "de"'s built-in valid style is LOW_HIGH_9_9, but every translation actually uses
        # STRAIGHT quotes -- since the dominant style disagrees with the expected one, every
        # instance of the dominant style is a finding.
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "de": f'Er sagte "Hallo {i}".'})
            groups[g.key] = g

        findings = collect_quote_style_findings(groups, ["en", "de"], "en")
        quote_findings = [
            f for f in findings if f.signal == QualityHeuristicKind.QUOTE_STYLE_MISMATCH
        ]
        assert len(quote_findings) == 3
        for f in quote_findings:
            assert f.locale == ""
            assert f.notes == "de"

    def test_matches_valid_style_is_not_flagged_even_when_dominant_disagrees(self):
        # Same scenario as above, but one entry correctly uses the expected LOW_HIGH_9_9 style --
        # that one must not be flagged even though the corpus-wide dominant style is STRAIGHT.
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "de": f'Er sagte "Hallo {i}".'})
            groups[g.key] = g
        correct = self._group("key.correct", {"en": "hi", "de": "Er sagte „Hallo“."})
        groups[correct.key] = correct

        findings = collect_quote_style_findings(groups, ["en", "de"], "en")
        flagged_msgids = {f.key_msgid for f in findings}
        assert "key.correct" not in flagged_msgids
        assert "key.0" in flagged_msgids

    def test_rule_4_outlier_neither_dominant_nor_valid_is_flagged(self):
        # Dominant for "de" is STRAIGHT (majority); valid (built-in) is LOW_HIGH_9_9. A value
        # using guillemets matches neither and must be flagged as an outlier.
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "de": f'Er sagte "Hallo {i}".'})
            groups[g.key] = g
        outlier = self._group("key.outlier", {"en": "hi", "de": "Er sagte «Hallo»."})
        groups[outlier.key] = outlier

        findings = collect_quote_style_findings(groups, ["en", "de"], "en")
        flagged_msgids = {f.key_msgid for f in findings}
        assert "key.outlier" in flagged_msgids

    def test_uncurated_locale_falls_back_to_dominant_only(self):
        # "it" has no built-in valid style. Matching the dominant style should not be flagged;
        # an outlier that doesn't match the dominant style should be flagged.
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "it": f'Ha detto "Ciao {i}".'})
            groups[g.key] = g
        outlier = self._group("key.outlier", {"en": "hi", "it": "Ha detto «Ciao»."})
        groups[outlier.key] = outlier

        findings = collect_quote_style_findings(groups, ["en", "it"], "en")
        flagged_msgids = {f.key_msgid for f in findings}
        assert flagged_msgids == {"key.outlier"}

    def test_locale_with_no_detected_quote_style_anywhere_produces_no_findings(self):
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "pt": f"Ola, sem aspas aqui {i}."})
            groups[g.key] = g

        findings = collect_quote_style_findings(groups, ["en", "pt"], "en")
        assert findings == []

    def test_project_override_takes_precedence_over_builtin_default(self):
        # "de" built-in default is LOW_HIGH_9_9, but the project explicitly wants STRAIGHT.
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "de": f'Er sagte "Hallo {i}".'})
            groups[g.key] = g

        findings = collect_quote_style_findings(
            groups, ["en", "de"], "en", quote_style_overrides={"de": "straight"}
        )
        assert findings == []

    def test_invalid_override_value_falls_back_to_builtin_default(self):
        groups = {}
        for i in range(3):
            g = self._group(f"key.{i}", {"en": "hi", "de": f'Er sagte "Hallo {i}".'})
            groups[g.key] = g

        findings = collect_quote_style_findings(
            groups, ["en", "de"], "en", quote_style_overrides={"de": "not-a-real-style"}
        )
        # Falls back to the built-in LOW_HIGH_9_9 default, so STRAIGHT instances are flagged.
        assert len(findings) == 3

    def test_excluded_msgids_are_skipped(self):
        g = self._group("key.excluded", {"en": "hi", "de": 'Er sagte "Hallo".'})
        findings = collect_quote_style_findings(
            {g.key: g}, ["en", "de"], "en", excluded_msgids={"key.excluded"}
        )
        assert findings == []

    def test_multiple_mismatched_locales_in_one_key_are_grouped_into_one_finding(self):
        # de and pl both have built-in valid styles (LOW_HIGH_9_9 / LOW_HIGH_9_0); a straight-
        # quoted value in both should collapse into one grouped finding, not two rows.
        groups = {}
        for i in range(3):
            g = self._group(
                f"key.{i}",
                {"en": "hi", "de": f'Er sagte "Hallo {i}".', "pl": f'Powiedzial "Czesc {i}".'},
            )
            groups[g.key] = g

        findings = collect_quote_style_findings(groups, ["en", "de", "pl"], "en")
        quote_findings = [
            f for f in findings if f.signal == QualityHeuristicKind.QUOTE_STYLE_MISMATCH
        ]
        assert len(quote_findings) == 3  # one per key, not one per key-locale pair
        for f in quote_findings:
            assert set(f.notes.split(", ")) == {"de", "pl"}

    def test_collect_project_quality_findings_respects_quote_style_override(self):
        g = self._group("key.a", {"en": "hi", "de": 'Er sagte "Hallo".'})
        qf = collect_project_quality_findings(
            {g.key: g},
            ["en", "de"],
            "en",
            quote_style_overrides={"de": "straight"},
        )
        signals = {f.signal for f in qf.findings}
        # Matches the (overridden) expected style, so no quote-style finding.
        assert QualityHeuristicKind.QUOTE_STYLE_MISMATCH not in signals

    def test_collect_project_quality_findings_flags_quote_style_without_override(self):
        g = self._group("key.a", {"en": "hi", "de": 'Er sagte "Hallo".'})
        qf = collect_project_quality_findings({g.key: g}, ["en", "de"], "en")
        signals = {f.signal for f in qf.findings}
        assert QualityHeuristicKind.QUOTE_STYLE_MISMATCH in signals
