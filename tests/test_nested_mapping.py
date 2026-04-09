"""Tests for utils/nested_mapping.py."""

from utils.nested_mapping import get_nested_value


def test_returns_list_leaf_without_stringifying():
    data = {"a": {"b": ["line one", "line two"]}}
    assert get_nested_value(data, "a.b") == ["line one", "line two"]
