"""Sync base locale YAML from `i18n-tasks missing` output (without `add-missing`).

Runs ``bundle exec i18n-tasks missing``, parses the CLI table, routes keys via
``i18n_tasks_pattern_router``, and merges new keys using ``yaml_parser_utils`` so
ruamel settings match :class:`~i18n.ruby.ruby_i18n_manager.RubyI18nManager`.

``RubyI18nManager.generate_pot_file()`` calls :func:`sync_base_from_missing` for Gemfile projects.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from utils.logging_setup import get_logger

from .i18n_tasks_pattern_router import (
    find_i18n_tasks_config_path,
    load_i18n_tasks_config,
    path_for_key_pattern_router,
)
from .yaml_parser_utils import RUAMEL_AVAILABLE, merge_dotted_keys_into_locale_file

logger = get_logger("i18n_tasks_missing_sync")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MissingRow:
    """One row from ``i18n-tasks missing`` tabular output."""

    locale_column: str
    key: str

    def is_missing_in_all_locales(self) -> bool:
        """True when the key is not defined in any locale (Locale column is ``all``)."""
        return self.locale_column.strip() == "all"


@dataclass
class SyncBaseFromMissingResult:
    """Result of :func:`sync_base_from_missing`."""

    success: bool
    message: str = ""
    keys_added: int = 0
    keys_skipped_existing: int = 0
    keys_unrouted: int = 0


# ---------------------------------------------------------------------------
# Bundler / subprocess (mirrors ``RubyI18nManager`` conventions)
# ---------------------------------------------------------------------------


def _bundle_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    extra = os.environ.get("I18N_MANAGER_PATH_EXTRA", "").strip()
    if extra:
        env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    return env


def _resolve_bundle_executable() -> Optional[str]:
    override = os.environ.get("I18N_MANAGER_BUNDLE", "").strip()
    if override:
        return override
    exe = shutil.which("bundle")
    if exe:
        return exe
    if sys.platform == "win32":
        return shutil.which("bundle.cmd")
    return None


def run_i18n_tasks_missing(project_root: str) -> tuple[bool, str]:
    """Run ``bundle exec i18n-tasks missing`` in ``project_root``.

    Returns:
        ``(success, combined_stdout_stderr)`` — on failure, message explains the error.
    """
    bundle_exe = _resolve_bundle_executable()
    if not bundle_exe:
        return (
            False,
            "Could not find 'bundle'. Install Ruby/Bundler, ensure its bin directory is on PATH "
            "for this process, set I18N_MANAGER_PATH_EXTRA to that bin directory (prepended for this command only), "
            "or set I18N_MANAGER_BUNDLE to the bundle executable path.",
        )
    cmd = [bundle_exe, "exec", "i18n-tasks", "missing"]
    env = _bundle_subprocess_env()
    try:
        completed = subprocess.run(
            cmd,
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, "i18n-tasks missing timed out after 10 minutes."
    except FileNotFoundError:
        return (
            False,
            f"Could not execute {bundle_exe!r}. Check I18N_MANAGER_BUNDLE and PATH.",
        )
    except Exception as e:
        return False, str(e)

    out = (completed.stdout or "").strip()
    err = (completed.stderr or "").strip()
    combined = "\n".join(x for x in (out, err) if x)
    if completed.returncode != 0:
        return False, combined or f"Exit code {completed.returncode}"
    return True, combined


# ---------------------------------------------------------------------------
# Parse `missing` table
# ---------------------------------------------------------------------------


def parse_i18n_tasks_missing_table(output: str) -> list[MissingRow]:
    """Parse ASCII table rows from ``i18n-tasks missing`` stdout.

    Expects pipe-separated columns: Locale | Key | (optional third column).
    Skips header and separator lines (``+---+``).
    """
    rows: list[MissingRow] = []
    for line in output.splitlines():
        line = line.rstrip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*[\-+]", line):
            continue
        parts = [p.strip() for p in line.split("|")]
        inner = [p for p in parts if p != ""]
        if len(inner) < 2:
            continue
        locale_col, key_col = inner[0], inner[1]
        if locale_col.lower() == "locale" and key_col.lower() == "key":
            continue
        if not key_col:
            continue
        rows.append(MissingRow(locale_column=locale_col, key=key_col))
    return rows


def sync_base_from_missing(project_root: str) -> SyncBaseFromMissingResult:
    """Run ``i18n-tasks missing``, then add **globally missing** keys (Locale ``all``) to base locale files.

    Uses ``pattern_router`` paths from ``config/i18n-tasks.yml``. Requires ``ruamel.yaml``.
    Does not run ``i18n-tasks add-missing``.
    """
    if not RUAMEL_AVAILABLE:
        return SyncBaseFromMissingResult(
            False,
            "ruamel.yaml is required for preserving YAML formatting when adding keys. "
            "Install ruamel.yaml (see requirements.txt).",
        )

    ok, output = run_i18n_tasks_missing(project_root)
    if not ok:
        return SyncBaseFromMissingResult(False, output)

    rows = parse_i18n_tasks_missing_table(output)
    config_path = find_i18n_tasks_config_path(project_root)
    if not config_path:
        return SyncBaseFromMissingResult(
            False,
            "Could not find config/i18n-tasks.yml or config/i18n-tasks.yaml under the project root.",
        )

    try:
        cfg = load_i18n_tasks_config(config_path)
    except Exception as e:
        return SyncBaseFromMissingResult(False, f"Failed to load i18n-tasks config: {e}")

    if cfg.router and cfg.router != "pattern_router":
        logger.warning(
            "i18n-tasks router is %r (expected 'pattern_router'); routing may not match i18n-tasks.",
            cfg.router,
        )

    keys_all: list[str] = []
    seen: set[str] = set()
    for r in rows:
        if not r.is_missing_in_all_locales():
            continue
        if r.key in seen:
            continue
        seen.add(r.key)
        keys_all.append(r.key)

    if not keys_all:
        return SyncBaseFromMissingResult(True, "", 0, 0, 0)

    by_file: dict[str, list[str]] = {}
    unrouted = 0
    for key in keys_all:
        rel = path_for_key_pattern_router(key, cfg.base_locale, cfg.data_write)
        if not rel:
            unrouted += 1
            logger.warning("No data.write rule matched key %r; skipping.", key)
            continue
        by_file.setdefault(rel, []).append(key)

    total_added = 0
    total_skip = 0
    for rel, keys in sorted(by_file.items()):
        try:
            a, s = merge_dotted_keys_into_locale_file(project_root, rel, cfg.base_locale, keys)
            total_added += a
            total_skip += s
        except Exception as e:
            logger.error("Failed merging keys into %s: %s", rel, e, exc_info=True)
            return SyncBaseFromMissingResult(False, f"{rel}: {e}")

    msg = ""
    if total_added or total_skip or unrouted:
        msg = (
            f"Added {total_added} key(s), skipped {total_skip} already present, "
            f"{unrouted} unrouted."
        )
    return SyncBaseFromMissingResult(
        True,
        msg,
        keys_added=total_added,
        keys_skipped_existing=total_skip,
        keys_unrouted=unrouted,
    )
