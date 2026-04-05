"""YAML read/write helpers for Ruby/Rails i18n (PyYAML + ruamel.yaml).

Why both PyYAML and ruamel.yaml
-------------------------------

Ruby/Rails i18n YAML files typically use **quoted** string values (e.g. ``"value"`` instead of
``value``). That convention:

1. Stops YAML from treating special strings as booleans/null (e.g. ``yes``, ``no``, ``true``).
2. Keeps translation files visually consistent.
3. Matches common Rails project style.

**PyYAML** reads quoted strings fine, but **writing** discards formatting (quotes, comments,
spacing) and picks its own output style.

**ruamel.yaml** is built for round-trips: it preserves quotes, comments, and indentation when
loading and dumping, which fits i18n files where formatting matters.

**Strategy in this app**

- Use **PyYAML** for reading where we use a custom loader (e.g. i18n keys without implicit bools).
- Use **ruamel.yaml** for writing when available (quoted values, comment preservation).
- Fall back to **PyYAML** with a value-quoting dumper when ruamel is unavailable (valid YAML,
  keys unquoted where the post-process strips key quotes, except ``yes`` / ``no`` which stay quoted for Ruby).

This module centralizes ruamel round-trip settings, merge/quote helpers, the PyYAML fallback
dumper, and utilities used by :class:`~i18n.ruby.ruby_i18n_manager.RubyI18nManager` and
:mod:`~i18n.ruby.i18n_tasks_sync`.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, Iterable, Optional, TYPE_CHECKING

import yaml

from utils.nested_mapping import remove_from_nested_dict, resolve_nested_dict_key

if TYPE_CHECKING:
    from ruamel.yaml import YAML as RuamelYAMLType

try:
    from ruamel.yaml import YAML as RuamelYAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString

    RUAMEL_AVAILABLE = True
except ImportError:
    RuamelYAML = None  # type: ignore[misc, assignment]
    DoubleQuotedScalarString = None  # type: ignore[misc, assignment]
    RUAMEL_AVAILABLE = False


def ruby_roundtrip_yaml() -> "RuamelYAMLType":
    """Return a :class:`ruamel.yaml.YAML` instance with the app's standard Ruby-locale settings."""
    if not RUAMEL_AVAILABLE or RuamelYAML is None:
        raise RuntimeError("ruamel.yaml is not available")
    ryaml = RuamelYAML()
    ryaml.preserve_quotes = True
    ryaml.width = 1000
    ryaml.indent(mapping=2, sequence=4, offset=2)
    ryaml.allow_duplicate_keys = True
    return ryaml


def empty_quoted_string() -> Any:
    """Placeholder leaf value for new translation keys (double-quoted empty string in YAML)."""
    if RUAMEL_AVAILABLE and DoubleQuotedScalarString is not None:
        return DoubleQuotedScalarString("")
    return ""


def _is_sequence_not_str(obj: Any) -> bool:
    """True for lists/tuples/CommentedSeq; false for str/bytes (str is a Sequence)."""
    return isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray))


def quote_string_values(data: Any) -> Any:
    """Recursively wrap string values in ``DoubleQuotedScalarString``.

    Converts structures to plain dicts/lists where needed, which **loses** ruamel comments;
    use :func:`quote_string_values_in_place` when preserving comments on existing trees.

    Sequences (lists, ``CommentedSeq``, tuples) are preserved as YAML sequences, not
    flattened to strings.
    """
    if not RUAMEL_AVAILABLE or DoubleQuotedScalarString is None:
        return data
    if isinstance(data, dict):
        return {k: quote_string_values(v) for k, v in data.items()}
    if _is_sequence_not_str(data):
        return [quote_string_values(item) for item in data]
    if isinstance(data, str):
        return DoubleQuotedScalarString(data)
    return data


# YAML 1.1 (Ruby Psych): plain ``yes`` / ``no`` map keys are booleans. On write we must emit
# quoted keys so Rails I18n sees string keys.
_RUBY_BOOL_AMBIGUOUS_KEYS = frozenset(("yes", "no"))


def ensure_ruby_yaml_safe_mapping_keys(obj: Any) -> None:
    """Recursively rekey string ``yes`` / ``no`` to double-quoted key nodes for Ruby-safe YAML.

    Call on data trees immediately before ruamel dump. Idempotent for already-quoted keys
    (``DoubleQuotedScalarString`` is not in ``_RUBY_BOOL_AMBIGUOUS_KEYS`` as plain str).
    """
    if not RUAMEL_AVAILABLE or DoubleQuotedScalarString is None:
        return
    try:
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
    except ImportError:
        return

    if isinstance(obj, (dict, CommentedMap)):
        for k in list(obj.keys()):
            ensure_ruby_yaml_safe_mapping_keys(obj[k])
        for k in list(obj.keys()):
            if isinstance(k, str) and k in _RUBY_BOOL_AMBIGUOUS_KEYS:
                v = obj.pop(k)
                obj[DoubleQuotedScalarString(k)] = v
    elif isinstance(obj, (list, CommentedSeq)) or _is_sequence_not_str(obj):
        for item in obj:
            ensure_ruby_yaml_safe_mapping_keys(item)


def quote_string_values_in_place(data: Any) -> Any:
    """Wrap string values in ``DoubleQuotedScalarString`` in-place (preserves CommentedMap/comments)."""
    if not RUAMEL_AVAILABLE or DoubleQuotedScalarString is None:
        return quote_string_values(data)
    try:
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
    except ImportError:
        return quote_string_values(data)

    if isinstance(data, (dict, CommentedMap)):
        for k, v in list(data.items()):
            if isinstance(v, str):
                data[k] = DoubleQuotedScalarString(v)
            elif isinstance(v, (dict, CommentedMap, list, CommentedSeq)):
                quote_string_values_in_place(v)
    elif isinstance(data, (list, CommentedSeq)):
        for i, item in enumerate(data):
            if isinstance(item, str):
                data[i] = DoubleQuotedScalarString(item)
            elif isinstance(item, (dict, CommentedMap, list, CommentedSeq)):
                quote_string_values_in_place(item)
    return data


def merge_ruamel_data(original: Any, new: Any) -> None:
    """Deep-merge ``new`` into ``original`` (both mappings), quoting new string leaves.

    Keys are matched with :func:`~utils.nested_mapping.resolve_nested_dict_key` so
    ruamel/PyYAML trees (e.g. boolean ``true`` keys) merge with dot-path strings
    (``\"true\"``) instead of inserting a parallel branch that leaves old leaves unchanged.

    YAML sequences (lists) are merged/replaced with quoted sequence content; a scalar
    string is never written over an existing sequence (avoids ``str(list)`` one-liners).
    """
    if not isinstance(original, Mapping) or not isinstance(new, Mapping):
        return
    if not RUAMEL_AVAILABLE or DoubleQuotedScalarString is None:
        return

    for key, value in new.items():
        key_str = str(key)
        resolved = resolve_nested_dict_key(original, key_str)

        if resolved is not None:
            existing = original[resolved]
            if (
                isinstance(value, Mapping)
                and isinstance(existing, Mapping)
                and not isinstance(value, str)
            ):
                merge_ruamel_data(existing, value)
            elif _is_sequence_not_str(value) and _is_sequence_not_str(existing):
                original[resolved] = quote_string_values(value)
            elif isinstance(value, str) and _is_sequence_not_str(existing):
                # Do not replace a YAML list with a scalar (e.g. accidental str(list)).
                continue
            else:
                if isinstance(value, str):
                    original[resolved] = DoubleQuotedScalarString(value)
                elif isinstance(value, Mapping):
                    original[resolved] = quote_string_values(value)
                elif _is_sequence_not_str(value):
                    original[resolved] = quote_string_values(value)
                else:
                    original[resolved] = value
        else:
            if isinstance(value, str):
                original[key_str] = DoubleQuotedScalarString(value)
            elif isinstance(value, Mapping):
                original[key_str] = quote_string_values(value)
            elif _is_sequence_not_str(value):
                original[key_str] = quote_string_values(value)
            else:
                original[key_str] = value


def ruamel_yaml_dump_new_file(data: Any, stream, **kwargs: Any) -> None:
    """Dump YAML with ruamel for new files (no original content to preserve)."""
    ryaml = ruby_roundtrip_yaml()
    quoted_data = quote_string_values(data)
    ensure_ruby_yaml_safe_mapping_keys(quoted_data)
    ryaml.dump(quoted_data, stream)


def pyyaml_dump(data: Any, stream, **kwargs: Any) -> None:
    """Dump YAML using PyYAML with a dumper that quotes values; post-process unquotes keys."""

    class QuotedValueDumper(yaml.SafeDumper):
        pass

    def str_representer(dumper: Any, s: str) -> Any:
        return dumper.represent_scalar("tag:yaml.org,2002:str", s, style='"')

    QuotedValueDumper.add_representer(str, str_representer)

    output = io.StringIO()
    yaml.dump(
        data,
        output,
        Dumper=QuotedValueDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
        **kwargs,
    )
    content = output.getvalue()
    lines = content.split("\n")
    processed_lines: list[str] = []
    key_pattern = re.compile(r'^(\s*)"([^"]+)":(\s+.*)?$')
    for line in lines:
        match = key_pattern.match(line)
        if match:
            indent, quoted_key, rest = match.group(1), match.group(2), match.group(3) or ""
            # Keep keys quoted so Ruby Psych does not read them as YAML 1.1 booleans.
            if quoted_key in _RUBY_BOOL_AMBIGUOUS_KEYS:
                processed_lines.append(f'{indent}"{quoted_key}":{rest}')
            else:
                processed_lines.append(f"{indent}{quoted_key}:{rest}")
        else:
            processed_lines.append(line)
    stream.write("\n".join(processed_lines))


# ---------------------------------------------------------------------------
# Locale file helpers (i18n-tasks missing sync)
# ---------------------------------------------------------------------------


def ensure_top_level_locale_key(data: Any, base_locale: str) -> Any:
    """Ensure ``data`` has a top-level key ``base_locale`` with a mapping value; return that subtree."""
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


def _navigate_or_create(parent: Any, parts: list[str]) -> Optional[Any]:
    current = parent
    for part in parts[:-1]:
        if current is None:
            return None
        nxt = current.get(part) if hasattr(current, "get") else None
        if nxt is None:
            try:
                from ruamel.yaml.comments import CommentedMap
            except ImportError:
                CommentedMap = dict  # type: ignore[misc, assignment]
            try:
                nxt = CommentedMap()
            except Exception:
                nxt = {}
            current[part] = nxt
        elif not hasattr(nxt, "get"):
            return None
        current = nxt
    return current


def _leaf_exists(parent: Any, leaf: str) -> bool:
    if parent is None or not hasattr(parent, "get"):
        return False
    return leaf in parent and parent.get(leaf) is not None


def set_dotted_key_under_locale_root(
    locale_root: Any,
    dotted_key: str,
    *,
    leaf_value: Any = None,
    skip_if_leaf_exists: bool = True,
) -> bool:
    """Set ``dotted_key`` under an existing locale subtree (e.g. ``en:`` → ``dashboard.title``).

    If ``leaf_value`` is None, uses :func:`empty_quoted_string`.

    Returns:
        True if a new leaf was written.
    """
    if leaf_value is None:
        leaf_value = empty_quoted_string()
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        return False
    parent = _navigate_or_create(locale_root, parts)
    if parent is None:
        return False
    leaf = parts[-1]
    if skip_if_leaf_exists and _leaf_exists(parent, leaf):
        return False
    parent[leaf] = leaf_value
    return True


def add_dotted_keys_with_empty_values(
    locale_root: Any,
    dotted_keys: Iterable[str],
    *,
    skip_if_leaf_exists: bool = True,
) -> tuple[int, int]:
    """Insert many dotted keys with empty quoted placeholders. Returns ``(added, skipped)``."""
    added = skipped = 0
    for dk in dotted_keys:
        if set_dotted_key_under_locale_root(
            locale_root, dk, skip_if_leaf_exists=skip_if_leaf_exists
        ):
            added += 1
        else:
            skipped += 1
    return added, skipped


def load_roundtrip_yaml_file(path: str) -> tuple[Any, Any]:
    """Load a YAML file with round-trip settings. Returns ``(ryaml, data)``."""
    ryaml = ruby_roundtrip_yaml()
    with open(path, encoding="utf-8") as f:
        data = ryaml.load(f)
    return ryaml, data


def write_roundtrip_yaml_file(ryaml: Any, data: Any, path: str) -> None:
    """Write ``data`` to ``path`` using an existing round-trip loader."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    ensure_ruby_yaml_safe_mapping_keys(data)
    with open(path, "w", encoding="utf-8") as f:
        ryaml.dump(data, f)


def merge_dotted_keys_into_locale_file(
    project_root: str,
    rel_path: str,
    base_locale: str,
    dotted_keys: list[str],
) -> tuple[int, int]:
    """Load ``rel_path`` under ``project_root``, add keys under ``base_locale``, save.

    Creates the file with a minimal ``base_locale`` tree if missing.

    New mapping keys are **appended** (insertion order); there is **no** alphabetical sort.
    See ``tests/test_yaml_parser_utils.py`` (key order assertions).

    Returns:
        ``(added, skipped_existing)``.
    """
    if not RUAMEL_AVAILABLE:
        raise RuntimeError("ruamel.yaml is required for locale YAML merge")

    abs_path = os.path.normpath(os.path.join(project_root, rel_path.replace("/", os.sep)))

    if not os.path.isfile(abs_path):
        from ruamel.yaml.comments import CommentedMap

        ryaml = ruby_roundtrip_yaml()
        data: Any = CommentedMap()
        lr = ensure_top_level_locale_key(data, base_locale)
        if lr is None:
            raise RuntimeError(f"Could not create locale root for {base_locale!r} in {abs_path}")
        added, skipped = add_dotted_keys_with_empty_values(lr, dotted_keys)
        write_roundtrip_yaml_file(ryaml, data, abs_path)
        return added, skipped

    ryaml, data = load_roundtrip_yaml_file(abs_path)
    if data is None:
        from ruamel.yaml.comments import CommentedMap

        data = CommentedMap()
    lr = ensure_top_level_locale_key(data, base_locale)
    if lr is None:
        raise RuntimeError(f"Could not resolve locale root {base_locale!r} in {abs_path}")
    added, skipped = add_dotted_keys_with_empty_values(lr, dotted_keys)
    write_roundtrip_yaml_file(ryaml, data, abs_path)
    return added, skipped


def remove_dotted_keys_from_locale_file(
    project_root: str,
    rel_path: str,
    locale: str,
    dotted_keys: Iterable[str],
) -> tuple[int, int]:
    """Remove dot-notation keys under ``locale`` in ``rel_path`` (relative to project root).

    Uses :func:`~utils.nested_mapping.remove_from_nested_dict` on the locale subtree.
    Skips keys that are not present. Does nothing if the file is missing.

    Returns:
        ``(removed_count, not_found_count)``.
    """
    if not RUAMEL_AVAILABLE:
        raise RuntimeError("ruamel.yaml is required for locale YAML edits")

    keys_list = [k for k in dotted_keys if k and str(k).strip()]
    if not keys_list:
        return 0, 0

    abs_path = os.path.normpath(os.path.join(project_root, rel_path.replace("/", os.sep)))
    if not os.path.isfile(abs_path):
        return 0, len(keys_list)

    ryaml, data = load_roundtrip_yaml_file(abs_path)
    if data is None:
        return 0, len(keys_list)
    lr = ensure_top_level_locale_key(data, locale)
    if lr is None:
        return 0, len(keys_list)

    removed = not_found = 0
    for dk in keys_list:
        if remove_from_nested_dict(lr, dk):
            removed += 1
        else:
            not_found += 1

    if removed:
        write_roundtrip_yaml_file(ryaml, data, abs_path)
    return removed, not_found
