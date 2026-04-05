"""Tests for i18n/ruby/yaml_parser_utils.py."""

import io
import os
import tempfile
import unittest

from i18n.ruby.yaml_parser_utils import (
    RUAMEL_AVAILABLE,
    ensure_ruby_yaml_safe_mapping_keys,
    merge_dotted_keys_into_locale_file,
    merge_ruamel_data,
    pyyaml_dump,
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

    def test_merge_updates_existing_scalar_leaf(self):
        """Regression: merged data must replace an existing string leaf (same as bool-key fix)."""
        original = {"en": {"home": {"title": "Old title"}}}
        merge_ruamel_data(
            original,
            quote_string_values({"en": {"home": {"title": "New title"}}}),
        )
        self.assertEqual(str(original["en"]["home"]["title"]), "New title")

    def test_merge_preserves_yaml_list_not_python_repr_string(self):
        """Lists must stay YAML sequences after merge/dump, not one scalar str(list)."""
        ryaml = ruby_roundtrip_yaml()
        original = ryaml.load(
            'de:\n  compare:\n    features:\n'
            '      - "14 Tage kostenlose Testversion"\n'
            '      - "Keine Kreditkarte erforderlich"\n'
        )
        merge_ruamel_data(
            original,
            quote_string_values(
                {
                    "de": {
                        "compare": {
                            "features": [
                                "Neu eins",
                                "Neu zwei",
                            ]
                        }
                    }
                }
            ),
        )
        features = original["de"]["compare"]["features"]
        self.assertIsInstance(features, list)
        self.assertEqual(len(features), 2)
        self.assertEqual(str(features[0]), "Neu eins")

        buf = io.StringIO()
        ryaml.dump(original, buf)
        dumped = buf.getvalue()
        self.assertNotIn("['Neu eins'", dumped)
        self.assertIn("- ", dumped)


class TestRubyYamlYesNoKeyQuoting(unittest.TestCase):
    """YAML 1.1 / Ruby Psych: unquoted yes/no keys become booleans; writers must quote them."""

    def test_pyyaml_dump_keeps_quoted_yes_no_keys(self):
        buf = io.StringIO()
        pyyaml_dump({"en": {"common": {"yes": "Да", "no": "Нет", "other": "x"}}}, buf)
        dumped = buf.getvalue()
        self.assertIn('"yes":', dumped)
        self.assertIn('"no":', dumped)

    @unittest.skipUnless(RUAMEL_AVAILABLE, "ruamel.yaml required")
    def test_ruamel_dump_quotes_yes_no_keys(self):
        ryaml = ruby_roundtrip_yaml()
        data = quote_string_values({"ru": {"common": {"yes": "Да", "no": "Нет"}}})
        ensure_ruby_yaml_safe_mapping_keys(data)
        buf = io.StringIO()
        ryaml.dump(data, buf)
        dumped = buf.getvalue()
        self.assertIn('"yes":', dumped)
        self.assertIn('"no":', dumped)

    @unittest.skipUnless(RUAMEL_AVAILABLE, "ruamel.yaml required")
    def test_merge_dotted_keys_writes_quoted_yes_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = "config/locales/en/widgets.en.yml"
            abs_path = os.path.normpath(os.path.join(tmp, rel.replace("/", os.sep)))
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write('en:\n  common:\n    other: "x"\n')

            merge_dotted_keys_into_locale_file(tmp, rel, "en", ["common.yes"])

            with open(abs_path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn('"yes":', text)


if __name__ == "__main__":
    unittest.main()
