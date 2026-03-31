import json
import tempfile
import unittest
from pathlib import Path

from utils.settings_manager import SettingsManager


class TestQualityReviewExclusionsSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_path = "C:/tmp/project-a"
        self.mgr = SettingsManager()
        self.mgr.settings_file = Path(self._tmp.name) / "settings.json"
        self.mgr.settings_file.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_patterns_seeds_defaults_once(self):
        patterns = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        self.assertTrue(patterns)
        self.assertIn(r"(?i)\bCSV\b", patterns)
        self.assertIn(r"(?i)\bHTML\b", patterns)
        self.assertIn(
            r"\b(?:JSON|YML|YAML|XML|CSV|TSV|TXT|LOG|MD|PDF|PNG|JPG|JPEG|GIF|WEBP|SVG|MP3|MP4|WAV|ZIP|EXE|APK|IPA|JS|TS|JSX|TSX|PY|RB|JAVA|KT|GO|RS|SQL|INI|CFG|CONF|TOML)s?\b",
            patterns,
        )
        self.assertIn(
            r"(?i)\b(?:Ctrl|Cmd|Shift)(?:(?:\+Shift)?\+[A-Za-z])?\b",
            patterns,
        )
        self.assertIn(
            r"(?i)\.(?:json|yml|yaml|xml|csv|tsv|txt|log|md|pdf|png|jpe?g|gif|webp|svg|mp3|mp4|wav|zip|tar|gz|7z|exe|msi|dmg|apk|ipa|js|ts|jsx|tsx|py|rb|java|kt|go|rs|c|cpp|h|hpp|ini|cfg|conf|toml|lock|sql)\b",
            patterns,
        )

        with open(self.mgr.settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = data["project_settings"][self.project_path]
        self.assertTrue(cfg.get("quality_review_script_ignore_patterns_initialized"))

    def test_empty_saved_patterns_are_not_reseeded(self):
        ok = self.mgr.save_quality_review_script_ignore_patterns(self.project_path, [])
        self.assertTrue(ok)
        loaded = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        self.assertEqual([], loaded)

    def test_reset_patterns_restores_defaults(self):
        self.mgr.save_quality_review_script_ignore_patterns(self.project_path, [r"(?i)\bSKU\b"])
        ok = self.mgr.reset_quality_review_script_ignore_patterns_to_defaults(self.project_path)
        self.assertTrue(ok)
        loaded = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        self.assertIn(r"(?i)\bCSV\b", loaded)
        self.assertNotIn(r"(?i)\bSKU\b", loaded)

    def test_save_patterns_normalizes_strips_and_deduplicates(self):
        ok = self.mgr.save_quality_review_script_ignore_patterns(
            self.project_path,
            ["  (?i)\\bAPI\\b  ", r"(?i)\bAPI\b", "", "   ", r"(?i)\bJSON\b"],
        )
        self.assertTrue(ok)
        loaded = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        self.assertEqual([r"(?i)\bAPI\b", r"(?i)\bJSON\b"], loaded)

    def test_migrates_legacy_latin_pattern_keys(self):
        legacy = {
            "project_settings": {
                self.project_path: {
                    "quality_review_latin_ignore_patterns": [r"(?i)\bCSV\b"],
                    "quality_review_latin_ignore_patterns_initialized": True,
                }
            }
        }
        with open(self.mgr.settings_file, "w", encoding="utf-8") as f:
            json.dump(legacy, f, indent=4)

        self.mgr._migrate_settings_schema()

        with open(self.mgr.settings_file, "r", encoding="utf-8") as f:
            migrated = json.load(f)
        cfg = migrated["project_settings"][self.project_path]
        self.assertIn("quality_review_script_ignore_patterns", cfg)
        self.assertIn("quality_review_script_ignore_patterns_initialized", cfg)
        self.assertNotIn("quality_review_latin_ignore_patterns", cfg)
        self.assertNotIn("quality_review_latin_ignore_patterns_initialized", cfg)


if __name__ == "__main__":
    unittest.main()
