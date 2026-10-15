"""Where the app's own files live.

Bundled, read-only files (locale, default config, icon) resolve through
``resource_path``: the repo in a checkout, the unpack folder in a compiled
build, which places them at the same relative paths. Nothing the app writes
goes under the resource root: in a onefile build it is a fresh folder per
build. Written files go under ``app_data_dir()`` (``~/.i18n_manager``), in
checkouts and builds alike, through ``user_data_path``; its first call in a
process moves the user files earlier versions left in the repo
(``utils/legacy_user_files.py``). No app imports at load time: the logger
resolves its directory here.
"""

import os
import sys

#: True in a Nuitka-compiled build.
IS_BUILD = "__compiled__" in globals()

RESOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Relocates the whole app data dir (tests, the smoke test).
DATA_DIR_ENV = "PY_I18N_MANAGER_DATA_DIR"
#: Relocate single files; each wins over the data dir for its file.
SETTINGS_PATH_ENV = "PY_I18N_MANAGER_SETTINGS_PATH"
APP_INFO_CACHE_PATH_ENV = "PY_I18N_MANAGER_APP_INFO_CACHE_PATH"
CONFIG_DIR_ENV = "PY_I18N_MANAGER_CONFIG_DIR"
#: While any of these is set, no legacy files are moved: the user's files
#: belong in the real data dir, not wherever the variable points.
OVERRIDE_ENVS = (DATA_DIR_ENV, SETTINGS_PATH_ENV, APP_INFO_CACHE_PATH_ENV, CONFIG_DIR_ENV)


def resource_path(*parts: str) -> str:
    """Absolute path of a bundled, read-only file."""
    return os.path.join(RESOURCE_ROOT, *parts)


def env_override(name: str) -> str:
    """The value of override variable *name*, or "" when unset or blank."""
    return os.environ.get(name, "").strip()


def default_app_data_dir() -> str:
    """The app data dir without overrides: ``~/.i18n_manager``."""
    return os.path.join(os.path.expanduser("~"), ".i18n_manager")


def app_data_dir() -> str:
    """Root of the per-user app data dir (not created here)."""
    return env_override(DATA_DIR_ENV) or default_app_data_dir()


def user_data_path(*parts: str) -> str:
    """Path of a file or folder the app writes, under app_data_dir() (not
    created here). Moves legacy user files in first, once per process."""
    from utils.legacy_user_files import migrate_once

    migrate_once()
    return os.path.join(app_data_dir(), *parts)


def user_logs_dir() -> str:
    """This app's own log directory (not created here):
    ``%APPDATA%\\py_i18n_manager\\logs`` on Windows,
    ``~/.local/share/py_i18n_manager/logs`` elsewhere."""
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    else:
        base = os.path.expanduser("~/.local/share")
    return os.path.join(base, "py_i18n_manager", "logs")
