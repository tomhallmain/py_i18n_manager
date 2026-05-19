"""Sync locale YAML with ``i18n-tasks`` (missing + unused).

- **Missing:** ``bundle exec i18n-tasks missing`` → add keys (Locale ``all``) via
  ``merge_dotted_keys_into_locale_file``.
- **Unused:** ``bundle exec i18n-tasks unused -f keys`` (or default table) → remove keys from
  routed locale files. ``-f keys`` lines are often ``<locale>.<dotted.path>``; the locale prefix is
  stripped so paths match YAML under each locale root (see :func:`normalize_and_dedupe_unused_keys`).

``RubyI18nManager.generate_pot_file()`` runs :func:`sync_base_from_missing` then
:func:`sync_base_from_unused` for Gemfile projects.

**Intentional scope limits for sync_base_from_missing**

Only rows whose Locale column is ``all`` are processed (key not present in any locale).
Rows listing specific locales (e.g. ``de es``) mean the key exists in the base locale but
is missing for those non-base locales; those gaps belong to the outstanding-items translation
workflow, not to "sync base."

Pluralization/ICU rows (e.g. a single-locale row whose third column contains ``few, many``)
are also skipped because they require language-specific stub structures rather than a plain
empty string. They will appear as outstanding items once their base key is present.

**Why ``missing`` and not ``add-missing``**

``i18n-tasks add-missing`` rewrites locale files in bulk with its own formatting choices.
``i18n-tasks missing`` is read-only; the Python side handles targeted YAML edits with
comment preservation via ruamel.yaml, giving the application control over file formatting.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from collections import defaultdict
from typing import Optional

from utils.logging_setup import get_logger

from .i18n_tasks_pattern_router import (
    find_i18n_tasks_config_path,
    load_i18n_tasks_config,
    path_for_key_pattern_router,
)
from .yaml_parser_utils import (
    RUAMEL_AVAILABLE,
    merge_dotted_keys_into_locale_file,
    remove_dotted_keys_from_locale_file,
)

logger = get_logger("i18n_tasks_sync")


def is_i18n_tasks_missing_report_output(text: str) -> bool:
    """Return True if ``text`` looks like ``bundle exec i18n-tasks missing`` report output.

    The gem often exits non-zero when any keys are missing (CI-style). It may also print
    unrelated lines to stderr (e.g. maintainer notices); parsing uses stdout when possible.
    """
    if not (text and text.strip()):
        return False
    if "Missing translations" in text:
        return True
    for line in text.splitlines()[:60]:
        s = line.strip()
        if s.startswith("|") and "Locale" in line and "Key" in line:
            return True
    return False


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


@dataclass
class SyncBaseFromUnusedResult:
    """Result of :func:`sync_base_from_unused`."""

    success: bool
    message: str = ""
    keys_removed: int = 0
    keys_not_found_in_tree: int = 0
    keys_skipped_dynamic: int = 0
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
        ``(success, text_to_parse)``. On success, ``text_to_parse`` is usually **stdout**
        so stderr noise (gem banners, etc.) is not mixed into the table parser.

    Note:
        ``i18n-tasks missing`` commonly returns a **non-zero exit code** when there are
        missing keys; that is still a successful run for our purposes if the report table
        is present (see :func:`is_i18n_tasks_missing_report_output`).
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

    if completed.returncode == 0:
        return True, out if out else combined

    # Non-zero: often "missing keys exist" (exit 1). Treat as success if we got a real report.
    if is_i18n_tasks_missing_report_output(out):
        logger.info(
            "i18n-tasks missing exited with code %s but produced a report on stdout "
            "(normal when keys are missing). Ignoring exit code.",
            completed.returncode,
        )
        return True, out
    if is_i18n_tasks_missing_report_output(combined):
        logger.info(
            "i18n-tasks missing exited with code %s but produced a parseable report. Ignoring exit code.",
            completed.returncode,
        )
        return True, combined
    if is_i18n_tasks_missing_report_output(err):
        logger.info(
            "i18n-tasks missing exited with code %s; report found on stderr. Ignoring exit code.",
            completed.returncode,
        )
        return True, err

    tail = combined if combined else err or out
    if tail and len(tail) > 2500:
        tail = tail[:2500] + "\n... (truncated)"
    msg = (
        f"i18n-tasks missing failed (exit {completed.returncode})."
        + (f"\n{tail}" if tail else "")
    )
    return False, msg


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


# ---------------------------------------------------------------------------
# Dynamic key heuristic (prefix + ".{") — exclude from "unused" removal
# ---------------------------------------------------------------------------

_SKIP_SCAN_DIR_NAMES = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "vendor/bundle",
        ".bundle",
        "tmp",
        "log",
        "coverage",
        "storage",
        "vendor",
        "public/packs",
        "public/packs-test",
        "dist",
        "build",
        ".next",
    }
)
_SOURCE_SCAN_SUFFIXES = frozenset(
    {
        ".rb",
        ".rake",
        ".erb",
        ".haml",
        ".slim",
        ".rhtml",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".vue",
        ".coffee",
        ".jbuilder",
    }
)
_MAX_SCAN_FILE_BYTES = 2 * 1024 * 1024

_KEY_LINE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# First path segment looks like an i18n locale code (helps when config ``locales`` is incomplete).
_LOCALE_LIKE_FIRST_SEGMENT = re.compile(r"^[a-z]{2}(-[A-Za-z0-9]+)?$")


def dynamic_prefix_brace_needle(dotted_key: str) -> Optional[str]:
    """Return substring to search for: parent path + ``.{`` (e.g. dynamic segment after a dot).

    Example: ``admin.dashboard.modal.error`` → ``admin.dashboard.modal.{`` .
    """
    parts = [p for p in dotted_key.split(".") if p]
    if len(parts) < 2:
        return None
    return ".".join(parts[:-1]) + ".{"


def partition_keys_by_dynamic_prefix_hint(
    project_root: str, keys: list[str]
) -> tuple[list[str], int]:
    """Split ``keys`` into (remove, skipped) where *skipped* may be used dynamically (``parent.{``).

    One directory walk checks all needles against each scanned file so large projects do not
    re-read the tree once per key.
    """
    if not keys:
        return [], 0

    needle_to_keys: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        n = dynamic_prefix_brace_needle(key)
        if n:
            needle_to_keys[n].append(key)

    if not needle_to_keys:
        return list(keys), 0

    keys_with_needle = {k for ks in needle_to_keys.values() for k in ks}
    matched: set[str] = set()
    root = os.path.normpath(project_root)
    needles = list(needle_to_keys.keys())
    scan_done = False

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _SKIP_SCAN_DIR_NAMES and not d.startswith(".")
        ]
        for name in filenames:
            lower = name.lower()
            if not any(lower.endswith(suf) for suf in _SOURCE_SCAN_SUFFIXES):
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_size > _MAX_SCAN_FILE_BYTES:
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            for needle in needles:
                if needle in content:
                    matched.update(needle_to_keys[needle])
            if keys_with_needle <= matched:
                scan_done = True
                break
        if scan_done:
            break

    if matched:
        logger.debug(
            "Skipping unused removal for %d key(s) (dynamic prefix `parent.{` found in sources): %s",
            len(matched),
            sorted(matched)[:20],
        )

    to_remove = [k for k in keys if k not in matched]
    return to_remove, len(matched)


# ---------------------------------------------------------------------------
# `i18n-tasks unused` (``-f keys`` and/or default table)
# ---------------------------------------------------------------------------


def is_i18n_tasks_unused_report_output(text: str) -> bool:
    """True if ``text`` looks like default ``unused`` ASCII table (Locale | Key | …)."""
    if not (text and text.strip()):
        return False
    if "Unused" in text and ("|" in text or "Locale" in text):
        return True
    for line in text.splitlines()[:60]:
        s = line.strip()
        if s.startswith("|") and "Locale" in line and "Key" in line:
            return True
    return False


def is_i18n_tasks_unused_flat_keys_output(text: str) -> bool:
    """True if ``text`` looks like ``-f keys`` output (one dotted key per line)."""
    if not text or not text.strip():
        return True
    for line in text.splitlines()[:500]:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if _KEY_LINE_RE.match(s):
            return True
    return False


def is_i18n_tasks_unused_output_parseable(text: str) -> bool:
    """True if we can parse keys from ``unused`` stdout (table or ``-f keys`` lines)."""
    if not text or not text.strip():
        return True
    if is_i18n_tasks_unused_report_output(text):
        return True
    return is_i18n_tasks_unused_flat_keys_output(text)


def parse_i18n_tasks_unused_table(output: str) -> list[str]:
    """Parse default ``unused`` table: **Key** column only; order-preserving unique keys."""
    seen: set[str] = set()
    keys: list[str] = []
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
        if key_col not in seen:
            seen.add(key_col)
            keys.append(key_col)
    return keys


def collect_locale_like_prefixes_from_unused_keys(keys: list[str]) -> set[str]:
    """First segments of ``a.b.c`` keys that look like locale codes (``en``, ``zh-CN``, …)."""
    out: set[str] = set()
    for k in keys:
        if "." not in k:
            continue
        first, _rest = k.split(".", 1)
        if _LOCALE_LIKE_FIRST_SEGMENT.match(first):
            out.add(first)
    return out


def merge_locale_prefixes_for_unused_strip(cfg_locales: list[str], raw_keys: list[str]) -> list[str]:
    """Config locales plus locale-like first segments from raw ``unused`` lines (longest first)."""
    merged = frozenset(cfg_locales) | collect_locale_like_prefixes_from_unused_keys(raw_keys)
    return sorted(merged, key=len, reverse=True)


def strip_leading_locale_from_i18n_tasks_key(key: str, locales: list[str]) -> str:
    """Strip ``<locale>.`` when ``locale`` is in ``locales`` (``-f keys`` / internal form).

    YAML files nest translations under ``en:`` → ``admin:`` → …, so dotted paths passed to
    :func:`~utils.nested_mapping.remove_from_nested_dict` must be ``admin....``, not
    ``en.admin....``. i18n-tasks often prints one line per locale with the locale as the first
    segment; longer locale codes are matched first (e.g. ``pt-BR`` before ``pt``).
    """
    if not key or not locales:
        return key
    for loc in sorted(frozenset(locales), key=len, reverse=True):
        if not loc:
            continue
        if key == loc:
            return ""
        prefix = loc + "."
        if key.startswith(prefix):
            return key[len(prefix) :]
    return key


def normalize_and_dedupe_unused_keys(keys: list[str], locales: list[str]) -> list[str]:
    """Strip locale prefixes and dedupe (same logical key may appear once per locale in output)."""
    out: list[str] = []
    seen: set[str] = set()
    for k in keys:
        nk = strip_leading_locale_from_i18n_tasks_key(k.strip(), locales)
        if not nk:
            continue
        if nk not in seen:
            seen.add(nk)
            out.append(nk)
    return out


def parse_i18n_tasks_unused_keys(output: str) -> list[str]:
    """Raw keys from ``unused`` output: table (if present) else ``-f keys`` lines.

    Rows are deduped only as emitted; call :func:`normalize_and_dedupe_unused_keys` with
    ``config/i18n-tasks.yml`` locales before routing/removal.
    """
    table_keys = parse_i18n_tasks_unused_table(output)
    if table_keys:
        return table_keys

    seen: set[str] = set()
    keys: list[str] = []
    for line in output.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not _KEY_LINE_RE.match(s):
            continue
        if s not in seen:
            seen.add(s)
            keys.append(s)
    return keys


def run_i18n_tasks_unused(project_root: str) -> tuple[bool, str]:
    """Run ``bundle exec i18n-tasks unused -f keys`` in ``project_root``.

    ``-f keys`` is stable to parse; lines are normalized with
    :func:`normalize_and_dedupe_unused_keys` before YAML edits.

    Returns:
        ``(success, text_to_parse)``. Non-zero exit is common when unused keys exist; we still
        treat it as success if the output is parseable (table or key lines).
    """
    bundle_exe = _resolve_bundle_executable()
    if not bundle_exe:
        return (
            False,
            "Could not find 'bundle'. Install Ruby/Bundler, ensure its bin directory is on PATH "
            "for this process, set I18N_MANAGER_PATH_EXTRA to that bin directory (prepended for this command only), "
            "or set I18N_MANAGER_BUNDLE to the bundle executable path.",
        )
    cmd = [bundle_exe, "exec", "i18n-tasks", "unused", "-f", "keys"]
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
        return False, "i18n-tasks unused timed out after 10 minutes."
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

    if completed.returncode == 0:
        return True, out if out else combined

    if is_i18n_tasks_unused_output_parseable(out):
        logger.info(
            "i18n-tasks unused exited with code %s but parseable output on stdout; ignoring exit code.",
            completed.returncode,
        )
        return True, out
    if is_i18n_tasks_unused_output_parseable(combined):
        logger.info(
            "i18n-tasks unused exited with code %s; parseable output in combined stdout/stderr.",
            completed.returncode,
        )
        return True, combined
    if is_i18n_tasks_unused_output_parseable(err):
        logger.info(
            "i18n-tasks unused exited with code %s; parseable output on stderr.",
            completed.returncode,
        )
        return True, err

    tail = combined if combined else err or out
    if tail and len(tail) > 2500:
        tail = tail[:2500] + "\n... (truncated)"
    msg = f"i18n-tasks unused failed (exit {completed.returncode})." + (f"\n{tail}" if tail else "")
    return False, msg


def sync_base_from_unused(project_root: str) -> SyncBaseFromUnusedResult:
    """Run ``i18n-tasks unused``, normalize keys (strip ``locale.`` prefix, dedupe), then remove.

    Keys that match :func:`partition_keys_by_dynamic_prefix_hint` are kept (not removed).
    """
    if not RUAMEL_AVAILABLE:
        return SyncBaseFromUnusedResult(
            False,
            "ruamel.yaml is required for preserving YAML formatting when removing keys. "
            "Install ruamel.yaml (see requirements.txt).",
        )

    ok, output = run_i18n_tasks_unused(project_root)
    if not ok:
        return SyncBaseFromUnusedResult(False, output)

    raw_keys = parse_i18n_tasks_unused_keys(output)
    config_path = find_i18n_tasks_config_path(project_root)
    if not config_path:
        return SyncBaseFromUnusedResult(
            False,
            "Could not find config/i18n-tasks.yml or config/i18n-tasks.yaml under the project root.",
        )

    try:
        cfg = load_i18n_tasks_config(config_path)
    except Exception as e:
        return SyncBaseFromUnusedResult(False, f"Failed to load i18n-tasks config: {e}")

    strip_locales = merge_locale_prefixes_for_unused_strip(cfg.locales, raw_keys)
    keys = normalize_and_dedupe_unused_keys(raw_keys, strip_locales)

    if not keys:
        return SyncBaseFromUnusedResult(True, "", 0, 0, 0, 0)

    to_remove, skipped_dynamic = partition_keys_by_dynamic_prefix_hint(project_root, keys)

    if not to_remove:
        msg = ""
        if skipped_dynamic:
            msg = f"Skipped removing {skipped_dynamic} key(s) (dynamic prefix heuristic)."
        return SyncBaseFromUnusedResult(True, msg, 0, 0, skipped_dynamic, 0)

    by_file_locale: dict[tuple[str, str], list[str]] = defaultdict(list)
    unrouted = 0
    for key in to_remove:
        rel0 = path_for_key_pattern_router(key, cfg.base_locale, cfg.data_write)
        if not rel0:
            unrouted += 1
            logger.warning("No data.write rule matched key %r; skipping.", key)
            continue
        for locale in cfg.locales:
            rel = path_for_key_pattern_router(key, locale, cfg.data_write)
            if not rel:
                continue
            by_file_locale[(rel, locale)].append(key)

    total_removed = 0
    total_not_found = 0
    for (rel, loc), key_list in sorted(by_file_locale.items()):
        unique = list(dict.fromkeys(key_list))
        try:
            removed, not_found = remove_dotted_keys_from_locale_file(
                project_root, rel, loc, unique
            )
            total_removed += removed
            total_not_found += not_found
        except Exception as e:
            logger.error("Failed removing keys from %s (%s): %s", rel, loc, e, exc_info=True)
            return SyncBaseFromUnusedResult(False, f"{rel} ({loc}): {e}")

    msg_parts: list[str] = []
    if total_removed or total_not_found or skipped_dynamic or unrouted:
        msg_parts.append(
            f"Removed {total_removed} key occurrence(s), {total_not_found} not found in file, "
            f"{skipped_dynamic} skipped (dynamic), {unrouted} unrouted."
        )
    return SyncBaseFromUnusedResult(
        True,
        " ".join(msg_parts).strip(),
        keys_removed=total_removed,
        keys_not_found_in_tree=total_not_found,
        keys_skipped_dynamic=skipped_dynamic,
        keys_unrouted=unrouted,
    )


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
