"""Tests for :meth:`TranslationGroup.get_invalid_brace_locales`."""

from i18n.translation_group import TranslationGroup


def _make(en_text, other_text, locale="fr"):
    g = TranslationGroup(en_text)
    g.default_locale = "en"
    g.add_translation("en", en_text)
    g.add_translation(locale, other_text)
    return g


def test_full_string_parenthetical_dropped_in_translation_is_invalid():
    g = _make(
        "(Unable to parse image prompt information for this file.)",
        "Impossible de traiter les informations de la promesse d'image pour ce fichier.",
    )
    assert "fr" in g.get_invalid_brace_locales()


def test_full_string_parenthetical_ok_when_translation_also_wrapped():
    g = _make(
        "(Unable to parse image prompt information for this file.)",
        "(Impossible de traiter les informations de la promesse d'image pour ce fichier.)",
    )
    assert "fr" not in g.get_invalid_brace_locales()


def test_full_string_parenthetical_added_only_in_translation_is_invalid():
    g = _make("Status message", "(Message de statut)")
    assert "fr" in g.get_invalid_brace_locales()


def test_period_inside_vs_outside_close_paren_both_full_wrap():
    g = _make(
        "(Open this image as part of a directory to see index details.)",
        "(Öffnen Sie dieses Bild als Teil eines Verzeichnisses, um Indexdetails zu sehen).",
        locale="de",
    )
    assert "de" not in g.get_invalid_brace_locales()


def test_cjk_ideographic_period_after_fullwidth_close_paren():
    g = TranslationGroup("(Open this image as part of a directory to see index details.)")
    g.default_locale = "en"
    g.add_translation("en", "(Open this image as part of a directory to see index details.)")
    g.add_translation("ja", "(インデックスの詳細を見るには、この画像をディレクトリの一部として開いてください）。")
    assert "ja" not in g.get_invalid_brace_locales()


def test_parentheses_loose_when_neither_side_is_full_string_parenthetical():
    g = _make("See (details) in the log", "Voir les détails dans le journal")
    assert "fr" not in g.get_invalid_brace_locales()


def test_curly_braces_still_compared_to_default():
    g = _make("Hello {name}", "Hallo name")
    assert "fr" in g.get_invalid_brace_locales()
