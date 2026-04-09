"""Tests for TranslationManagerResults and LocaleStatus."""

import os
import tempfile
import unittest
from datetime import datetime

from i18n.invalid_translation_groups import InvalidTranslationGroups
from i18n.translation_manager_results import (
    LocaleStatus,
    TranslationAction,
    TranslationManagerResults,
)


def _make_results(**overrides) -> TranslationManagerResults:
    """Build a minimal valid TranslationManagerResults."""
    defaults = dict(
        project_dir="/tmp/proj",
        action=TranslationAction.CHECK_STATUS,
        action_timestamp=datetime.now(),
        action_successful=True,
        locale_statuses={},
        failed_locales=[],
        default_locale="en",
        has_locale_dir=True,
        has_pot_file=True,
        pot_file_path="/tmp/proj/locale/base.pot",
        pot_last_modified=None,
    )
    defaults.update(overrides)
    return TranslationManagerResults(**defaults)


class TestLocaleStatusConstruction(unittest.TestCase):
    def test_direct_construction_stores_fields(self):
        s = LocaleStatus(locale_code="fr", has_directory=True, has_po_file=True, has_mo_file=False)
        self.assertEqual(s.locale_code, "fr")
        self.assertTrue(s.has_directory)
        self.assertTrue(s.has_po_file)
        self.assertFalse(s.has_mo_file)

    def test_optional_fields_default_to_none(self):
        s = LocaleStatus(locale_code="de", has_directory=False, has_po_file=False, has_mo_file=False)
        self.assertIsNone(s.po_file_path)
        self.assertIsNone(s.mo_file_path)
        self.assertIsNone(s.last_modified)


class TestLocaleStatusFromDirectory(unittest.TestCase):
    def test_nonexistent_directory_returns_all_false(self):
        s = LocaleStatus.from_directory("/nonexistent/path/fr", "fr")
        self.assertFalse(s.has_directory)
        self.assertFalse(s.has_po_file)
        self.assertFalse(s.has_mo_file)
        self.assertIsNone(s.po_file_path)
        self.assertIsNone(s.mo_file_path)
        self.assertIsNone(s.last_modified)

    def test_empty_locale_dir_has_no_po_or_mo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s = LocaleStatus.from_directory(tmpdir, "fr")
            self.assertTrue(s.has_directory)
            self.assertFalse(s.has_po_file)
            self.assertFalse(s.has_mo_file)

    def test_with_po_file_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lc_dir = os.path.join(tmpdir, "LC_MESSAGES")
            os.makedirs(lc_dir)
            po_path = os.path.join(lc_dir, "base.po")
            open(po_path, "w").close()

            s = LocaleStatus.from_directory(tmpdir, "fr")
            self.assertTrue(s.has_po_file)
            self.assertFalse(s.has_mo_file)
            self.assertEqual(s.po_file_path, po_path)
            self.assertIsNotNone(s.last_modified)

    def test_with_both_po_and_mo_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lc_dir = os.path.join(tmpdir, "LC_MESSAGES")
            os.makedirs(lc_dir)
            for name in ("base.po", "base.mo"):
                open(os.path.join(lc_dir, name), "w").close()

            s = LocaleStatus.from_directory(tmpdir, "de")
            self.assertTrue(s.has_po_file)
            self.assertTrue(s.has_mo_file)


class TestTranslationManagerResultsNeedsSetup(unittest.TestCase):
    def test_no_pot_file_needs_setup(self):
        r = _make_results(has_pot_file=False)
        self.assertTrue(r.needs_setup())

    def test_no_locale_dir_needs_setup(self):
        r = _make_results(has_locale_dir=False, locale_statuses={})
        self.assertTrue(r.needs_setup())

    def test_no_locale_statuses_needs_setup(self):
        r = _make_results(locale_statuses={})
        self.assertTrue(r.needs_setup())

    def test_locale_missing_po_needs_setup(self):
        statuses = {"fr": LocaleStatus("fr", True, False, False)}
        r = _make_results(locale_statuses=statuses)
        self.assertTrue(r.needs_setup())

    def test_all_locales_have_po_does_not_need_setup(self):
        statuses = {
            "fr": LocaleStatus("fr", True, True, False),
            "de": LocaleStatus("de", True, True, False),
        }
        r = _make_results(locale_statuses=statuses)
        self.assertFalse(r.needs_setup())


class TestTranslationManagerResultsMissingFiles(unittest.TestCase):
    def test_get_missing_po_files_returns_locales_without_po(self):
        statuses = {
            "fr": LocaleStatus("fr", True, False, False),
            "de": LocaleStatus("de", True, True, False),
        }
        r = _make_results(locale_statuses=statuses)
        self.assertEqual(r.get_missing_po_files(), ["fr"])

    def test_get_missing_po_files_empty_when_all_present(self):
        statuses = {"fr": LocaleStatus("fr", True, True, False)}
        r = _make_results(locale_statuses=statuses)
        self.assertEqual(r.get_missing_po_files(), [])

    def test_get_missing_mo_files_returns_locales_without_mo(self):
        statuses = {
            "fr": LocaleStatus("fr", True, True, True),
            "de": LocaleStatus("de", True, True, False),
        }
        r = _make_results(locale_statuses=statuses)
        self.assertEqual(r.get_missing_mo_files(), ["de"])

    def test_get_missing_mo_files_empty_when_all_present(self):
        statuses = {"fr": LocaleStatus("fr", True, True, True)}
        r = _make_results(locale_statuses=statuses)
        self.assertEqual(r.get_missing_mo_files(), [])

    def test_get_outdated_po_files_returns_older_than_pot(self):
        pot_mod = datetime(2023, 6, 1)
        statuses = {
            "fr": LocaleStatus("fr", True, True, False, last_modified=datetime(2020, 1, 1)),
            "de": LocaleStatus("de", True, True, False, last_modified=datetime(2024, 1, 1)),
        }
        r = _make_results(locale_statuses=statuses, pot_last_modified=pot_mod)
        outdated = r.get_outdated_po_files()
        self.assertIn("fr", outdated)
        self.assertNotIn("de", outdated)

    def test_get_outdated_po_files_empty_when_no_pot_mtime(self):
        statuses = {"fr": LocaleStatus("fr", True, True, False, last_modified=datetime(2020, 1, 1))}
        r = _make_results(locale_statuses=statuses, pot_last_modified=None)
        self.assertEqual(r.get_outdated_po_files(), [])


class TestTranslationManagerResultsErrorHandling(unittest.TestCase):
    def test_extend_error_message_from_none(self):
        r = _make_results()
        r.extend_error_message("something failed")
        self.assertEqual(r.error_message, "something failed")

    def test_extend_error_message_appends_to_existing(self):
        r = _make_results()
        r.extend_error_message("first")
        r.extend_error_message("second")
        self.assertIn("first", r.error_message)
        self.assertIn("second", r.error_message)

    def test_determine_action_successful_fails_on_error_message(self):
        r = _make_results(action_successful=True)
        r.extend_error_message("oops")
        r.determine_action_successful()
        self.assertFalse(r.action_successful)

    def test_determine_action_successful_fails_on_failed_locales(self):
        r = _make_results(action_successful=True, failed_locales=["fr"])
        r.determine_action_successful()
        self.assertFalse(r.action_successful)

    def test_determine_action_successful_passes_when_clean(self):
        r = _make_results(action_successful=True)
        r.determine_action_successful()
        self.assertTrue(r.action_successful)

    def test_determine_action_successful_preserves_already_failed(self):
        r = _make_results(action_successful=False)
        r.determine_action_successful()
        self.assertFalse(r.action_successful)


class TestTranslationManagerResultsReport(unittest.TestCase):
    def test_format_report_contains_action_name(self):
        r = _make_results(action=TranslationAction.CHECK_STATUS)
        self.assertIn("CHECK_STATUS", r.format_status_report())

    def test_format_report_shows_error_message(self):
        r = _make_results(action_successful=False)
        r.extend_error_message("disk full")
        self.assertIn("disk full", r.format_status_report())

    def test_format_report_shows_locale(self):
        statuses = {"fr": LocaleStatus("fr", True, True, False)}
        r = _make_results(locale_statuses=statuses)
        self.assertIn("fr", r.format_status_report())

    def test_format_report_shows_translation_stats_when_nonzero(self):
        r = _make_results(total_strings=42, total_locales=3)
        report = r.format_status_report()
        self.assertIn("42", report)

    def test_format_report_shows_invalid_group_counts(self):
        invalid = InvalidTranslationGroups()
        invalid.missing_locale_groups.append((None, ["fr", "de"]))
        r = _make_results(total_strings=10, total_locales=2)
        r.invalid_groups = invalid
        report = r.format_status_report()
        self.assertIn("Missing Translations", report)


if __name__ == "__main__":
    unittest.main()
