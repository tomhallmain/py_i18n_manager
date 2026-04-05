"""Tests for i18n/ruby/yaml_parser_utils.py."""

import os
import tempfile
import unittest

from i18n.ruby.yaml_parser_utils import (
    RUAMEL_AVAILABLE,
    merge_dotted_keys_into_locale_file,
    merge_ruamel_data,
    quote_string_values,
    ruby_roundtrip_yaml,
)
from utils.nested_mapping import add_to_nested_dict


@unittest.skipUnless(RUAMEL_AVAILABLE, "ruamel.yaml required")
class TestMergeDottedKeysKeyOrder(unittest.TestCase):
    """merge_dotted_keys_into_locale_file appends new mapping keys; it does not sort keys."""

    def test_existing_keys_keep_order_new_keys_follow_call_order(self):
        """New siblings are appended after existing keys; order matches ``dotted_keys``, not alphabetical."""
        with tempfile.TemporaryDirectory() as tmp:
            rel = "config/locales/en/widgets.en.yml"
            abs_path = os.path.normpath(os.path.join(tmp, rel.replace("/", os.sep)))
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(
                    'en:\n  alpha: "a"\n  beta: "b"\n',
                )

            merge_dotted_keys_into_locale_file(
                tmp,
                rel,
                "en",
                ["zebra", "aaa", "nested.deep", "nested.other"],
            )

            ryaml = ruby_roundtrip_yaml()
            with open(abs_path, encoding="utf-8") as f:
                data = ryaml.load(f)
            en = data["en"]
            self.assertEqual(
                list(en.keys()),
                ["alpha", "beta", "zebra", "aaa", "nested"],
                "Existing keys stay first; new top-level keys follow insertion order (zebra before aaa, not sorted).",
            )
            nested = en["nested"]
            self.assertEqual(
                list(nested.keys()),
                ["deep", "other"],
                "Nested keys under a new parent follow the dotted-key sequence.",
            )


@unittest.skipUnless(RUAMEL_AVAILABLE, "ruamel.yaml required")
class TestMergeRuamelDataKeyResolution(unittest.TestCase):
    """merge_ruamel_data must update existing leaves when YAML/ruamel key types differ from str."""

    def test_merges_into_bool_true_key_when_new_uses_string_true(self):
        original = {True: {"leaf": "old"}}
        new = {"true": {"leaf": "new"}}
        merge_ruamel_data(original, quote_string_values(new))
        self.assertIn(True, original)
        self.assertEqual(str(original[True]["leaf"]), "new")

    def test_add_to_nested_dict_resolves_bool_segment(self):
        data = {True: {"inner": "x"}}
        add_to_nested_dict(data, "true.inner", "updated")
        self.assertEqual(data[True]["inner"], "updated")


if __name__ == "__main__":
    unittest.main()
