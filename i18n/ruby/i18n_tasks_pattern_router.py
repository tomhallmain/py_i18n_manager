"""Resolve i18n YAML paths from ``config/i18n-tasks.yml`` ``data.write`` (``pattern_router``).

This is the server-side analogue of how the i18n-tasks gem routes keys to files; it does not
use :class:`~i18n.ruby.file_structure_manager.FileStructureManager`, which learns paths from
already-loaded keys. For projects with ``pattern_router``, both should agree when the same
keys exist; for "sync base" we only have ``i18n-tasks missing`` output and must use this config.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Any, Optional

import yaml


def _coerce_locales_list(val: Any) -> list[str]:
    """Normalize ``locales`` from YAML (list, tuple, or comma-separated string)."""
    if val is None:
        return []
    if isinstance(val, str):
        return [x.strip() for x in val.replace(",", " ").split() if x.strip()]
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    return []


@dataclass
class I18nTasksConfig:
    """Subset of ``config/i18n-tasks.yml`` needed for routing."""

    base_locale: str
    router: Optional[str]
    data_write: list[Any]
    locales: list[str]


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
    locales = _coerce_locales_list(raw.get("locales"))
    if not locales:
        locales = _coerce_locales_list(data_block.get("locales"))
    if not locales:
        locales = [base_locale]
    return I18nTasksConfig(
        base_locale=base_locale,
        router=str(router) if router is not None else None,
        data_write=write_rules,
        locales=locales,
    )


def substitute_locale_in_template(template: str, locale: str) -> str:
    """Replace ``%{locale}`` in a path template (i18n-tasks style)."""
    return template.replace("%{locale}", locale)


def path_for_key_pattern_router(
    dotted_key: str, base_locale: str, write_rules: list[Any]
) -> Optional[str]:
    """Resolve project-relative path for ``dotted_key`` using ``data.write`` rules.

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
