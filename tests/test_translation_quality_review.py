import unicodedata as u

from i18n.translation_quality_review import (
    collect_findings_for_group,
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
        # es and pt sharing "digital" is in the allowed {es, pt} group
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
        # es/pt sharing "digital" is approved; de is the only outsider → no finding
        # (IDENTICAL_TO_NONDEFAULT requires 2+ unapproved locales)
        class _K:
            def __init__(self):
                self.msgid = "tag.digital"
                self.context = ""

        class _G:
            def __init__(self):
                self.key = _K()
                self._v = {"en": "digital media", "es": "digital", "pt": "digital", "de": "digital"}

            def get_translation(self, loc):
                return self._v.get(loc, "")

        findings = collect_findings_for_group(
            _G(), "en", ["en", "es", "pt", "de"],
            use_builtin_exclusions=True,
        )
        assert not any(f.signal == QualityHeuristicKind.IDENTICAL_TO_NONDEFAULT for f in findings)

    def test_partial_cluster_two_outsiders_flagged(self):
        # es/pt sharing "digital" is approved; de and fr are both outsiders → finding for de+fr
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
