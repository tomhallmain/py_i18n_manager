"""Tests for utils/nested_mapping.py."""

import unittest

from utils.nested_mapping import get_nested_value


class TestGetNestedValue(unittest.TestCase):
    def test_returns_list_leaf_without_stringifying(self):
        data = {"a": {"b": ["line one", "line two"]}}
        self.assertEqual(get_nested_value(data, "a.b"), ["line one", "line two"])


if __name__ == "__main__":
    unittest.main()
