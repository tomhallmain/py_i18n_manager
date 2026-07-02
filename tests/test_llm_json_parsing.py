"""Tests for LLMResult's JSON parsing helpers (no network, no PyQt6 dependency).

These back both the existing single-value extraction (``generate_json_get_value``, used for
one-locale-at-a-time translation) and the new whole-object extraction (``generate_json_dict``,
used for the per-key/all-locales translation mode).
"""

from lib.llm import LLMResult


def _result(response_text):
    return LLMResult.from_json({"response": response_text})


class TestGetJsonDict:
    def test_parses_plain_json_object(self):
        r = _result('{"es": "Hola", "fr": "Bonjour"}')
        assert r.get_json_dict() == {"es": "Hola", "fr": "Bonjour"}

    def test_strips_code_fences_and_json_tag(self):
        r = _result('```json\n{"es": "Hola"}\n```')
        assert r.get_json_dict() == {"es": "Hola"}

    def test_returns_none_for_empty_response(self):
        assert _result("").get_json_dict() is None
        assert _result("   ").get_json_dict() is None

    def test_returns_none_for_non_json_text(self):
        r = _result("Sure, here is your translation: Hola")
        assert r.get_json_dict() is None

    def test_returns_none_for_json_array_not_object(self):
        assert _result("[1, 2, 3]").get_json_dict() is None

    def test_returns_none_for_malformed_json(self):
        assert _result('{"es": "Hola",}').get_json_dict() is None


class TestGetJsonAttr:
    """Also a regression test: this previously called the nonexistent
    ``Utils.is_similar_strings``, so the fuzzy-key fallback silently raised and always
    returned None instead of matching a near-miss key."""

    def test_exact_key_match(self):
        r = _result('{"translation": "Hola"}')
        out = r._get_json_attr("translation")
        assert out is not None
        assert out.response == "Hola"

    def test_fuzzy_key_fallback_for_close_match(self):
        # "translation_resutl" is a transposition (edit distance 2) of "translation_result",
        # close enough for Utils.is_similar_str to match at this length.
        r = _result('{"translation_resutl": "Hola"}')
        out = r._get_json_attr("translation_result")
        assert out is not None
        assert out.response == "Hola"

    def test_missing_key_returns_none(self):
        r = _result('{"totally_unrelated_field_name": "Hola"}')
        assert r._get_json_attr("translation") is None

    def test_malformed_json_returns_none(self):
        assert _result("not json at all")._get_json_attr("translation") is None

    def test_blank_attr_name_returns_none(self):
        r = _result('{"translation": "Hola"}')
        assert r._get_json_attr("") is None
        assert r._get_json_attr(None) is None
