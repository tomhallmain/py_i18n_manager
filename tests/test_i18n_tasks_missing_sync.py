"""Tests for i18n/ruby/i18n_tasks_sync.py."""

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from i18n.ruby.i18n_tasks_sync import (
    MissingRow,
    dynamic_prefix_brace_needle,
    is_i18n_tasks_missing_report_output,
    merge_locale_prefixes_for_unused_strip,
    normalize_and_dedupe_unused_keys,
    parse_i18n_tasks_missing_table,
    parse_i18n_tasks_unused_keys,
    partition_keys_by_dynamic_prefix_hint,
    run_i18n_tasks_missing,
    run_i18n_tasks_unused,
    strip_leading_locale_from_i18n_tasks_key,
)
from i18n.ruby.i18n_tasks_pattern_router import (
    load_i18n_tasks_config,
    path_for_key_pattern_router,
)


class TestI18nTasksMissingReportDetection(unittest.TestCase):
    def test_detects_header_line_and_missing_translations_title(self):
        self.assertTrue(is_i18n_tasks_missing_report_output("Missing translations (12) | i18n-tasks\n"))
        table = "| Locale | Key | Value |\n| all | k | v |\n"
        self.assertTrue(is_i18n_tasks_missing_report_output(table))

    def test_rejects_empty_and_random_stderr(self):
        self.assertFalse(is_i18n_tasks_missing_report_output(""))
        self.assertFalse(is_i18n_tasks_missing_report_output("Some political banner text\n"))


class TestRunI18nTasksMissingExitCode(unittest.TestCase):
    @patch("i18n.ruby.i18n_tasks_sync._resolve_bundle_executable")
    @patch("i18n.ruby.i18n_tasks_sync.subprocess.run")
    def test_exit_1_with_table_on_stdout_is_success_stdout_only(
        self, mock_run, mock_bundle
    ):
        mock_bundle.return_value = "bundle"
        table = (
            "| Locale | Key | Value |\n"
            "| all | admin.x | src |\n"
        )
        mock_run.return_value = Mock(
            returncode=1,
            stdout=table,
            stderr="Unrelated stderr banner\n",
        )
        ok, text = run_i18n_tasks_missing("/tmp/project")
        self.assertTrue(ok)
        self.assertEqual(text.strip(), table.strip())


class TestI18nTasksMissingSync(unittest.TestCase):
    def test_parse_missing_table_sample(self):
        sample = textwrap.dedent(
            """\
            Missing translations (3) | i18n-tasks v1.1.2
            +-------------------------+-------------------------------------------------------------------------+----------+
            | Locale                  | Key                                                                     | Value    |
            +-------------------------+-------------------------------------------------------------------------+----------+
            |           all           | admin.feature_abusers.no                                                | src      |
            | de es fr                | dashboard.alliances                                                     | other    |
            |           en            | foo.bar                                                                 | zh text  |
            +-------------------------+-------------------------------------------------------------------------+----------+
            """
        )
        rows = parse_i18n_tasks_missing_table(sample)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], MissingRow("all", "admin.feature_abusers.no"))
        self.assertTrue(rows[0].is_missing_in_all_locales())
        self.assertEqual(rows[1], MissingRow("de es fr", "dashboard.alliances"))
        self.assertFalse(rows[1].is_missing_in_all_locales())
        self.assertEqual(rows[2].locale_column.strip(), "en")

    def test_path_for_key_pattern_router_order(self):
        rules = [
            ["js.*", "config/locales/%{locale}/javascript.%{locale}.yml"],
            ["admin.*", "config/locales/%{locale}/admin.%{locale}.yml"],
            "config/locales/%{locale}/%{locale}.yml",
        ]
        self.assertEqual(
            path_for_key_pattern_router("js.alert", "en", rules),
            "config/locales/en/javascript.en.yml",
        )
        self.assertEqual(
            path_for_key_pattern_router("admin.users.title", "en", rules),
            "config/locales/en/admin.en.yml",
        )
        self.assertEqual(
            path_for_key_pattern_router("guilds.members.title", "en", rules),
            "config/locales/en/en.yml",
        )

    def test_load_i18n_tasks_config_router_under_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "i18n-tasks.yml"
            p.write_text(
                textwrap.dedent(
                    """\
                    base_locale: en
                    data:
                      router: pattern_router
                      write:
                        - - "js.*"
                          - "config/locales/%{locale}/javascript.%{locale}.yml"
                        - config/locales/%{locale}/%{locale}.yml
                    """
                ),
                encoding="utf-8",
            )
            cfg = load_i18n_tasks_config(str(p))
            self.assertEqual(cfg.base_locale, "en")
            self.assertEqual(cfg.router, "pattern_router")
            self.assertEqual(len(cfg.data_write), 2)
            self.assertEqual(cfg.locales, ["en"])

    def test_load_i18n_tasks_config_locales(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "i18n-tasks.yml"
            p.write_text(
                textwrap.dedent(
                    """\
                    base_locale: en
                    locales: [en, de]
                    data:
                      router: pattern_router
                      write:
                        - config/locales/%{locale}/%{locale}.yml
                    """
                ),
                encoding="utf-8",
            )
            cfg = load_i18n_tasks_config(str(p))
            self.assertEqual(cfg.locales, ["en", "de"])


class TestDynamicPrefixBrace(unittest.TestCase):
    def test_needle_parent_plus_brace(self):
        self.assertEqual(
            dynamic_prefix_brace_needle("admin.dashboard.danger_zone.modal.error"),
            "admin.dashboard.danger_zone.modal.{",
        )

    def test_partition_skips_when_needle_in_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            rb = Path(tmp) / "app.rb"
            rb.write_text(
                "t('admin.dashboard.danger_zone.modal.' + error_key) # admin.dashboard.danger_zone.modal.{\n",
                encoding="utf-8",
            )
            keys = ["admin.dashboard.danger_zone.modal.error", "other.unused.key"]
            keep, skipped = partition_keys_by_dynamic_prefix_hint(str(tmp), keys)
            self.assertEqual(skipped, 1)
            self.assertEqual(keep, ["other.unused.key"])


class TestI18nTasksUnusedCli(unittest.TestCase):
    @patch("i18n.ruby.i18n_tasks_sync._resolve_bundle_executable")
    @patch("i18n.ruby.i18n_tasks_sync.subprocess.run")
    def test_exit_1_with_keys_on_stdout_is_success(self, mock_run, mock_bundle):
        mock_bundle.return_value = "bundle"
        mock_run.return_value = Mock(
            returncode=1,
            stdout="admin.foo.bar\nlegacy.key\n",
            stderr="",
        )
        ok, text = run_i18n_tasks_unused("/tmp/project")
        self.assertTrue(ok)
        self.assertIn("admin.foo.bar", text)

    def test_parse_unused_keys(self):
        raw = "# comment\nadmin.x\n\nbeta.y\n"
        self.assertEqual(
            parse_i18n_tasks_unused_keys(raw),
            ["admin.x", "beta.y"],
        )

    def test_parse_unused_table_dedupes_key_column(self):
        sample = textwrap.dedent(
            """\
            Unused translations | i18n-tasks
            +--------+------------------------------------------+-------+
            | Locale | Key                                      | Value |
            +--------+------------------------------------------+-------+
            |   de   | admin.dashboard.modal.error              | Fehler |
            |   en   | admin.dashboard.modal.error              | Error |
            |   de   | other.key                                | x |
            +--------+------------------------------------------+-------+
            """
        )
        self.assertEqual(
            parse_i18n_tasks_unused_keys(sample),
            ["admin.dashboard.modal.error", "other.key"],
        )


class TestNormalizeUnusedKeys(unittest.TestCase):
    def test_strip_locale_prefix_for_yaml_path(self):
        locales = merge_locale_prefixes_for_unused_strip(
            ["en", "de", "zh-CN"],
            [],
        )
        self.assertEqual(
            strip_leading_locale_from_i18n_tasks_key(
                "en.admin.dashboard.danger_zone.modal.error", locales
            ),
            "admin.dashboard.danger_zone.modal.error",
        )
        self.assertEqual(
            strip_leading_locale_from_i18n_tasks_key(
                "zh-CN.admin.dashboard.title", locales
            ),
            "admin.dashboard.title",
        )

    def test_normalize_dedupes_per_locale_lines(self):
        raw = [
            "en.admin.dashboard.title",
            "de.admin.dashboard.title",
            "en.other.leaf",
        ]
        locales = merge_locale_prefixes_for_unused_strip(["en", "de"], raw)
        self.assertEqual(
            normalize_and_dedupe_unused_keys(raw, locales),
            ["admin.dashboard.title", "other.leaf"],
        )

    def test_does_not_strip_admin_segment(self):
        """First segment ``admin`` is not treated as a locale."""
        raw = ["admin.dashboard.title"]
        locales = merge_locale_prefixes_for_unused_strip(["en"], raw)
        self.assertEqual(
            normalize_and_dedupe_unused_keys(raw, locales),
            ["admin.dashboard.title"],
        )


if __name__ == "__main__":
    unittest.main()
