"""Tests for list-valued translations: escaped/unescaped apply per element."""

from i18n.translation_group import TranslationGroup, escape_unicode, unescape_unicode


def test_escaped_applies_escape_unicode_to_each_element():
    g = TranslationGroup("home.features", is_in_base=True)
    g.add_translation("en", ["café", "naïve"])
    out = g.get_translation_escaped("en")
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0] == escape_unicode("café")
    assert out[1] == escape_unicode("naïve")


def test_unescaped_applies_unescape_to_each_element():
    g = TranslationGroup("k", is_in_base=True)
    g.add_translation("en", [r"caf\u00e9", "x"])
    out = g.get_translation_unescaped("en")
    assert isinstance(out, list)
    assert out[0] == unescape_unicode(r"caf\u00e9")
    assert out[1] == "x"
