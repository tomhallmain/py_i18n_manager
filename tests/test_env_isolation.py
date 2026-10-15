"""Tests for tests/test_utils.isolated_settings_and_cache_env's isolation guarantees.

utils.config.config_manager is a process-wide singleton holding configs/user_config.json. Any test
that saves a "global" setting (project_path=None) - including the LLM translation-mode/model
settings - goes through it, so each test needs its own. The root conftest.py keeps all of them out
of the real app data dir (tests/test_app_paths.py checks that).
"""

import os
from pathlib import Path

from test_utils import isolated_settings_and_cache_env


def test_isolated_env_points_config_manager_at_temp_dir():
    with isolated_settings_and_cache_env(prefix=".tmp_env_isolation_") as paths:
        import utils.config as config_module

        assert str(config_module.config_manager.config_dir) == paths["config_dir"]
        assert os.environ["PY_I18N_MANAGER_CONFIG_DIR"] == paths["config_dir"]
        assert os.environ["PY_I18N_MANAGER_SETTINGS_PATH"] == paths["settings_path"]
        assert os.environ["PY_I18N_MANAGER_APP_INFO_CACHE_PATH"] == paths["app_cache_path"]


def test_isolated_config_manager_writes_stay_out_of_real_repo_config():
    marker = "isolated-test-marker-value"
    with isolated_settings_and_cache_env(prefix=".tmp_env_isolation_"):
        import utils.config as config_module

        assert config_module.config_manager.set("translation.llm_model", marker)
        assert config_module.config_manager.user_config_path.exists()
        assert config_module.config_manager.get("translation.llm_model") == marker

    real_user_config = Path(__file__).parent.parent / "configs" / "user_config.json"
    if real_user_config.exists():
        assert marker not in real_user_config.read_text(encoding="utf-8")


def test_isolated_config_manager_still_sees_real_app_defaults():
    """The bundled default_config.json is read whatever the config dir override says."""
    with isolated_settings_and_cache_env(prefix=".tmp_env_isolation_"):
        import utils.config as config_module

        # From the real configs/default_config.json; proves it was actually read, not just an
        # absent file silently returning None for everything.
        assert config_module.config_manager.get("files.settings_file") == "settings.json"


def test_config_manager_and_env_vars_restored_after_context_exit():
    import utils.config as config_module

    original_config_manager = config_module.config_manager
    with isolated_settings_and_cache_env(prefix=".tmp_env_isolation_"):
        assert config_module.config_manager is not original_config_manager

    assert config_module.config_manager is original_config_manager
    assert "PY_I18N_MANAGER_CONFIG_DIR" not in os.environ
    assert "PY_I18N_MANAGER_SETTINGS_PATH" not in os.environ
    assert "PY_I18N_MANAGER_APP_INFO_CACHE_PATH" not in os.environ


def test_nested_context_restores_outer_values():
    """Prior env values (e.g. from an outer isolated context) are restored, not just cleared."""
    with isolated_settings_and_cache_env(prefix=".tmp_env_isolation_outer_") as outer_paths:
        with isolated_settings_and_cache_env(prefix=".tmp_env_isolation_inner_") as inner_paths:
            assert os.environ["PY_I18N_MANAGER_CONFIG_DIR"] == inner_paths["config_dir"]
        assert os.environ["PY_I18N_MANAGER_CONFIG_DIR"] == outer_paths["config_dir"]
