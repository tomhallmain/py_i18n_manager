"""Dot-notation helpers for nested ``dict`` trees (e.g. i18n data loaded from YAML).

Supports matching segment keys that may appear as strings or YAML-coerced booleans
(``true`` / ``false`` vs ``True`` / ``False``).
"""

from __future__ import annotations

from typing import Any


def add_to_nested_dict(data: dict, key: str, value: str) -> None:
    """Set ``value`` at dot-notation ``key``, creating intermediate mappings as needed.

    Preserves existing nested structure: only the leaf path is written.
    """
    parts = key.split(".")
    current = data

    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        elif not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]

    current[parts[-1]] = value


def resolve_nested_dict_key(mapping: dict, part: str) -> Any | None:
    """Resolve which key in ``mapping`` corresponds to path segment ``part``.

    Handles ``True``/``False`` strings, ``true``/``false`` strings, and bool keys from YAML.
    Returns the actual key object to use (or ``None`` if not found).
    """
    if part in mapping:
        return part

    wanted = str(part)
    wanted_lower = wanted.lower()
    bool_like = wanted_lower in {"true", "false"}

    for existing_key in mapping.keys():
        if str(existing_key) == wanted:
            return existing_key

    if bool_like:
        for existing_key in mapping.keys():
            if str(existing_key).lower() == wanted_lower:
                return existing_key
            if isinstance(existing_key, bool):
                if existing_key and wanted_lower == "true":
                    return existing_key
                if (not existing_key) and wanted_lower == "false":
                    return existing_key

    return None


def remove_from_nested_dict(data: dict, key: str) -> bool:
    """Remove a dot-notation key from a nested dict in-place.

    Returns:
        True if a value was removed.
    """
    if not isinstance(data, dict):
        return False

    parts = key.split(".")
    current = data
    parents: list[tuple[dict, Any]] = []

    for part in parts[:-1]:
        resolved_part = resolve_nested_dict_key(current, part)
        if resolved_part is None or not isinstance(current[resolved_part], dict):
            return False
        parents.append((current, resolved_part))
        current = current[resolved_part]

    leaf = parts[-1]
    resolved_leaf = resolve_nested_dict_key(current, leaf)
    if resolved_leaf is None:
        return False

    del current[resolved_leaf]

    for parent, parent_key in reversed(parents):
        child = parent.get(parent_key)
        if isinstance(child, dict) and not child:
            del parent[parent_key]
        else:
            break

    return True
