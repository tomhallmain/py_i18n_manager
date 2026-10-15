"""Removes folders older builds unpacked to.

The onefile build unpacks to ``~/.i18n_manager/unpacked/i18n-manager-<build id>``
(``build_exe.py``), one folder per build, and Nuitka never removes them. A
build runs its executable from its own folder, so a folder holding the
executable of a running process is skipped. On Windows each folder is also
renamed before it is deleted, which Windows refuses while a running exe holds
files in it; macOS and Linux allow that rename, so there the process check
alone decides, and nothing is removed when processes cannot be listed.
"""

import os
import shutil
import sys
from typing import Optional

from utils.app_paths import IS_BUILD, RESOURCE_ROOT
from utils.logging_setup import get_logger

logger = get_logger("utils.unpack_cleanup")

UNPACK_PARENT_NAME = "unpacked"
UNPACK_DIR_PREFIX = "i18n-manager-"
_REMOVING_SUFFIX = ".removing"
_IS_WINDOWS = sys.platform == "win32"


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _long_path(path: str) -> str:
    """*path* with Windows 8.3 short names (``I18N-M~1``) expanded. A build's
    ``__file__`` can hold the short name of its unpack folder, which
    ``os.listdir`` never returns."""
    if not _IS_WINDOWS:
        return path
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetLongPathNameW(path, buffer, len(buffer)):
            return buffer.value
    except (AttributeError, OSError):
        pass
    return path


def _is_same_folder(path: str, other: str) -> bool:
    try:
        return os.path.samefile(path, other)
    except OSError:
        return _normalize(path) == _normalize(other)


def _running_executables() -> Optional[set]:
    """Normalized executable paths of the running processes this user can
    see, or None when they cannot be listed."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        # A process this user may not inspect reports exe as None.
        return {_normalize(p.info["exe"]) for p in psutil.process_iter(["exe"]) if p.info.get("exe")}
    except Exception as e:
        logger.warning(f"Could not list running processes: {e}")
        return None


def _holds_running_executable(folder: str, executables: set) -> bool:
    prefix = _normalize(folder) + os.sep
    return any(exe.startswith(prefix) for exe in executables)


def _is_unpack_dir(name: str) -> bool:
    return name.startswith(UNPACK_DIR_PREFIX)


def remove_stale_unpack_dirs() -> list:
    """Delete the running build's sibling build folders; returns the paths removed."""
    if not IS_BUILD:
        return []
    current = _long_path(RESOURCE_ROOT)
    parent = os.path.dirname(_normalize(current))
    if (os.path.basename(parent) != _normalize(UNPACK_PARENT_NAME)
            or not _is_unpack_dir(os.path.basename(os.path.normpath(current)))):
        logger.warning(f"Not cleaning up old build folders: {current} is not an unpack folder")
        return []
    executables = _running_executables()
    if executables is None:
        if not _IS_WINDOWS:
            logger.info("Not cleaning up old build folders: running processes cannot be listed")
            return []
        executables = set()  # the rename alone guards running builds
    try:
        names = sorted(os.listdir(parent))
    except OSError as e:
        logger.error(f"Could not list {parent}: {e}")
        return []
    removed = []
    for name in names:
        path = os.path.join(parent, name)
        if not _is_unpack_dir(name) or not os.path.isdir(path) or _is_same_folder(path, current):
            continue
        if _holds_running_executable(path, executables):
            logger.info(f"Not removing {path}: a running build uses it")
            continue
        if not name.endswith(_REMOVING_SUFFIX):
            # Marks the folder so a delete cut short is finished at the next
            # start; on Windows, failing here also means it is in use.
            renamed = path + _REMOVING_SUFFIX
            try:
                os.rename(path, renamed)
            except OSError as e:
                logger.info(f"Not removing {path}, possibly in use: {e}")
                continue
            path = renamed
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):
            logger.warning(f"Could not fully remove {path}; trying again at the next start")
        else:
            logger.info(f"Removed old build folder {path}")
            removed.append(path)
    return removed
