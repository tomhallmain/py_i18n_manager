"""Tests for i18n/ruby/i18n_tasks_missing_sync.py."""

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from i18n.ruby.i18n_tasks_missing_sync import (
    MissingRow,
    is_i18n_tasks_missing_report_output,
    parse_i18n_tasks_missing_table,
    run_i18n_tasks_missing,
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
    @patch("i18n.ruby.i18n_tasks_missing_sync._resolve_bundle_executable")
    @patch("i18n.ruby.i18n_tasks_missing_sync.subprocess.run")
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


if __name__ == "__main__":
    unittest.main()
