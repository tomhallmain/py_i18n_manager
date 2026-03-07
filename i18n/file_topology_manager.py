"""Generic locale-file topology helper for i18n managers.

Tracks per-key source files and default-locale file templates, and provides
locale-aware path normalization/translation to keep locale file topology
consistent across non-default locales.
"""

import os
from typing import Optional

from utils.logging_setup import get_logger

logger = get_logger("file_topology_manager_generic")


class FileTopologyManager:
    """Manage locale-aware file path normalization and translation."""

    def __init__(self, base_locale_dir: str, default_locale: str):
        self._base_locale_dir = base_locale_dir
        self._default_locale = default_locale
        self._source_files: dict[str, dict[str, str]] = {}
        self._default_locale_files: set[str] = set()

    @staticmethod
    def _is_locale_like(token: str) -> bool:
        if not token:
            return False
        if len(token) == 2 and token.isalpha():
            return True
        if len(token) == 5 and token[2] in {"-", "_"} and token[:2].isalpha() and token[3:].isalpha():
            return True
        return False

    def _locale_variants(self, locale: str) -> set[str]:
        base = locale or ""
        variants = {
            base,
            base.replace("-", "_"),
            base.replace("_", "-"),
        }
        variants |= {v.lower() for v in variants}
        return {v for v in variants if v}

    def _replace_locale_token(self, text: str, locale: str, replacement: str) -> tuple[str, bool]:
        variants = sorted(self._locale_variants(locale), key=len, reverse=True)
        updated = text
        changed = False

        for variant in variants:
            if updated == variant:
                updated = replacement
                changed = True
                continue
            for sep in (".", "_", "-"):
                token = f"{sep}{variant}{sep}"
                if token in updated:
                    updated = updated.replace(token, f"{sep}{replacement}{sep}")
                    changed = True
                suffix = f"{sep}{variant}"
                if updated.endswith(suffix):
                    updated = updated[: -len(suffix)] + f"{sep}{replacement}"
                    changed = True
                prefix = f"{variant}{sep}"
                if updated.startswith(prefix):
                    updated = f"{replacement}{sep}" + updated[len(prefix):]
                    changed = True
        return updated, changed

    def normalize_path_for_comparison(self, file_path: str, locale: str) -> str:
        """Return a locale-agnostic relative path representation."""
        rel_path = os.path.relpath(file_path, self._base_locale_dir)
        parts = rel_path.replace("\\", "/").split("/")
        if not parts:
            return rel_path.replace("\\", "/")

        changed = False
        normalized_parts: list[str] = []
        for part in parts[:-1]:
            replaced, did_change = self._replace_locale_token(part, locale, "{locale}")
            normalized_parts.append(replaced)
            changed = changed or did_change

        filename = parts[-1]
        stem, ext = os.path.splitext(filename)
        replaced_stem, did_change = self._replace_locale_token(stem, locale, "{locale}")
        changed = changed or did_change
        normalized_parts.append(replaced_stem + ext)

        normalized = "/".join(normalized_parts)
        if changed:
            return normalized
        return rel_path.replace("\\", "/")

    def translate_file_path(self, default_file_path: str, target_locale: str) -> Optional[str]:
        """Translate a default-locale file path to its target-locale counterpart."""
        try:
            rel_path = os.path.relpath(default_file_path, self._base_locale_dir)
        except ValueError:
            return None

        parts = rel_path.replace("\\", "/").split("/")
        if not parts:
            return None

        changed = False
        translated_parts: list[str] = []
        for part in parts[:-1]:
            replaced, did_change = self._replace_locale_token(part, self._default_locale, target_locale)
            translated_parts.append(replaced)
            changed = changed or did_change

        filename = parts[-1]
        stem, ext = os.path.splitext(filename)
        replaced_stem, did_change = self._replace_locale_token(stem, self._default_locale, target_locale)
        translated_parts.append(replaced_stem + ext)
        changed = changed or did_change

        if not changed and parts and parts[0] in self._locale_variants(self._default_locale):
            translated_parts[0] = target_locale
            changed = True

        if not changed:
            return None
        return os.path.join(self._base_locale_dir, *translated_parts)

    def get_source_file(self, key: str, locale: str) -> Optional[str]:
        return self._source_files.get(key, {}).get(locale)

    def set_source_file(self, key: str, locale: str, file_path: str) -> None:
        if key not in self._source_files:
            self._source_files[key] = {}
        self._source_files[key][locale] = file_path

    def add_default_locale_file(self, file_path: str) -> None:
        self._default_locale_files.add(file_path)

    def get_default_locale_files(self) -> set[str]:
        return self._default_locale_files.copy()

    def reset(self) -> None:
        self._source_files = {}
        self._default_locale_files = set()

