from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from utils.settings_manager import SettingsManager


def get_default_script_ignore_patterns() -> tuple[str, ...]:
    """Canonical default ignore-pattern set used by script checks."""
    return tuple(SettingsManager.get_default_quality_review_script_ignore_patterns())


_ISOLATED_ENV_VARS = (
    "PY_I18N_MANAGER_SETTINGS_PATH",
    "PY_I18N_MANAGER_APP_INFO_CACHE_PATH",
    "PY_I18N_MANAGER_CONFIG_DIR",
)


@contextmanager
def isolated_settings_and_cache_env(
    *,
    prefix: str = ".tmp_test_env_",
    base_dir: Path | None = None,
    keep_tmp: bool | None = None,
) -> Iterator[dict[str, str]]:
    """Temporarily point settings/app-cache/config paths at a tests-local temp directory.

    Isolates three things that would otherwise touch real, shared state:
    - :class:`~utils.settings_manager.SettingsManager` (``~/.i18n_manager/settings.json``)
    - :class:`~utils.app_info_cache.AppInfoCache`
    - the module-level ``utils.config.config_manager`` singleton, which by default reads/writes
      ``configs/user_config.json`` *relative to the process cwd* - i.e. the real repo's config
      file. Without this, any test exercising a "global" (non-project-path) settings save (e.g.
      ``SettingsManager.save_llm_model(..., project_path=None)``) would silently mutate that file.

    ``config_manager`` is swapped for a fresh instance pointed at the temp dir for the duration of
    the context, then restored - callers that do ``from utils.config import config_manager``
    inside a function body (the pattern used throughout this codebase) pick up the swap
    automatically since that re-resolves the module attribute on every call.

    Set ``keep_tmp=True`` (or env ``PY_I18N_MANAGER_KEEP_TEST_TMP=1``) to retain
    the directory after test teardown for debugging.
    """
    target_base = base_dir or Path(__file__).parent
    if keep_tmp is None:
        keep_tmp = os.environ.get("PY_I18N_MANAGER_KEEP_TEST_TMP", "").strip() == "1"

    if keep_tmp:
        root = Path(tempfile.mkdtemp(dir=str(target_base), prefix=prefix))
        temp_dir_ctx = None
    else:
        temp_dir_ctx = tempfile.TemporaryDirectory(dir=str(target_base), prefix=prefix)
        root = Path(temp_dir_ctx.name)

    settings_path = str(root / "settings.json")
    app_cache_path = str(root / "app_info_cache.json")
    config_dir = root / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Mirror the real default_config.json so an isolated ConfigManager still sees the app's real
    # defaults (translation.default_locale, llm_prompt_template, etc.) - only user_config.json
    # (the writable half) is isolated/absent.
    real_default_config = Path(__file__).parent.parent / "configs" / "default_config.json"
    if real_default_config.exists():
        shutil.copy(real_default_config, config_dir / "default_config.json")

    old_env = {name: os.environ.get(name) for name in _ISOLATED_ENV_VARS}
    os.environ["PY_I18N_MANAGER_SETTINGS_PATH"] = settings_path
    os.environ["PY_I18N_MANAGER_APP_INFO_CACHE_PATH"] = app_cache_path
    os.environ["PY_I18N_MANAGER_CONFIG_DIR"] = str(config_dir)

    import utils.config as config_module

    old_config_manager = config_module.config_manager
    config_module.config_manager = config_module.ConfigManager()
    try:
        yield {
            "root": str(root),
            "settings_path": settings_path,
            "app_cache_path": app_cache_path,
            "config_dir": str(config_dir),
            "kept_tmp": "1" if keep_tmp else "0",
        }
    finally:
        config_module.config_manager = old_config_manager
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if temp_dir_ctx is not None:
            temp_dir_ctx.cleanup()
