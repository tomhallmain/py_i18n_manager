"""utils/app_paths.py: bundled resources and the app's own log directory."""

import os
import sys

from utils import app_paths
from utils.config import ConfigManager
from utils.translations import I18N
from utils.version import VERSION_FILE


def test_checkout_is_not_a_build():
    assert app_paths.IS_BUILD is False


def test_resource_root_is_the_repo_in_a_checkout():
    assert os.path.isfile(app_paths.resource_path("app.py"))
    assert os.path.isfile(app_paths.resource_path(VERSION_FILE))
    assert os.path.isdir(app_paths.resource_path("locale"))
    assert os.path.isfile(app_paths.resource_path("configs", "default_config.json"))
    assert os.path.isfile(app_paths.resource_path("assets", "icon.svg"))


def test_resource_path_follows_the_resource_root(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "RESOURCE_ROOT", str(tmp_path))
    assert app_paths.resource_path("locale", "en") == os.path.join(str(tmp_path), "locale", "en")


def test_translations_load_from_the_bundled_locale_dir():
    assert I18N.localedir == app_paths.resource_path("locale")


def test_default_config_is_the_bundled_one_whatever_the_cwd(monkeypatch, tmp_path):
    """A build is started from any directory; the defaults must not depend on it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PY_I18N_MANAGER_CONFIG_DIR", str(tmp_path / "configs"))
    manager = ConfigManager()
    assert str(manager.default_config_path) == app_paths.resource_path("configs", "default_config.json")
    assert manager.get("files.settings_file") == "settings.json"
    assert manager.user_config_path == tmp_path / "configs" / "user_config.json"


def test_user_logs_dir_is_under_the_per_user_data_dir():
    if sys.platform == "win32":
        base = os.environ["APPDATA"]
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    assert app_paths.user_logs_dir() == os.path.join(base, "py_i18n_manager", "logs")


# The app data dir

def test_app_data_dir_defaults_to_dot_i18n_manager_in_home(monkeypatch):
    monkeypatch.delenv(app_paths.DATA_DIR_ENV, raising=False)
    assert app_paths.app_data_dir() == os.path.join(os.path.expanduser("~"), ".i18n_manager")
    assert app_paths.app_data_dir() == app_paths.default_app_data_dir()


def test_app_data_dir_follows_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv(app_paths.DATA_DIR_ENV, str(tmp_path))
    assert app_paths.app_data_dir() == str(tmp_path)
    assert app_paths.user_data_path("configs", "user_config.json") == str(tmp_path / "configs" / "user_config.json")


def test_a_blank_override_is_ignored(monkeypatch):
    monkeypatch.setenv(app_paths.DATA_DIR_ENV, "  ")
    assert app_paths.app_data_dir() == app_paths.default_app_data_dir()


def test_writers_use_the_data_dir(monkeypatch, tmp_path):
    from utils.app_info_cache import AppInfoCache
    from utils.settings_manager import SettingsManager

    monkeypatch.setenv(app_paths.DATA_DIR_ENV, str(tmp_path))
    for name in (app_paths.SETTINGS_PATH_ENV, app_paths.APP_INFO_CACHE_PATH_ENV, app_paths.CONFIG_DIR_ENV):
        monkeypatch.delenv(name, raising=False)
    # AppInfoCache sets its class-level path too; monkeypatch puts it back.
    monkeypatch.setattr(AppInfoCache, "JSON_LOC", AppInfoCache.JSON_LOC)
    assert ConfigManager().user_config_path == tmp_path / "configs" / "user_config.json"
    assert AppInfoCache().JSON_LOC == str(tmp_path / "app_info_cache.json")
    assert SettingsManager().settings_file == tmp_path / "settings.json"


def test_a_file_override_wins_over_the_data_dir(monkeypatch, tmp_path):
    from utils.app_info_cache import AppInfoCache
    from utils.settings_manager import SettingsManager

    monkeypatch.setenv(app_paths.DATA_DIR_ENV, str(tmp_path / "data"))
    monkeypatch.setenv(app_paths.SETTINGS_PATH_ENV, str(tmp_path / "s.json"))
    monkeypatch.setenv(app_paths.APP_INFO_CACHE_PATH_ENV, str(tmp_path / "c.json"))
    monkeypatch.setenv(app_paths.CONFIG_DIR_ENV, str(tmp_path / "cfg"))
    monkeypatch.setattr(AppInfoCache, "JSON_LOC", AppInfoCache.JSON_LOC)
    assert ConfigManager().user_config_path == tmp_path / "cfg" / "user_config.json"
    assert AppInfoCache().JSON_LOC == str(tmp_path / "c.json")
    assert SettingsManager().settings_file == tmp_path / "s.json"


def test_tests_stay_out_of_the_real_data_dir_and_the_repo():
    """The root conftest.py points the data dir at a temp dir before anything is imported."""
    import utils.app_info_cache as app_info_cache_module
    import utils.config as config_module
    from i18n import llm_catalog_review
    from utils.settings_manager import SettingsManager

    assert app_paths.app_data_dir() != app_paths.default_app_data_dir()
    written = [
        str(config_module.config_manager.user_config_path),
        app_info_cache_module.app_info_cache.JSON_LOC,
        str(SettingsManager().settings_file),
        str(llm_catalog_review.REVIEW_LOG_ROOT),
    ]
    legacy = [
        app_paths.resource_path("configs", "user_config.json"),
        app_paths.resource_path("app_info_cache.json"),
        app_paths.resource_path("llm_review_output"),
    ]
    for path in written:
        path = os.path.abspath(path)
        assert not path.startswith(app_paths.default_app_data_dir() + os.sep), path
        assert path not in legacy, path
