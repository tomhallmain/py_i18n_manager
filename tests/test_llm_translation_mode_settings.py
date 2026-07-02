"""Tests for LLMTranslationMode and its SettingsManager-backed mode/model settings.

These exercise the "Translate All (LLM)" mode switch: one request per (key, locale) pair
(PER_LOCALE, the original behavior) vs. one request per key covering every missing locale at
once (PER_KEY_ALL_LOCALES). The settings tests below deliberately hit both the project-override
path and the *global* (project_path=None) path, which is what makes them a useful check on
``isolated_settings_and_cache_env``'s config isolation: the global path writes through
``utils.config.config_manager``, which by default points at the real repo's
``configs/user_config.json``.
"""

from pathlib import Path

from test_utils import isolated_settings_and_cache_env
from utils.globals import LLMTranslationMode
from utils.settings_manager import SettingsManager


class TestLLMTranslationModeEnum:
    def test_from_value_accepts_known_strings(self):
        assert LLMTranslationMode.from_value("per_locale") is LLMTranslationMode.PER_LOCALE
        assert (
            LLMTranslationMode.from_value("per_key_all_locales")
            is LLMTranslationMode.PER_KEY_ALL_LOCALES
        )

    def test_from_value_passes_through_enum_member(self):
        assert (
            LLMTranslationMode.from_value(LLMTranslationMode.PER_KEY_ALL_LOCALES)
            is LLMTranslationMode.PER_KEY_ALL_LOCALES
        )

    def test_from_value_falls_back_to_per_locale_for_unknown_or_none(self):
        assert LLMTranslationMode.from_value(None) is LLMTranslationMode.PER_LOCALE
        assert LLMTranslationMode.from_value("bogus_mode") is LLMTranslationMode.PER_LOCALE
        assert LLMTranslationMode.from_value(123) is LLMTranslationMode.PER_LOCALE

    def test_from_value_honors_explicit_default(self):
        assert (
            LLMTranslationMode.from_value("bogus", default=LLMTranslationMode.PER_KEY_ALL_LOCALES)
            is LLMTranslationMode.PER_KEY_ALL_LOCALES
        )

    def test_display_names_are_distinct_and_nonempty(self):
        names = {mode.get_display_name() for mode in LLMTranslationMode}
        assert len(names) == 2
        assert all(names)

    def test_str_enum_equals_its_plain_string_value(self):
        # str, Enum mixin: settings persist mode.value directly as plain, JSON-friendly text.
        assert LLMTranslationMode.PER_LOCALE == "per_locale"
        assert LLMTranslationMode.PER_KEY_ALL_LOCALES == "per_key_all_locales"


class TestLLMTranslationModeAndModelSettings:
    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_llm_mode_settings_")
        self._env_ctx.__enter__()
        self.settings_manager = SettingsManager()
        self.project_path = "C:/tmp/llm-mode-settings-test-project"

    def teardown_method(self):
        self._env_ctx.__exit__(None, None, None)

    # --- Mode -----------------------------------------------------------------

    def test_default_mode_is_per_locale(self):
        assert self.settings_manager.get_llm_translation_mode() is LLMTranslationMode.PER_LOCALE
        assert (
            self.settings_manager.get_llm_translation_mode(self.project_path)
            is LLMTranslationMode.PER_LOCALE
        )

    def test_global_mode_round_trip(self):
        assert self.settings_manager.save_llm_translation_mode(
            LLMTranslationMode.PER_KEY_ALL_LOCALES
        )
        assert (
            self.settings_manager.get_llm_translation_mode()
            is LLMTranslationMode.PER_KEY_ALL_LOCALES
        )
        # A project with no override falls back to the new global default.
        assert (
            self.settings_manager.get_llm_translation_mode(self.project_path)
            is LLMTranslationMode.PER_KEY_ALL_LOCALES
        )

    def test_project_override_takes_precedence_over_global(self):
        self.settings_manager.save_llm_translation_mode(LLMTranslationMode.PER_KEY_ALL_LOCALES)
        self.settings_manager.save_llm_translation_mode(
            LLMTranslationMode.PER_LOCALE, self.project_path
        )
        assert (
            self.settings_manager.get_llm_translation_mode()
            is LLMTranslationMode.PER_KEY_ALL_LOCALES
        )
        assert (
            self.settings_manager.get_llm_translation_mode(self.project_path)
            is LLMTranslationMode.PER_LOCALE
        )

    def test_has_and_clear_project_mode_override(self):
        assert not self.settings_manager.has_project_llm_translation_mode(self.project_path)
        self.settings_manager.save_llm_translation_mode(
            LLMTranslationMode.PER_KEY_ALL_LOCALES, self.project_path
        )
        assert self.settings_manager.has_project_llm_translation_mode(self.project_path)

        assert self.settings_manager.clear_project_llm_translation_mode(self.project_path)
        assert not self.settings_manager.has_project_llm_translation_mode(self.project_path)
        assert (
            self.settings_manager.get_llm_translation_mode(self.project_path)
            is LLMTranslationMode.PER_LOCALE
        )

    def test_save_llm_translation_mode_accepts_plain_string(self):
        assert self.settings_manager.save_llm_translation_mode("per_key_all_locales")
        assert (
            self.settings_manager.get_llm_translation_mode()
            is LLMTranslationMode.PER_KEY_ALL_LOCALES
        )

    # --- Models -----------------------------------------------------------------

    def test_default_models(self):
        assert self.settings_manager.get_llm_model() == SettingsManager.DEFAULT_LLM_MODEL
        assert (
            self.settings_manager.get_llm_model_multi_locale()
            == SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE
        )

    def test_multi_locale_model_default_is_a_distinct_cloud_model(self):
        # Regression: per-key mode must not silently reuse the (often local/unreliable-at-JSON)
        # single-locale model default.
        assert SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE != SettingsManager.DEFAULT_LLM_MODEL
        assert "cloud" in SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE

    def test_global_model_round_trip(self):
        assert self.settings_manager.save_llm_model("qwen3:8b")
        assert self.settings_manager.get_llm_model() == "qwen3:8b"

        assert self.settings_manager.save_llm_model_multi_locale("gpt-oss:120b-cloud")
        assert self.settings_manager.get_llm_model_multi_locale() == "gpt-oss:120b-cloud"

    def test_project_model_override_and_clear(self):
        self.settings_manager.save_llm_model("global-model", None)
        self.settings_manager.save_llm_model("project-model", self.project_path)
        assert self.settings_manager.get_llm_model() == "global-model"
        assert self.settings_manager.get_llm_model(self.project_path) == "project-model"
        assert self.settings_manager.has_project_llm_model(self.project_path)

        assert self.settings_manager.clear_project_llm_model(self.project_path)
        assert not self.settings_manager.has_project_llm_model(self.project_path)
        assert self.settings_manager.get_llm_model(self.project_path) == "global-model"

    def test_project_multi_locale_model_override_and_clear(self):
        self.settings_manager.save_llm_model_multi_locale("global-cloud-model", None)
        self.settings_manager.save_llm_model_multi_locale("project-cloud-model", self.project_path)
        assert self.settings_manager.get_llm_model_multi_locale() == "global-cloud-model"
        assert (
            self.settings_manager.get_llm_model_multi_locale(self.project_path)
            == "project-cloud-model"
        )
        assert self.settings_manager.has_project_llm_model_multi_locale(self.project_path)

        assert self.settings_manager.clear_project_llm_model_multi_locale(self.project_path)
        assert not self.settings_manager.has_project_llm_model_multi_locale(self.project_path)
        assert (
            self.settings_manager.get_llm_model_multi_locale(self.project_path)
            == "global-cloud-model"
        )

    def test_blank_model_name_falls_back_to_default(self):
        assert self.settings_manager.save_llm_model("   ")
        assert self.settings_manager.get_llm_model() == SettingsManager.DEFAULT_LLM_MODEL

        assert self.settings_manager.save_llm_model_multi_locale("")
        assert (
            self.settings_manager.get_llm_model_multi_locale()
            == SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE
        )

    def test_global_saves_do_not_leak_into_real_repo_config(self):
        """Guards the isolation fix itself: a global save must never land in the real repo config."""
        marker = "should-not-leak-into-repo-config"
        self.settings_manager.save_llm_model(marker)
        self.settings_manager.save_llm_translation_mode(LLMTranslationMode.PER_KEY_ALL_LOCALES)

        real_user_config = Path(__file__).parent.parent / "configs" / "user_config.json"
        if real_user_config.exists():
            assert marker not in real_user_config.read_text(encoding="utf-8")


class TestLLMPromptTemplateMultiLocaleSettings:
    """The PER_KEY_ALL_LOCALES prompt template - separate storage from the single-locale one,
    same global/project-override pattern."""

    def setup_method(self):
        self._env_ctx = isolated_settings_and_cache_env(prefix=".tmp_llm_prompt_multi_locale_")
        self._env_ctx.__enter__()
        self.settings_manager = SettingsManager()
        self.project_path = "C:/tmp/llm-prompt-multi-locale-test-project"

    def teardown_method(self):
        self._env_ctx.__exit__(None, None, None)

    def test_default_is_distinct_from_single_locale_default(self):
        default_multi = self.settings_manager.get_llm_prompt_template_multi_locale()
        default_single = self.settings_manager.get_llm_prompt_template()
        assert default_multi != default_single
        assert default_multi == SettingsManager.get_default_llm_prompt_template_multi_locale()

    def test_default_multi_locale_template_requires_target_locales_variable(self):
        # Regression: this variable is what makes the per-key batch response parseable as one
        # JSON key per locale - it must survive in the shipped default.
        assert "{target_locales}" in SettingsManager.get_default_llm_prompt_template_multi_locale()
        assert "{source_text}" in SettingsManager.get_default_llm_prompt_template_multi_locale()

    def test_global_round_trip(self):
        custom = "Translate {source_text} into {target_locales} from {source_locale}. {context}"
        assert self.settings_manager.save_llm_prompt_template_multi_locale(custom)
        assert self.settings_manager.get_llm_prompt_template_multi_locale() == custom

    def test_project_override_takes_precedence_and_clears_back_to_global(self):
        global_template = "GLOBAL {source_text} {target_locales} {source_locale} {context}"
        project_template = "PROJECT {source_text} {target_locales} {source_locale} {context}"
        self.settings_manager.save_llm_prompt_template_multi_locale(global_template)
        self.settings_manager.save_llm_prompt_template_multi_locale(project_template, self.project_path)

        assert self.settings_manager.get_llm_prompt_template_multi_locale() == global_template
        assert (
            self.settings_manager.get_llm_prompt_template_multi_locale(self.project_path)
            == project_template
        )
        assert self.settings_manager.has_project_llm_prompt_template_multi_locale(self.project_path)

        assert self.settings_manager.clear_project_llm_prompt_template_multi_locale(self.project_path)
        assert not self.settings_manager.has_project_llm_prompt_template_multi_locale(self.project_path)
        assert (
            self.settings_manager.get_llm_prompt_template_multi_locale(self.project_path)
            == global_template
        )

    def test_independent_from_single_locale_template_storage(self):
        """Saving one template must not affect the other."""
        self.settings_manager.save_llm_prompt_template("SINGLE {source_text} {target_locale}")
        self.settings_manager.save_llm_prompt_template_multi_locale(
            "MULTI {source_text} {target_locales}"
        )
        assert self.settings_manager.get_llm_prompt_template() == "SINGLE {source_text} {target_locale}"
        assert (
            self.settings_manager.get_llm_prompt_template_multi_locale()
            == "MULTI {source_text} {target_locales}"
        )


class TestLLMPromptVariablesPerMode:
    def test_single_locale_variables_use_singular_target_locale(self):
        names = {v["name"] for v in SettingsManager.get_llm_prompt_variables(multi_locale=False)}
        assert "{target_locale}" in names
        assert "{target_locales}" not in names

    def test_multi_locale_variables_use_plural_target_locales(self):
        names = {v["name"] for v in SettingsManager.get_llm_prompt_variables(multi_locale=True)}
        assert "{target_locales}" in names
        assert "{target_locale}" not in names

    def test_both_variants_include_shared_variables(self):
        for multi_locale in (False, True):
            names = {v["name"] for v in SettingsManager.get_llm_prompt_variables(multi_locale=multi_locale)}
            assert "{source_locale}" in names
            assert "{source_text}" in names
            assert "{context}" in names
