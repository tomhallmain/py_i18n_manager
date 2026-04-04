"""Sync base locale YAML from `i18n-tasks missing` output (without `add-missing`).

Runs ``bundle exec i18n-tasks missing``, parses the CLI table, routes keys using
``config/i18n-tasks.yml`` ``data.write`` rules (``pattern_router``), and merges new
keys into existing locale files with ruamel.yaml when available so comments and
formatting are preserved as much as possible.

``RubyI18nManager.generate_pot_file()`` should call :func:`sync_base_from_missing`
for Gemfile projects instead of ``i18n-tasks add-missing``.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Optional

import yaml

from utils.logging_setup import get_logger

logger = get_logger("i18n_tasks_missing_sync")

try:
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString

    RUAMEL_AVAILABLE = True
except ImportError:
    RuamelYAML = None  # type: ignore[misc, assignment]
    DoubleQuotedScalarString = None  # type: ignore[misc, assignment]
    RUAMEL_AVAILABLE = False


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
class I18nTasksConfig:
    """Subset of ``config/i18n-tasks.yml`` needed for routing."""

    base_locale: str
    router: Optional[str]
    data_write: list[Any]


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
            # Separator like |---| — skip
            continue
        parts = [p.strip() for p in line.split("|")]
        # parts[0] and parts[-1] are empty from leading/trailing |
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


# ---------------------------------------------------------------------------
# Load i18n-tasks config & pattern_router
# ---------------------------------------------------------------------------


def find_i18n_tasks_config_path(project_root: str) -> Optional[str]:
    """Return path to ``config/i18n-tasks.yml`` or ``config/i18n-tasks.yaml`` if present."""
    for name in ("i18n-tasks.yml", "i18n-tasks.yaml"):
        p = os.path.join(project_root, "config", name)
        if os.path.isfile(p):
            return p
    return None


def load_i18n_tasks_config(config_path: str) -> I18nTasksConfig:
    """Load routing-related fields from an i18n-tasks config file."""
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid i18n-tasks config (expected mapping): {config_path}")
    base_locale = str(raw.get("base_locale") or "en")
    data_block = raw.get("data") or {}
    if not isinstance(data_block, dict):
        data_block = {}
    write_rules = data_block.get("write")
    if write_rules is None:
        write_rules = []
    if not isinstance(write_rules, list):
        write_rules = []
    router = data_block.get("router")
    if router is None:
        router = raw.get("router")
    return I18nTasksConfig(
        base_locale=base_locale,
        router=str(router) if router is not None else None,
        data_write=write_rules,
    )


def substitute_locale_in_template(template: str, locale: str) -> str:
    """Replace ``%{locale}`` in a path template (i18n-tasks style)."""
    return template.replace("%{locale}", locale)


def path_for_key_pattern_router(dotted_key: str, base_locale: str, write_rules: list[Any]) -> Optional[str]:
    """Resolve relative path for ``dotted_key`` using ``data.write`` (pattern_router semantics).

    First matching ``[glob, path_template]`` wins; if none match, the last bare string
    rule in ``write_rules`` is used as catch-all (same order as i18n-tasks).
    """
    default_template: Optional[str] = None
    for rule in write_rules:
        if isinstance(rule, str):
            default_template = rule
            continue
        if isinstance(rule, (list, tuple)) and len(rule) == 2:
            pattern, tmpl = rule[0], rule[1]
            if isinstance(pattern, str) and isinstance(tmpl, str):
                if fnmatch.fnmatch(dotted_key, pattern):
                    return substitute_locale_in_template(tmpl, base_locale)
    if default_template:
        return substitute_locale_in_template(default_template, base_locale)
    return None


# ---------------------------------------------------------------------------
# Merge keys into YAML (ruamel round-trip)
# ---------------------------------------------------------------------------


def _empty_placeholder_value() -> Any:
    if RUAMEL_AVAILABLE and DoubleQuotedScalarString is not None:
        return DoubleQuotedScalarString("")
    return ""


def _ensure_locale_root(data: Any, base_locale: str) -> Any:
    """Ensure top-level ``base_locale`` key exists on a CommentedMap or dict."""
    if data is None:
        return None
    if hasattr(data, "get") and hasattr(data, "__setitem__"):
        if base_locale not in data:
            if RUAMEL_AVAILABLE:
                try:
                    from ruamel.yaml.comments import CommentedMap

                    data[base_locale] = CommentedMap()
                except Exception:
                    data[base_locale] = {}
            else:
                data[base_locale] = {}
        return data[base_locale]
    return None


def _navigate_or_create(parent: Any, parts: list[str]) -> tuple[Any, bool]:
    """Navigate ``parts`` (excluding leaf); create CommentedMap/dict nodes as needed.

    Returns ``(parent_of_leaf, created_any)``.
    """
    created = False
    current = parent
    for part in parts[:-1]:
        if current is None:
            return None, created
        nxt = current.get(part) if hasattr(current, "get") else None
        if nxt is None:
            try:
                from ruamel.yaml.comments import CommentedMap
            except ImportError:
                CommentedMap = dict  # type: ignore[misc, assignment]
            if RuamelYAML is not None:
                try:
                    nxt = CommentedMap()
                except Exception:
                    nxt = {}
            else:
                nxt = {}
            current[part] = nxt
            created = True
        elif not hasattr(nxt, "get"):
            return None, created
        current = nxt
    return current, created


def _leaf_exists(parent: Any, leaf: str) -> bool:
    if parent is None or not hasattr(parent, "get"):
        return False
    return leaf in parent and parent.get(leaf) is not None


def _set_dotted_key_under_locale(
    locale_root: Any,
    dotted_key: str,
    *,
    skip_if_leaf_exists: bool = True,
) -> bool:
    """Insert ``dotted_key`` with an empty placeholder value under ``locale_root``.

    Returns True if a new leaf was added.
    """
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        return False
    parent, _ = _navigate_or_create(locale_root, parts)
    if parent is None:
        return False
    leaf = parts[-1]
    if skip_if_leaf_exists and _leaf_exists(parent, leaf):
        return False
    parent[leaf] = _empty_placeholder_value()
    return True


def _load_yaml_ruamel(path: str) -> tuple[Any, Any]:
    """Load YAML with round-trip loader. Returns ``(ryaml, data)``."""
    if not RUAMEL_AVAILABLE or RuamelYAML is None:
        raise RuntimeError("ruamel.yaml is required for i18n-tasks missing sync")
    ryaml = RuamelYAML()
    ryaml.preserve_quotes = True
    with open(path, encoding="utf-8") as f:
        data = ryaml.load(f)
    return ryaml, data


def _merge_keys_into_file(
    project_root: str,
    rel_path: str,
    base_locale: str,
    dotted_keys: list[str],
) -> tuple[int, int, int]:
    """Merge keys that map to ``rel_path`` (relative to project root).

    Returns:
        ``(added, skipped_existing, skipped_unrouted)`` — unrouted unused here (always 0).
    """
    abs_path = os.path.normpath(os.path.join(project_root, rel_path.replace("/", os.sep)))
    added = 0
    skipped = 0

    if not os.path.isfile(abs_path):
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not RUAMEL_AVAILABLE or RuamelYAML is None:
            raise RuntimeError("ruamel.yaml is required for i18n-tasks missing sync")
        from ruamel.yaml.comments import CommentedMap

        ryaml = RuamelYAML()
        data: Any = CommentedMap()
        lr = _ensure_locale_root(data, base_locale)
        if lr is None:
            raise RuntimeError(f"Could not create locale root for {base_locale!r} in {abs_path}")
        for dk in dotted_keys:
            if _set_dotted_key_under_locale(lr, dk, skip_if_leaf_exists=True):
                added += 1
            else:
                skipped += 1
        with open(abs_path, "w", encoding="utf-8") as f:
            ryaml.dump(data, f)
        return added, skipped, 0

    ryaml, data = _load_yaml_ruamel(abs_path)
    if data is None:
        from ruamel.yaml.comments import CommentedMap

        data = CommentedMap()
    lr = _ensure_locale_root(data, base_locale)
    if lr is None:
        raise RuntimeError(f"Could not resolve locale root {base_locale!r} in {abs_path}")
    for dk in dotted_keys:
        if _set_dotted_key_under_locale(lr, dk, skip_if_leaf_exists=True):
            added += 1
        else:
            skipped += 1
    with open(abs_path, "w", encoding="utf-8") as f:
        ryaml.dump(data, f)
    return added, skipped, 0


def sync_base_from_missing(project_root: str) -> SyncBaseFromMissingResult:
    """Run ``i18n-tasks missing``, then add **globally missing** keys (Locale ``all``) to base locale files.

    Uses ``pattern_router`` paths from ``config/i18n-tasks.yml``. Requires ``ruamel.yaml``
    for writing. Does not run ``i18n-tasks add-missing``.
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
            a, s, _ = _merge_keys_into_file(project_root, rel, cfg.base_locale, keys)
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
