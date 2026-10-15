"""Moves user files that earlier versions wrote into the repo to the app data dir.

Those are ``configs/user_config.json`` (cwd-relative, which is the repo when
started through ``start.bat`` or Explorer), the app info cache and its
backups, and ``llm_review_output/``. The first ``app_paths.user_data_path()``
call in a process moves them to the same relative paths under the data dir:
in a checkout only (a build cannot see the repo), and never while an override
variable is set. An existing target is replaced unless the legacy file is
newer (then both stay, with a warning): a build started first can already
have written a default config and an empty cache there. Folders are merged
file by file.
"""

import glob
import os
import shutil
import threading

from utils import app_paths

#: Repo-relative paths, as glob patterns, of the files and folders moved.
LEGACY_PATTERNS = (
    os.path.join("configs", "user_config.json"),
    "app_info_cache.json",
    "app_info_cache.json.bak*",
    "llm_review_output",
)

_done = False
_lock = threading.Lock()


def _logger():
    # Imported on use: logging_setup imports app_paths, which imports this module lazily.
    from utils.logging_setup import get_logger

    return get_logger("legacy_user_files")


def migrate_once() -> None:
    """Move the legacy files once per process, in a checkout without overrides.
    Logs instead of raising."""
    global _done
    if _done:
        return
    with _lock:
        if _done:
            return
        _done = True
        if app_paths.IS_BUILD or any(app_paths.env_override(name) for name in app_paths.OVERRIDE_ENVS):
            return
        target = app_paths.default_app_data_dir()
        try:
            move_legacy_user_files(app_paths.RESOURCE_ROOT, target)
        except Exception as e:
            _logger().error(f"Moving user files from {app_paths.RESOURCE_ROOT} to {target} failed: {e}")


def move_legacy_user_files(source_root: str, target_root: str) -> None:
    """Move each LEGACY_PATTERNS match under *source_root* to the same
    relative path under *target_root*."""
    for pattern in LEGACY_PATTERNS:
        for source in sorted(glob.glob(os.path.join(glob.escape(source_root), pattern))):
            relative = os.path.relpath(source, source_root)
            try:
                _move_path(source, os.path.join(target_root, relative))
            except OSError as e:
                _logger().error(f"Could not move {source}: {e}")


def _move_path(source: str, target: str) -> None:
    if os.path.isdir(source):
        if os.path.exists(target) and not os.path.isdir(target):
            _logger().warning(f"Not moving folder {source}: {target} is a file")
            return
        for name in sorted(os.listdir(source)):
            _move_path(os.path.join(source, name), os.path.join(target, name))
        try:
            os.rmdir(source)
        except OSError:
            pass  # Something in it was kept.
        return
    if os.path.isdir(target):
        _logger().warning(f"Not moving {source}: {target} is a folder")
        return
    if os.path.exists(target) and os.path.getmtime(source) > os.path.getmtime(target):
        _logger().warning(f"Not moving {source}: it is newer than {target}; both are kept, "
                          f"remove or merge one by hand")
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        os.replace(source, target)
    except OSError:
        # os.replace cannot cross drives (repo on D:, home on C:).
        shutil.copy2(source, target)
        os.remove(source)
    _logger().info(f"Moved {source} to {target}")
