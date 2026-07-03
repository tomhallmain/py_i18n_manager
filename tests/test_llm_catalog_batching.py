"""Tests for the LLM catalog review batch format (i18n.translation_quality_review).

Every line in a block -- including the default locale's own line -- uses the same
LOCALE<TAB>TEXT shape, so there's nothing special-cased for the LLM to parse. What's *not*
repeated is the key/msgid: the default-locale text serves as the group's implicit identifier
(the gettext key is typically the default text itself), so it's only sent once per group
instead of once per locale line, avoiding wasted tokens repeating a (sometimes long) key.
"""

from i18n.translation_group import TranslationGroup
from i18n.translation_quality_review import (
    format_catalog_group_block,
    iter_llm_catalog_batches,
)


class TestFormatCatalogGroupBlock:
    def test_default_locale_tagged_line_then_other_locale_lines(self):
        block = format_catalog_group_block("en", "Hello", [("de", "Hallo"), ("fr", "Bonjour")])
        lines = block.split("\n")
        assert lines == ["en\tHello", "de\tHallo", "fr\tBonjour"]

    def test_no_locale_texts_emits_default_line_only(self):
        assert format_catalog_group_block("en", "Hello", []) == "en\tHello"

    def test_newlines_in_text_replaced_with_spaces(self):
        block = format_catalog_group_block("en", "Line1\nLine2", [("de", "Zeile1\nZeile2")])
        lines = block.split("\n")
        assert lines[0] == "en\tLine1 Line2"
        assert lines[1] == "de\tZeile1 Zeile2"

    def test_tabs_in_text_replaced_with_spaces(self):
        block = format_catalog_group_block("en", "A\tB", [("de", "C\tD")])
        lines = block.split("\n")
        assert lines[0] == "en\tA B"
        assert lines[1] == "de\tC D"

    def test_long_text_truncated(self):
        block = format_catalog_group_block("en", "x" * 600, [])
        assert len(block) == len("en\t") + 480
        assert block.endswith("...")


class TestIterLlmCatalogBatches:
    def _group(self, msgid: str, values: dict) -> TranslationGroup:
        g = TranslationGroup(msgid, is_in_base=True)
        g.default_locale = "en"
        for locale, text in values.items():
            g.add_translation(locale, text)
        return g

    def test_empty_translations_returns_no_batches(self):
        assert iter_llm_catalog_batches({}, ["en", "de"], "en") == []

    def test_default_text_appears_exactly_once_per_group(self):
        g = self._group(
            "greeting",
            {
                "en": "Hello there, unique marker XYZ123",
                "de": "Hallo",
                "fr": "Bonjour",
                "es": "Hola",
            },
        )
        batches = iter_llm_catalog_batches(
            {g.key: g}, ["en", "de", "fr", "es"], "en", max_catalog_tokens=10000
        )
        combined = "\n".join(batches)
        assert combined.count("Hello there, unique marker XYZ123") == 1

    def test_default_locale_line_is_tagged_with_its_own_locale_code(self):
        # The default locale's own line is still tagged LOCALE<TAB>TEXT like every other line
        # (just emitted once, not once per other locale) rather than left bare/unlabeled.
        g = self._group("greeting", {"en": "Hello", "de": "Hallo"})
        batches = iter_llm_catalog_batches({g.key: g}, ["en", "de"], "en", max_catalog_tokens=10000)
        combined = "\n".join(batches)
        assert "en\tHello" in combined
        assert "de\tHallo" in combined
        assert combined.count("en\tHello") == 1

    def test_blocks_within_a_batch_separated_by_blank_line(self):
        g1 = self._group("a", {"en": "Hello", "de": "Hallo"})
        g2 = self._group("b", {"en": "Goodbye", "de": "Auf Wiedersehen"})
        batches = iter_llm_catalog_batches(
            {g1.key: g1, g2.key: g2}, ["en", "de"], "en", max_catalog_tokens=10000
        )
        assert len(batches) == 1
        assert "\n\n" in batches[0]

    def test_batch_starts_with_default_locale_header(self):
        g = self._group("a", {"en": "Hello", "de": "Hallo"})
        batches = iter_llm_catalog_batches({g.key: g}, ["en", "de"], "en", max_catalog_tokens=10000)
        assert batches[0].startswith("default_locale=en\n")

    def test_group_is_kept_atomic_across_a_small_budget(self):
        # A small budget forces multiple batches; a group's default text and its locale lines
        # must always land together in the same batch, never split across a boundary.
        groups = {}
        for i in range(5):
            g = self._group(
                f"key{i}",
                {
                    "en": f"Source text number {i}",
                    "de": f"Zieltext Nummer {i}",
                    "fr": f"Texte cible {i}",
                },
            )
            groups[g.key] = g

        batches = iter_llm_catalog_batches(groups, ["en", "de", "fr"], "en", max_catalog_tokens=40)
        assert len(batches) > 1

        for i in range(5):
            source_marker = f"Source text number {i}"
            de_marker = f"de\tZieltext Nummer {i}"
            fr_marker = f"fr\tTexte cible {i}"
            with_source = [idx for idx, b in enumerate(batches) if source_marker in b]
            with_de = [idx for idx, b in enumerate(batches) if de_marker in b]
            with_fr = [idx for idx, b in enumerate(batches) if fr_marker in b]
            assert with_source == with_de == with_fr
            assert len(with_source) == 1

    def test_oversized_single_group_still_gets_its_own_batch(self):
        g = self._group("big", {"en": "x" * 2000, "de": "y" * 2000})
        batches = iter_llm_catalog_batches({g.key: g}, ["en", "de"], "en", max_catalog_tokens=32)
        assert len(batches) == 1
        assert "..." in batches[0]
        assert "x" * 600 not in batches[0]
