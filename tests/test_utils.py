from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from utils.settings_manager import SettingsManager


def get_default_script_ignore_patterns() -> tuple[str, ...]:
    """Canonical default ignore-pattern set used by script checks."""
    return tuple(SettingsManager.get_default_quality_review_script_ignore_patterns())


@contextmanager
def isolated_settings_and_cache_env(
    *,
    prefix: str = ".tmp_test_env_",
    base_dir: Path | None = None,
    keep_tmp: bool | None = None,
) -> Iterator[dict[str, str]]:
    """Temporarily point settings/app cache paths at a tests-local temp directory.

    Set ``keep_tmp=True`` (or env ``PY_I18N_MANAGER_KEEP_TEST_TMP=1``) to retain
    the directory after test teardown for debugging.
    """
    target_base = base_dir or Path(__file__).parent
    if keep_tmp is None:
        keep_tmp = os.environ.get("PY_I18N_MANAGER_KEEP_TEST_TMP", "").strip() == "1"

    if keep_tmp:
        root = Path(tempfile.mkdtemp(dir=str(target_base), prefix=prefix))
        settings_path = str(root / "settings.json")
        app_cache_path = str(root / "app_info_cache.json")

        old_settings = os.environ.get("PY_I18N_MANAGER_SETTINGS_PATH")
        old_cache = os.environ.get("PY_I18N_MANAGER_APP_INFO_CACHE_PATH")
        os.environ["PY_I18N_MANAGER_SETTINGS_PATH"] = settings_path
        os.environ["PY_I18N_MANAGER_APP_INFO_CACHE_PATH"] = app_cache_path
        try:
            yield {
                "root": str(root),
                "settings_path": settings_path,
                "app_cache_path": app_cache_path,
                "kept_tmp": "1",
            }
        finally:
            if old_settings is None:
                os.environ.pop("PY_I18N_MANAGER_SETTINGS_PATH", None)
            else:
                os.environ["PY_I18N_MANAGER_SETTINGS_PATH"] = old_settings
            if old_cache is None:
                os.environ.pop("PY_I18N_MANAGER_APP_INFO_CACHE_PATH", None)
            else:
                os.environ["PY_I18N_MANAGER_APP_INFO_CACHE_PATH"] = old_cache
        return

    with tempfile.TemporaryDirectory(dir=str(target_base), prefix=prefix) as tmp:
        root = Path(tmp)
        settings_path = str(root / "settings.json")
        app_cache_path = str(root / "app_info_cache.json")

        old_settings = os.environ.get("PY_I18N_MANAGER_SETTINGS_PATH")
        old_cache = os.environ.get("PY_I18N_MANAGER_APP_INFO_CACHE_PATH")
        os.environ["PY_I18N_MANAGER_SETTINGS_PATH"] = settings_path
        os.environ["PY_I18N_MANAGER_APP_INFO_CACHE_PATH"] = app_cache_path
        try:
            yield {
                "root": str(root),
                "settings_path": settings_path,
                "app_cache_path": app_cache_path,
                "kept_tmp": "0",
            }
        finally:
            if old_settings is None:
                os.environ.pop("PY_I18N_MANAGER_SETTINGS_PATH", None)
            else:
                os.environ["PY_I18N_MANAGER_SETTINGS_PATH"] = old_settings
            if old_cache is None:
                os.environ.pop("PY_I18N_MANAGER_APP_INFO_CACHE_PATH", None)
            else:
                os.environ["PY_I18N_MANAGER_APP_INFO_CACHE_PATH"] = old_cache
