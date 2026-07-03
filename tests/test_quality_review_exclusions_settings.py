import json
import tempfile
from pathlib import Path

from utils.settings_manager import SettingsManager


class TestQualityReviewExclusionsSettings:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_path = "C:/tmp/project-a"
        self.mgr = SettingsManager()
        self.mgr.settings_file = Path(self._tmp.name) / "settings.json"
        self.mgr.settings_file.parent.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        self._tmp.cleanup()

    def test_get_patterns_seeds_defaults_once(self):
        patterns = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        assert patterns
        assert r"(?i)\bCSV\b" in patterns
        assert r"(?i)\bHTML\b" in patterns
        assert (
            r"\b(?:JSON|YML|YAML|XML|CSV|TSV|TXT|LOG|MD|PDF|PNG|JPG|JPEG|GIF|WEBP|SVG|MP3|MP4|WAV|ZIP|EXE|APK|IPA|JS|TS|JSX|TSX|PY|RB|JAVA|KT|GO|RS|SQL|INI|CFG|CONF|TOML)s?\b"
            in patterns
        )
        assert (
            r"(?i)\b(?:Ctrl|Cmd|Shift)(?:(?:\+Shift)?\+[A-Za-z])?\b"
            in patterns
        )
        assert (
            r"(?i)\.(?:json|yml|yaml|xml|csv|tsv|txt|log|md|pdf|png|jpe?g|gif|webp|svg|mp3|mp4|wav|zip|tar|gz|7z|exe|msi|dmg|apk|ipa|js|ts|jsx|tsx|py|rb|java|kt|go|rs|c|cpp|h|hpp|ini|cfg|conf|toml|lock|sql)\b"
            in patterns
        )

        with open(self.mgr.settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = data["project_settings"][self.project_path]
        assert cfg.get("quality_review_script_ignore_patterns_initialized")

    def test_empty_saved_patterns_are_not_reseeded(self):
        ok = self.mgr.save_quality_review_script_ignore_patterns(self.project_path, [])
        assert ok
        loaded = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        assert loaded == []

    def test_reset_patterns_restores_defaults(self):
        self.mgr.save_quality_review_script_ignore_patterns(self.project_path, [r"(?i)\bSKU\b"])
        ok = self.mgr.reset_quality_review_script_ignore_patterns_to_defaults(self.project_path)
        assert ok
        loaded = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        assert r"(?i)\bCSV\b" in loaded
        assert r"(?i)\bSKU\b" not in loaded

    def test_save_patterns_normalizes_strips_and_deduplicates(self):
        ok = self.mgr.save_quality_review_script_ignore_patterns(
            self.project_path,
            ["  (?i)\\bAPI\\b  ", r"(?i)\bAPI\b", "", "   ", r"(?i)\bJSON\b"],
        )
        assert ok
        loaded = self.mgr.get_quality_review_script_ignore_patterns(self.project_path)
        assert [r"(?i)\bAPI\b", r"(?i)\bJSON\b"] == loaded

    def test_use_builtin_exclusions_defaults_to_true(self):
        value = self.mgr.get_quality_review_use_builtin_exclusions(self.project_path)
        assert value is True

    def test_use_builtin_exclusions_save_false_and_reload(self):
        ok = self.mgr.save_quality_review_use_builtin_exclusions(self.project_path, False)
        assert ok
        assert self.mgr.get_quality_review_use_builtin_exclusions(self.project_path) is False

    def test_use_builtin_exclusions_save_true_and_reload(self):
        self.mgr.save_quality_review_use_builtin_exclusions(self.project_path, False)
        ok = self.mgr.save_quality_review_use_builtin_exclusions(self.project_path, True)
        assert ok
        assert self.mgr.get_quality_review_use_builtin_exclusions(self.project_path) is True

    def test_use_builtin_exclusions_independent_per_project(self):
        other_path = "C:/tmp/project-b"
        self.mgr.save_quality_review_use_builtin_exclusions(self.project_path, False)
        assert self.mgr.get_quality_review_use_builtin_exclusions(other_path) is True

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
        assert "quality_review_script_ignore_patterns" in cfg
        assert "quality_review_script_ignore_patterns_initialized" in cfg
        assert "quality_review_latin_ignore_patterns" not in cfg
        assert "quality_review_latin_ignore_patterns_initialized" not in cfg


class TestQualityReviewQuoteStyleOverrideSettings:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_path = "C:/tmp/project-a"
        self.mgr = SettingsManager()
        self.mgr.settings_file = Path(self._tmp.name) / "settings.json"
        self.mgr.settings_file.parent.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        self._tmp.cleanup()

    def test_defaults_to_empty_dict(self):
        assert self.mgr.get_quality_review_quote_style_overrides(self.project_path) == {}

    def test_save_and_reload(self):
        ok = self.mgr.save_quality_review_quote_style_overrides(
            self.project_path, {"de": "straight", "fr": "curly"}
        )
        assert ok
        loaded = self.mgr.get_quality_review_quote_style_overrides(self.project_path)
        assert loaded == {"de": "straight", "fr": "curly"}

    def test_save_strips_and_drops_blank_entries(self):
        ok = self.mgr.save_quality_review_quote_style_overrides(
            self.project_path,
            {" de ": " straight ", "": "curly", "es": "", "fr": "guillemets"},
        )
        assert ok
        loaded = self.mgr.get_quality_review_quote_style_overrides(self.project_path)
        assert loaded == {"de": "straight", "fr": "guillemets"}

    def test_clear_removes_overrides(self):
        self.mgr.save_quality_review_quote_style_overrides(self.project_path, {"de": "straight"})
        ok = self.mgr.clear_quality_review_quote_style_overrides(self.project_path)
        assert ok
        assert self.mgr.get_quality_review_quote_style_overrides(self.project_path) == {}

    def test_independent_per_project(self):
        other_path = "C:/tmp/project-b"
        self.mgr.save_quality_review_quote_style_overrides(self.project_path, {"de": "straight"})
        assert self.mgr.get_quality_review_quote_style_overrides(other_path) == {}

    def test_non_dict_stored_value_is_treated_as_empty(self):
        with open(self.mgr.settings_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "project_settings": {
                        self.project_path: {"quality_review_quote_style_overrides": ["bad"]}
                    }
                },
                f,
            )
        assert self.mgr.get_quality_review_quote_style_overrides(self.project_path) == {}


class TestQualityReviewLlmMaxCatalogTokens:
    """Catalog review defaults to a large-context cloud model (DEFAULT_LLM_MODEL_MULTI_LOCALE),
    so the default catalog-slice token budget should be generous (16000), not the old
    conservative-for-local-models value (2400)."""

    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_path = "C:/tmp/project-a"
        self.mgr = SettingsManager()
        self.mgr.settings_file = Path(self._tmp.name) / "settings.json"
        self.mgr.settings_file.parent.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        self._tmp.cleanup()

    def test_default_is_16000(self):
        assert self.mgr.get_quality_review_llm_max_catalog_tokens(self.project_path) == 16000
        assert SettingsManager.DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS == 16000

    def test_translation_quality_review_module_constant_matches(self):
        from i18n.translation_quality_review import DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS

        assert DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS == 16000

    def test_save_and_reload(self):
        ok = self.mgr.save_quality_review_llm_max_catalog_tokens(self.project_path, 40000)
        assert ok
        assert self.mgr.get_quality_review_llm_max_catalog_tokens(self.project_path) == 40000

    def test_clamped_to_new_higher_ceiling(self):
        self.mgr.save_quality_review_llm_max_catalog_tokens(self.project_path, 500000)
        assert self.mgr.get_quality_review_llm_max_catalog_tokens(self.project_path) == 100000

    def test_clamped_to_floor(self):
        self.mgr.save_quality_review_llm_max_catalog_tokens(self.project_path, 1)
        assert self.mgr.get_quality_review_llm_max_catalog_tokens(self.project_path) == 128

    def test_invalid_saved_value_falls_back_to_default(self):
        with open(self.mgr.settings_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "project_settings": {
                        self.project_path: {"quality_review_llm_max_catalog_tokens": "not-a-number"}
                    }
                },
                f,
            )
        assert self.mgr.get_quality_review_llm_max_catalog_tokens(self.project_path) == 16000
