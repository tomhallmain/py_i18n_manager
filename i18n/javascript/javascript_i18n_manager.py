import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from i18n.translation_group import TranslationGroup, TranslationKey
from ..file_topology_manager import FileTopologyManager
from ..i18n_manager_base import I18NManagerBase
from ..translation_manager_results import LocaleStatus, TranslationAction, TranslationManagerResults
from utils.logging_setup import get_logger
from utils.utils import Utils

logger = get_logger("javascript_i18n_manager")


class JavaScriptI18NManager(I18NManagerBase):
    """Manage JavaScript translation files (JSON or JS module object export).

    Implemented:
    - Multi-file bundle support with per-bundle translation contexts
    - Topology parity derived from default locale files
    """

    def __init__(self, directory, locales=None, intro_details=None, settings_manager=None):
        logger.info(f"Initializing JavaScriptI18NManager with directory: {directory}, locales: {locales}")
        super().__init__(directory, locales or [], intro_details, settings_manager)
        self._bundle_files_by_locale: Dict[str, Dict[str, dict]] = {}
        self._default_bundle_templates: Dict[str, dict] = {}
        self._topology_manager = FileTopologyManager(
            os.path.join(self._directory, self._locale_dir),
            self.default_locale,
        )

    @property
    def default_locale(self) -> str:
        if self.settings_manager:
            return self.settings_manager.get_project_default_locale(self._directory)
        return self.intro_details.get("translation.default_locale", "en")

    def _detect_locale_directory(self) -> str:
        candidates = [
            os.path.join(self._directory, "src", "locales"),
            os.path.join(self._directory, "locales"),
            os.path.join(self._directory, "locale"),
            os.path.join(self._directory, "i18n"),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                rel = os.path.relpath(candidate, self._directory)
                logger.info(f"Using JavaScript locale directory: {rel}")
                return rel
        logger.info("No JS locale directory found. Defaulting to src/locales")
        return os.path.join("src", "locales")

    def set_directory(self, directory: str):
        self._directory = directory
        self.translations = {}
        self.written_locales = set()
        self.locales = []
        self._bundle_files_by_locale = {}
        self._default_bundle_templates = {}
        self._locale_dir = self._detect_locale_directory()
        self._topology_manager = FileTopologyManager(
            os.path.join(self._directory, self._locale_dir),
            self.default_locale,
        )

    def _create_results(self, action: TranslationAction) -> TranslationManagerResults:
        locale_dir = os.path.join(self._directory, self._locale_dir)
        has_locale_dir = os.path.isdir(locale_dir)
        statuses: Dict[str, LocaleStatus] = {}
        bundle_files_by_locale, _ = self._scan_locale_files()

        for locale, bundles in bundle_files_by_locale.items():
            files = [bundle["path"] for bundle in bundles.values() if os.path.exists(bundle["path"])]
            last_modified = (
                datetime.fromtimestamp(max(os.path.getmtime(path) for path in files))
                if files else None
            )
            statuses[locale] = LocaleStatus(
                locale_code=locale,
                has_directory=has_locale_dir,
                has_po_file=bool(files),
                has_mo_file=False,
                po_file_path=files[0] if files else None,
                mo_file_path=None,
                last_modified=last_modified,
            )

        base_path = self.get_pot_file_path()
        has_base = bool(base_path and os.path.exists(base_path))
        return TranslationManagerResults(
            project_dir=self._directory,
            action=action,
            action_timestamp=datetime.now(),
            action_successful=True,
            locale_statuses=statuses,
            failed_locales=[],
            default_locale=self.default_locale,
            has_locale_dir=has_locale_dir,
            has_pot_file=has_base,
            pot_file_path=base_path if has_base else None,
            pot_last_modified=datetime.fromtimestamp(os.path.getmtime(base_path)) if has_base else None,
        )

    def _is_locale_code(self, name: str) -> bool:
        return bool(re.match(r"^[a-z]{2}(?:[-_][A-Za-z]{2})?$", name))

    def _extract_locale_from_stem(self, stem: str) -> Optional[str]:
        tokens = [token for token in re.split(r"[._-]", stem) if token]
        for token in tokens:
            if self._is_locale_code(token):
                return token
        return None

    def _extract_locale_from_relative_path(self, rel_path: str) -> Optional[str]:
        segments = rel_path.replace("\\", "/").split("/")
        for segment in segments:
            if self._is_locale_code(segment):
                return segment
        stem = os.path.splitext(os.path.basename(rel_path))[0]
        return self._extract_locale_from_stem(stem)

    def _bundle_id_from_path(self, file_path: str, locale: str) -> str:
        normalized = self._topology_manager.normalize_path_for_comparison(file_path, locale)
        if normalized.endswith(".json"):
            normalized = normalized[:-5]
        elif normalized.endswith(".js"):
            normalized = normalized[:-3]
        elif normalized.endswith(".ts"):
            normalized = normalized[:-3]
        return normalized

    def list_translation_file_paths(self) -> List[str]:
        """JSON/JS/TS translation files under the project locale directory (same scan as load)."""
        locale_dir = os.path.join(self._directory, self._locale_dir)
        if not Utils.isdir_with_retry(locale_dir):
            return []
        exts = {".json", ".js", ".ts"}
        return [
            str(p)
            for p in Path(locale_dir).rglob("*")
            if p.is_file() and p.suffix.lower() in exts
        ]

    def _scan_locale_files(self) -> Tuple[Dict[str, Dict[str, dict]], Dict[str, dict]]:
        locale_dir = os.path.join(self._directory, self._locale_dir)
        if not Utils.isdir_with_retry(locale_dir):
            return {}, {}

        locale_files: Dict[str, Dict[str, dict]] = {}
        default_templates: Dict[str, dict] = {}
        extensions = [".json", ".js", ".ts"]
        for file_path in Path(locale_dir).rglob("*"):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in extensions:
                continue

            rel_path = os.path.relpath(str(file_path), locale_dir)
            locale = self._extract_locale_from_relative_path(rel_path) or self.default_locale
            bundle_id = self._bundle_id_from_path(str(file_path), locale)

            if locale not in locale_files:
                locale_files[locale] = {}
            locale_files[locale][bundle_id] = {
                "path": str(file_path),
                "format": ext,
            }

            if locale == self.default_locale and bundle_id not in default_templates:
                default_templates[bundle_id] = {
                    "path": str(file_path),
                    "format": ext,
                }

        return locale_files, default_templates

    def _flatten_dict(self, data: dict, prefix: str = "") -> Dict[str, str]:
        flattened: Dict[str, str] = {}
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flattened.update(self._flatten_dict(value, full_key))
            else:
                flattened[full_key] = "" if value is None else str(value)
        return flattened

    def _expand_dict(self, flat_values: Dict[str, str]) -> Dict[str, object]:
        expanded: Dict[str, object] = {}
        for key, value in flat_values.items():
            parts = key.split(".")
            current = expanded
            for part in parts[:-1]:
                if part not in current or not isinstance(current[part], dict):
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        return expanded

    def _parse_js_object_literal(self, content: str) -> Optional[dict]:
        # Remove comments first.
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        # Keep this conservative to avoid corrupting URLs like "https://...".
        content = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)

        match = re.search(r"(?:export\s+default|module\.exports\s*=|export\s+const\s+\w+\s*=)\s*(\{.*\})\s*;?\s*$", content, re.DOTALL)
        if not match:
            return None
        object_literal = match.group(1)

        # Convert common JS object-literal forms to JSON.
        json_like = object_literal
        json_like = re.sub(r",(\s*[}\]])", r"\1", json_like)  # remove trailing commas
        json_like = re.sub(r'([{\s,])([A-Za-z_$][A-Za-z0-9_$-]*)\s*:', r'\1"\2":', json_like)  # quote keys
        json_like = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', json_like)  # single -> double quotes

        try:
            return json.loads(json_like)
        except json.JSONDecodeError:
            logger.warning("Could not parse JS translation object literal as JSON-compatible object")
            return None

    def _read_locale_data(self, file_path: str, format_hint: str) -> dict:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if format_hint == ".json":
            return json.loads(content) if content.strip() else {}

        # TODO(js-i18n): Add AST-based parsing for JS/TS modules to support
        # richer syntax (imports, `as const`, spread, computed keys).
        parsed = self._parse_js_object_literal(content)
        return parsed or {}

    def _unwrap_locale_wrapper(self, data: dict, locale: str) -> dict:
        if not isinstance(data, dict):
            return {}
        if locale in data and isinstance(data[locale], dict) and len(data) == 1:
            return data[locale]
        return data

    def _write_locale_data(self, file_path: str, format_hint: str, data: dict):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if format_hint == ".json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            return

        content = "export default " + json.dumps(data, indent=2, ensure_ascii=False) + ";\n"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _discover_locales(self, files_by_locale: Dict[str, Dict[str, dict]]) -> list[str]:
        locales = sorted(files_by_locale.keys())
        if self.default_locale not in locales and files_by_locale:
            locales.insert(0, self.default_locale)
        return locales

    def _load_locale_state(self):
        self._bundle_files_by_locale, self._default_bundle_templates = self._scan_locale_files()
        self.locales = self._discover_locales(self._bundle_files_by_locale)
        self._topology_manager.reset()
        for info in self._default_bundle_templates.values():
            self._topology_manager.add_default_locale_file(info["path"])

    def _ensure_default_template(self):
        if self._default_bundle_templates:
            return
        locale_dir = os.path.join(self._directory, self._locale_dir)
        default_file = os.path.join(locale_dir, f"{self.default_locale}.json")
        self._default_bundle_templates["{locale}"] = {"path": default_file, "format": ".json"}
        self._topology_manager.add_default_locale_file(default_file)

    def _bundle_templates_for_writing(self) -> Dict[str, dict]:
        templates = dict(self._default_bundle_templates)
        if not templates:
            self._ensure_default_template()
            templates = dict(self._default_bundle_templates)

        locale_dir = os.path.join(self._directory, self._locale_dir)
        for key, group in self.translations.items():
            if not group.is_in_base:
                continue
            bundle_id = key.context or "{locale}"
            if bundle_id in templates:
                continue
            templates[bundle_id] = {
                "path": os.path.join(locale_dir, f"{bundle_id}.json"),
                "format": ".json",
            }
        return templates

    def _bundle_file_for_locale(self, bundle_id: str, locale: str) -> dict:
        templates = self._bundle_templates_for_writing()
        template = templates.get(bundle_id)
        if not template:
            template = next(iter(templates.values()))
        default_path = template["path"]
        if locale == self.default_locale:
            return {"path": default_path, "format": template["format"]}
        translated = self._topology_manager.translate_file_path(default_path, locale)
        if translated:
            return {"path": translated, "format": template["format"]}
        stem, ext = os.path.splitext(default_path)
        return {"path": f"{stem}.{locale}{ext}", "format": template["format"]}

    def _parse_loaded_files(self):
        default_bundles = self._bundle_files_by_locale.get(self.default_locale, {})
        for bundle_id, info in default_bundles.items():
            data = self._read_locale_data(info["path"], info["format"])
            values = self._flatten_dict(self._unwrap_locale_wrapper(data, self.default_locale))
            for key, value in values.items():
                tkey = TranslationKey(key, context=bundle_id)
                group = TranslationGroup(key, is_in_base=True, context=bundle_id)
                group.add_translation(self.default_locale, value)
                self.translations[tkey] = group
                self._topology_manager.set_source_file(str(tkey), self.default_locale, info["path"])

        for locale, bundles in self._bundle_files_by_locale.items():
            if locale == self.default_locale:
                continue
            for bundle_id, info in bundles.items():
                data = self._read_locale_data(info["path"], info["format"])
                values = self._flatten_dict(self._unwrap_locale_wrapper(data, locale))
                for key, value in values.items():
                    tkey = TranslationKey(key, context=bundle_id)
                    if tkey not in self.translations:
                        self.translations[tkey] = TranslationGroup(key, is_in_base=False, context=bundle_id)
                    self.translations[tkey].add_translation(locale, value)
                    if self._topology_manager.get_source_file(str(tkey), locale) is None:
                        self._topology_manager.set_source_file(str(tkey), locale, info["path"])

    def _collect_entries_for_locale(self, locale: str) -> Dict[str, Dict[str, str]]:
        entries: Dict[str, Dict[str, str]] = {}
        for key, group in self.translations.items():
            if not group.is_in_base:
                continue
            bundle_id = key.context or "{locale}"
            if bundle_id not in entries:
                entries[bundle_id] = {}
            entries[bundle_id][key.msgid] = group.get_translation_unescaped(locale) or ""
        return entries

    def manage_translations(
        self,
        action: TranslationAction = TranslationAction.CHECK_STATUS,
        modified_locales=None,
    ):
        results = self._create_results(action)
        results.failed_locales = []
        results.action_successful = True

        try:
            if action in (TranslationAction.CHECK_STATUS, TranslationAction.QUALITY_REVIEW):
                self.translations = {}
                self._load_locale_state()
                self._parse_loaded_files()

            self._populate_translation_statistics(results, action)

            if action == TranslationAction.WRITE_PO_FILES:
                if self.fix_invalid_translations():
                    logger.debug("Applied automatic translation fixes before JS write")
                self.write_po_files(modified_locales, results)
            elif action == TranslationAction.WRITE_MO_FILES:
                self.create_mo_files(results)
            elif action == TranslationAction.GENERATE_POT:
                if not self.generate_pot_file():
                    results.action_successful = False
                    results.extend_error_message("Failed to generate JavaScript base locale file")

            if action == TranslationAction.CHECK_STATUS:
                self.apply_latest_translation_file_mtime(results)

            results.determine_action_successful()
            return results
        except Exception as exc:
            logger.error(f"Error in JavaScript manager: {exc}", exc_info=True)
            results.action_successful = False
            results.error_message = str(exc)
            return results

    def get_po_file_path(self, locale: str) -> str:
        if not self._default_bundle_templates:
            self._load_locale_state()
            self._ensure_default_template()
        primary_bundle = sorted(self._default_bundle_templates.keys())[0]
        return self._bundle_file_for_locale(primary_bundle, locale)["path"]

    def get_pot_file_path(self) -> str:
        return self.get_po_file_path(self.default_locale)

    def generate_pot_file(self) -> bool:
        try:
            self._load_locale_state()
            self._ensure_default_template()
            base_info = self._bundle_file_for_locale(sorted(self._default_bundle_templates.keys())[0], self.default_locale)
            if Utils.exists_with_retry(base_info["path"]):
                return True
            self._write_locale_data(
                base_info["path"],
                base_info["format"],
                {"application": {"name": self.intro_details.get("application_name", "Application Name")}},
            )
            return True
        except Exception as exc:
            logger.error(f"Failed generating JS base file: {exc}", exc_info=True)
            return False

    def create_mo_files(self, results: TranslationManagerResults):
        logger.info("JavaScript translations do not require compilation. Skipping.")

    def write_po_files(self, modified_locales, results: TranslationManagerResults):
        self._load_locale_state()
        self._ensure_default_template()
        # TODO(js-i18n-parity-policy): We currently project default-locale
        # bundle topology onto non-default locales. If a non-default locale
        # intentionally uses a different structure, add a locale-level policy
        # to skip parity enforcement instead of reshaping files.
        locales_to_write = set(modified_locales or self.locales or [self.default_locale])
        locales_to_write.add(self.default_locale)
        templates = self._bundle_templates_for_writing()

        for locale in sorted(locales_to_write):
            try:
                entries_by_bundle = self._collect_entries_for_locale(locale)
                for bundle_id in sorted(templates.keys()):
                    info = self._bundle_file_for_locale(bundle_id, locale)
                    locale_values = entries_by_bundle.get(bundle_id, {})
                    self._write_locale_data(
                        info["path"],
                        info["format"],
                        self._expand_dict(locale_values),
                    )
                self.written_locales.add(locale)
            except Exception as exc:
                logger.error(f"Failed writing JS translations for {locale}: {exc}", exc_info=True)
                results.failed_locales.append(locale)

        if results.failed_locales:
            results.extend_error_message(f"Failed to write JS locale files for locales: {results.failed_locales}")
        else:
            results.po_files_updated = True
            results.updated_locales = sorted(locales_to_write)
            if self.pending_deleted_keys:
                self.clear_queued_deleted_keys()

    def write_locale_po_file(self, locale: str) -> bool:
        temp_results = self._create_results(TranslationAction.WRITE_PO_FILES)
        self.write_po_files({locale}, temp_results)
        return not temp_results.failed_locales

    def find_translatable_strings(self):
        project_dir = self._directory
        results = {}
        literal_pattern = re.compile(r'["\']([^"\']{3,})["\']')

        for root, _, files in os.walk(project_dir):
            for file_name in files:
                if not file_name.endswith((".js", ".jsx", ".ts", ".tsx")):
                    continue
                if "locales" in root.replace("\\", "/"):
                    continue

                file_path = os.path.join(root, file_name)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    strings = []
                    for match in literal_pattern.finditer(content):
                        text = match.group(1).strip()
                        if not text:
                            continue
                        prefix = content[max(0, match.start() - 60):match.start()]
                        if any(token in prefix for token in ("t(", "i18n.t(", "translate(")):
                            continue
                        strings.append(text)

                    if strings:
                        results[os.path.relpath(file_path, project_dir)] = strings
                except Exception as exc:
                    logger.warning(f"Error scanning file {file_path}: {exc}")

        return results

    def check_translations_changed(self, include_stale_translations: bool = False) -> bool:
        # TODO(js-i18n): Compare all default-locale template files instead of
        # only the primary path returned by get_pot_file_path().
        base_path = self.get_pot_file_path()
        if not Utils.exists_with_retry(base_path):
            return True
        try:
            with open(base_path, "r", encoding="utf-8") as f:
                before = f.read()
            if not self.generate_pot_file():
                return True
            with open(base_path, "r", encoding="utf-8") as f:
                after = f.read()
            return before != after
        except Exception:
            return True

