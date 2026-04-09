"""Tests for I18NManagerBase concrete methods via a minimal stub subclass."""

import os
import tempfile
import unittest
from datetime import datetime

from i18n.i18n_manager_base import I18NManagerBase
from i18n.translation_group import TranslationGroup, TranslationKey
from i18n.translation_manager_results import TranslationAction, TranslationManagerResults
from tests.helpers import FakeSettingsManager


class _StubManager(I18NManagerBase):
    """Minimal concrete subclass for exercising base class logic."""

    @property
    def default_locale(self) -> str:
        return "en"

    def _detect_locale_directory(self) -> str:
        return "locale"

    def set_directory(self, directory: str):
        self._directory = directory

    def manage_translations(self, action=TranslationAction.CHECK_STATUS, modified_locales=None):
        pass

    def get_po_file_path(self, locale: str) -> str:
        return os.path.join(self._directory, "locale", locale, "LC_MESSAGES", "base.po")

    def get_pot_file_path(self) -> str:
        return os.path.join(self._directory, "locale", "base.pot")

    def generate_pot_file(self) -> bool:
        return True

    def create_mo_files(self, results):
        pass

    def write_po_files(self, modified_locales, results):
        pass

    def list_translation_file_paths(self) -> list:
        return []

    def find_translatable_strings(self):
        return {}

    def check_translations_changed(self, include_stale_translations=False) -> bool:
        return False


def _make_manager(locales=None, settings_manager=None) -> _StubManager:
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = _StubManager(tmpdir, locales=locales or ["en", "fr"], settings_manager=settings_manager)
        mgr._directory = tmpdir  # keep reference after TemporaryDirectory exits scope
        return mgr


def _minimal_results(action=TranslationAction.CHECK_STATUS) -> TranslationManagerResults:
    return TranslationManagerResults(
        project_dir="/tmp/stub",
        action=action,
        action_timestamp=datetime.now(),
        action_successful=True,
        locale_statuses={},
        failed_locales=[],
        default_locale="en",
        has_locale_dir=False,
        has_pot_file=False,
        pot_file_path=None,
        pot_last_modified=None,
    )


# ---------------------------------------------------------------------------
# Deleted key queue
# ---------------------------------------------------------------------------

class TestQueuedDeletedKeys(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager()

    def test_queue_deleted_keys_from_plain_strings(self):
        self.mgr.queue_deleted_keys(["foo", "bar"])
        self.assertIn("foo", self.mgr.pending_deleted_keys)
        self.assertIn("bar", self.mgr.pending_deleted_keys)

    def test_queue_deleted_keys_from_translation_key_objects(self):
        self.mgr.queue_deleted_keys([TranslationKey("hello")])
        self.assertIn("hello", self.mgr.pending_deleted_keys)

    def test_queue_deleted_keys_ignores_empty_strings(self):
        self.mgr.queue_deleted_keys([""])
        self.assertEqual(self.mgr.pending_deleted_keys, set())

    def test_queue_deleted_keys_accumulates(self):
        self.mgr.queue_deleted_keys(["a"])
        self.mgr.queue_deleted_keys(["b"])
        self.assertIn("a", self.mgr.pending_deleted_keys)
        self.assertIn("b", self.mgr.pending_deleted_keys)

    def test_clear_queued_deleted_keys_empties_set(self):
        self.mgr.queue_deleted_keys(["foo", "bar"])
        self.mgr.clear_queued_deleted_keys()
        self.assertEqual(self.mgr.pending_deleted_keys, set())


# ---------------------------------------------------------------------------
# Quality review settings delegation
# ---------------------------------------------------------------------------

class TestQualityReviewSettings(unittest.TestCase):
    def test_excluded_msgids_without_settings_manager_returns_empty_frozenset(self):
        mgr = _make_manager(settings_manager=None)
        self.assertEqual(mgr.get_quality_review_excluded_msgids(), frozenset())

    def test_excluded_msgids_with_settings_manager(self):
        sm = FakeSettingsManager(excluded_msgids=["skip.this", "and.this"])
        mgr = _make_manager(settings_manager=sm)
        excluded = mgr.get_quality_review_excluded_msgids()
        self.assertIn("skip.this", excluded)
        self.assertIn("and.this", excluded)

    def test_ignore_patterns_without_settings_manager_returns_empty_tuple(self):
        mgr = _make_manager(settings_manager=None)
        self.assertEqual(mgr.get_quality_review_script_ignore_patterns(), tuple())

    def test_ignore_patterns_with_settings_manager(self):
        sm = FakeSettingsManager(ignore_patterns=[r"\d+%", r"^\d+$"])
        mgr = _make_manager(settings_manager=sm)
        patterns = mgr.get_quality_review_script_ignore_patterns()
        self.assertIn(r"\d+%", patterns)


# ---------------------------------------------------------------------------
# get_invalid_translations
# ---------------------------------------------------------------------------

class TestGetInvalidTranslations(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager(locales=["en", "fr"])

    def _add_group(self, msgid, en_text, other_translations=None, is_in_base=True):
        g = TranslationGroup(msgid, is_in_base=is_in_base)
        g.default_locale = "en"
        g.add_translation("en", en_text)
        for locale, text in (other_translations or {}).items():
            g.add_translation(locale, text)
        self.mgr.translations[TranslationKey(msgid)] = g
        return g

    def test_empty_translations_returns_no_errors(self):
        result = self.mgr.get_invalid_translations()
        self.assertFalse(result.has_errors)

    def test_missing_locale_detected(self):
        self._add_group("greeting", "Hello", {})  # no fr translation
        result = self.mgr.get_invalid_translations()
        self.assertTrue(any("fr" in locs for _, locs in result.missing_locale_groups))

    def test_not_in_base_flagged_when_not_all_locales_written(self):
        key = TranslationKey("stale")
        g = TranslationGroup("stale", is_in_base=False)
        g.add_translation("en", "old")
        self.mgr.translations[key] = g
        # written_locales is empty → not all locales written
        result = self.mgr.get_invalid_translations()
        self.assertIn(key, result.not_in_base)

    def test_not_in_base_suppressed_when_all_locales_written(self):
        key = TranslationKey("stale")
        g = TranslationGroup("stale", is_in_base=False)
        g.add_translation("en", "old")
        self.mgr.translations[key] = g
        self.mgr.written_locales = set(self.mgr.locales)
        result = self.mgr.get_invalid_translations()
        self.assertNotIn(key, result.not_in_base)

    def test_invalid_index_placeholder_detected(self):
        self._add_group("fmt", "Hello {0}", {"fr": "Bonjour"})
        result = self.mgr.get_invalid_translations()
        self.assertTrue(any("fr" in locs for _, locs in result.invalid_index_locale_groups))

    def test_valid_translations_produce_no_errors(self):
        self._add_group("greeting", "Hello", {"fr": "Bonjour"})
        result = self.mgr.get_invalid_translations()
        self.assertFalse(result.has_errors)


# ---------------------------------------------------------------------------
# fix_invalid_translations
# ---------------------------------------------------------------------------

class TestFixInvalidTranslations(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager(locales=["en", "fr"])

    def test_fix_returns_false_when_nothing_to_fix(self):
        key = TranslationKey("hello")
        g = TranslationGroup("hello", is_in_base=True)
        g.add_translation("en", "Hello")
        g.add_translation("fr", "Bonjour")
        self.mgr.translations[key] = g
        self.assertFalse(self.mgr.fix_invalid_translations())

    def test_fix_corrects_leading_space_mismatch(self):
        key = TranslationKey("spaced")
        g = TranslationGroup("spaced", is_in_base=True)
        g.add_translation("en", "Hello")
        g.add_translation("fr", "  Bonjour")  # extra leading spaces
        self.mgr.translations[key] = g
        self.mgr.fix_invalid_translations()
        fixed = self.mgr.translations[key].get_translation("fr")
        self.assertFalse(fixed.startswith("  "))


# ---------------------------------------------------------------------------
# _populate_translation_statistics
# ---------------------------------------------------------------------------

class TestPopulateTranslationStatistics(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager(locales=["en", "fr"])

    def test_no_translations_leaves_stats_at_zero(self):
        results = _minimal_results()
        self.mgr._populate_translation_statistics(results, TranslationAction.CHECK_STATUS)
        self.assertEqual(results.total_strings, 0)
        self.assertEqual(results.total_locales, 0)

    def test_total_strings_reflects_translation_count(self):
        for i in range(4):
            key = TranslationKey(f"msg{i}")
            g = TranslationGroup(f"msg{i}", is_in_base=True)
            g.add_translation("en", f"text{i}")
            self.mgr.translations[key] = g
        results = _minimal_results()
        self.mgr._populate_translation_statistics(results, TranslationAction.CHECK_STATUS)
        self.assertEqual(results.total_strings, 4)

    def test_total_locales_reflects_manager_locales(self):
        key = TranslationKey("msg")
        g = TranslationGroup("msg", is_in_base=True)
        g.add_translation("en", "text")
        self.mgr.translations[key] = g
        results = _minimal_results()
        self.mgr._populate_translation_statistics(results, TranslationAction.CHECK_STATUS)
        self.assertEqual(results.total_locales, len(self.mgr.locales))

    def test_check_status_populates_invalid_groups_not_quality_findings(self):
        key = TranslationKey("msg")
        g = TranslationGroup("msg", is_in_base=True)
        g.add_translation("en", "Hello")
        self.mgr.translations[key] = g
        results = _minimal_results(TranslationAction.CHECK_STATUS)
        self.mgr._populate_translation_statistics(results, TranslationAction.CHECK_STATUS)
        self.assertIsNotNone(results.invalid_groups)
        self.assertIsNone(results.quality_findings)


# ---------------------------------------------------------------------------
# apply_latest_translation_file_mtime
# ---------------------------------------------------------------------------

class TestApplyLatestMtime(unittest.TestCase):
    def test_no_files_sets_none(self):
        mgr = _make_manager()
        results = _minimal_results()
        mgr.apply_latest_translation_file_mtime(results)
        self.assertIsNone(results.latest_translation_file_mtime)

    def test_real_file_sets_datetime(self):
        with tempfile.NamedTemporaryFile(suffix=".po", delete=False) as f:
            path = f.name
        try:
            mgr = _make_manager()
            mgr.list_translation_file_paths = lambda: [path]
            results = _minimal_results()
            mgr.apply_latest_translation_file_mtime(results)
            self.assertIsInstance(results.latest_translation_file_mtime, datetime)
        finally:
            os.unlink(path)

    def test_missing_file_is_skipped_gracefully(self):
        mgr = _make_manager()
        mgr.list_translation_file_paths = lambda: ["/nonexistent/path/base.po"]
        results = _minimal_results()
        mgr.apply_latest_translation_file_mtime(results)
        self.assertIsNone(results.latest_translation_file_mtime)

    def test_picks_latest_mtime_among_multiple_files(self):
        with tempfile.NamedTemporaryFile(suffix=".po", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix=".po", delete=False) as f2:
            p1, p2 = f1.name, f2.name
        try:
            mgr = _make_manager()
            mgr.list_translation_file_paths = lambda: [p1, p2]
            results = _minimal_results()
            mgr.apply_latest_translation_file_mtime(results)
            expected_mtime = datetime.fromtimestamp(max(os.path.getmtime(p1), os.path.getmtime(p2)))
            self.assertEqual(results.latest_translation_file_mtime, expected_mtime)
        finally:
            os.unlink(p1)
            os.unlink(p2)


if __name__ == "__main__":
    unittest.main()
