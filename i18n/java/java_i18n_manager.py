import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from i18n.translation_group import TranslationGroup, TranslationKey
from ..file_topology_manager import FileTopologyManager
from ..i18n_manager_base import I18NManagerBase
from ..translation_manager_results import LocaleStatus, TranslationAction, TranslationManagerResults
from utils.logging_setup import get_logger

logger = get_logger("java_i18n_manager")


class JavaI18NManager(I18NManagerBase):
    """Manage Java ResourceBundle-style `.properties` translations.

    Implemented:
    - Multi-bundle file support (e.g. messages, errors, client-specific bundles)
    - Topology parity based on default locale bundle file layout
    - Logical-line parsing for continuations and escaped separators
    """

    BASE_BUNDLE_NAME = "messages"

    def __init__(self, directory, locales=None, intro_details=None, settings_manager=None):
        logger.info(f"Initializing JavaI18NManager with directory: {directory}, locales: {locales}")
        super().__init__(directory, locales or [], intro_details, settings_manager)
        self._bundle_files_by_locale: Dict[str, Dict[str, str]] = {}
        self._default_bundle_templates: Dict[str, str] = {}
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
            os.path.join(self._directory, "src", "main", "resources"),
            os.path.join(self._directory, "resources"),
            os.path.join(self._directory, "locale"),
            os.path.join(self._directory, "locales"),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                rel = os.path.relpath(candidate, self._directory)
                logger.info(f"Using Java locale directory: {rel}")
                return rel
        logger.info("No Java locale directory found. Defaulting to src/main/resources")
        return os.path.join("src", "main", "resources")

    def set_directory(self, directory: str):
        self._directory = directory
        self.translations = {}
        self.written_locales = set()
        self.locales = []
        self._locale_dir = self._detect_locale_directory()
        self._bundle_files_by_locale = {}
        self._default_bundle_templates = {}
        self._topology_manager = FileTopologyManager(
            os.path.join(self._directory, self._locale_dir),
            self.default_locale,
        )

    def _create_results(self, action: TranslationAction) -> TranslationManagerResults:
        locale_dir = os.path.join(self._directory, self._locale_dir)
        has_locale_dir = os.path.isdir(locale_dir)
        statuses: Dict[str, LocaleStatus] = {}
        bundle_files_by_locale, _ = self._scan_bundle_files()

        for locale, bundle_files in bundle_files_by_locale.items():
            existing_files = [path for path in bundle_files.values() if os.path.exists(path)]
            last_modified = (
                datetime.fromtimestamp(max(os.path.getmtime(path) for path in existing_files))
                if existing_files else None
            )
            statuses[locale] = LocaleStatus(
                locale_code=locale,
                has_directory=has_locale_dir,
                has_po_file=bool(existing_files),
                has_mo_file=False,
                po_file_path=existing_files[0] if existing_files else None,
                mo_file_path=None,
                last_modified=last_modified,
            )

        base_path = self.get_pot_file_path()
        has_base = os.path.exists(base_path)
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

    def _default_primary_bundle_template(self) -> str:
        locale_dir = os.path.join(self._directory, self._locale_dir)
        if self._default_bundle_templates:
            return sorted(self._default_bundle_templates.values())[0]
        return os.path.join(locale_dir, f"{self.BASE_BUNDLE_NAME}.properties")

    def _bundle_path_for_locale(self, locale: str) -> str:
        template = self._default_primary_bundle_template()
        if locale == self.default_locale:
            return template
        translated = self._topology_manager.translate_file_path(template, locale)
        if translated:
            return translated
        locale_dir = os.path.join(self._directory, self._locale_dir)
        return os.path.join(locale_dir, f"{self.BASE_BUNDLE_NAME}_{locale}.properties")

    def _extract_locale_suffix(self, stem: str) -> Optional[Tuple[str, str]]:
        match = re.match(
            r"^(?P<bundle>.+)_(?P<locale>[A-Za-z]{2}(?:[_-][A-Za-z0-9]+){0,2})$",
            stem,
        )
        if not match:
            return None
        return match.group("bundle"), match.group("locale")

    def _bundle_id_for_path(self, rel_path: str, bundle_stem: str) -> str:
        rel_dir = os.path.dirname(rel_path).replace("\\", "/")
        if rel_dir and rel_dir != ".":
            return f"{rel_dir}/{bundle_stem}"
        return bundle_stem

    def _scan_bundle_files(self) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
        locale_dir = os.path.join(self._directory, self._locale_dir)
        if not os.path.isdir(locale_dir):
            return {}, {}

        unsuffixed_files: Dict[str, str] = {}
        localized_candidates: list[tuple[str, str, str, str]] = []

        for file_path in Path(locale_dir).rglob("*.properties"):
            rel_path = os.path.relpath(str(file_path), locale_dir)
            stem = file_path.stem
            parsed = self._extract_locale_suffix(stem)
            if parsed:
                bundle_stem, locale = parsed
                bundle_id = self._bundle_id_for_path(rel_path, bundle_stem)
                localized_candidates.append((bundle_id, locale, str(file_path), rel_path))
            else:
                bundle_id = self._bundle_id_for_path(rel_path, stem)
                unsuffixed_files[bundle_id] = str(file_path)

        default_templates: Dict[str, str] = {}
        bundle_files_by_locale: Dict[str, Dict[str, str]] = {}

        if unsuffixed_files:
            default_templates.update(unsuffixed_files)
            bundle_files_by_locale[self.default_locale] = dict(unsuffixed_files)

        default_variants = {self.default_locale, self.default_locale.replace("-", "_"), self.default_locale.replace("_", "-")}
        for bundle_id, locale, full_path, _ in localized_candidates:
            if locale in default_variants and bundle_id not in default_templates:
                default_templates[bundle_id] = full_path

        if self.default_locale not in bundle_files_by_locale and default_templates:
            bundle_files_by_locale[self.default_locale] = dict(default_templates)

        for bundle_id, locale, full_path, _ in localized_candidates:
            canonical_locale = locale
            if locale in default_variants:
                canonical_locale = self.default_locale
            if canonical_locale not in bundle_files_by_locale:
                bundle_files_by_locale[canonical_locale] = {}
            bundle_files_by_locale[canonical_locale][bundle_id] = full_path

        return bundle_files_by_locale, default_templates

    def _decode_properties_value(self, value: str) -> str:
        return self._unescape_properties_text(value)

    def _encode_properties_value(self, value: str) -> str:
        return self._escape_properties_text(value, is_key=False)

    def _encode_properties_key(self, key: str) -> str:
        return self._escape_properties_text(key, is_key=True)

    def _escape_properties_text(self, text: str, is_key: bool) -> str:
        escaped = (
            text.replace("\\", r"\\")
            .replace("\n", r"\n")
            .replace("\r", r"\r")
            .replace("\t", r"\t")
            .replace("\f", r"\f")
        )
        if is_key:
            escaped = escaped.replace(" ", r"\ ").replace(":", r"\:").replace("=", r"\=")
        return escaped

    def _unescape_properties_text(self, text: str) -> str:
        result: list[str] = []
        i = 0
        while i < len(text):
            char = text[i]
            if char != "\\":
                result.append(char)
                i += 1
                continue
            i += 1
            if i >= len(text):
                result.append("\\")
                break
            esc = text[i]
            if esc == "t":
                result.append("\t")
            elif esc == "n":
                result.append("\n")
            elif esc == "r":
                result.append("\r")
            elif esc == "f":
                result.append("\f")
            elif esc == "u" and i + 4 < len(text):
                code = text[i + 1:i + 5]
                try:
                    result.append(chr(int(code, 16)))
                    i += 4
                except ValueError:
                    result.append("\\u" + code)
                    i += 4
            else:
                result.append(esc)
            i += 1
        return "".join(result)

    def _is_continuation_line(self, line: str) -> bool:
        backslash_count = 0
        for char in reversed(line):
            if char != "\\":
                break
            backslash_count += 1
        return (backslash_count % 2) == 1

    def _iter_logical_properties_lines(self, file_path: str):
        with open(file_path, "r", encoding="utf-8") as f:
            pending = ""
            for raw in f:
                line = raw.rstrip("\n\r")
                if pending:
                    line = line.lstrip(" \t\f")
                    pending += line
                else:
                    pending = line

                if self._is_continuation_line(pending):
                    pending = pending[:-1]
                    continue

                logical = pending
                pending = ""
                stripped = logical.lstrip()
                if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                    continue
                yield logical

            if pending:
                stripped = pending.lstrip()
                if stripped and not stripped.startswith("#") and not stripped.startswith("!"):
                    yield pending

    def _split_properties_entry(self, line: str) -> tuple[str, str]:
        key_end = None
        value_start = None
        escaped = False

        for idx, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char in {"=", ":"}:
                key_end = idx
                value_start = idx + 1
                break
            if char in {" ", "\t", "\f"}:
                key_end = idx
                value_start = idx + 1
                while value_start < len(line) and line[value_start] in {" ", "\t", "\f"}:
                    value_start += 1
                if value_start < len(line) and line[value_start] in {"=", ":"}:
                    value_start += 1
                while value_start < len(line) and line[value_start] in {" ", "\t", "\f"}:
                    value_start += 1
                break

        if key_end is None:
            key = line
            value = ""
        else:
            key = line[:key_end]
            value = line[value_start:] if value_start is not None else ""

        return key, value

    def _parse_properties_file(self, file_path: str, locale: str, bundle_id: str, is_base: bool):
        for logical_line in self._iter_logical_properties_lines(file_path):
            key, value = self._split_properties_entry(logical_line)
            key = self._unescape_properties_text(key)
            key = key.strip()
            if not key:
                continue

            translation_key = TranslationKey(key, context=bundle_id)
            if is_base:
                self._topology_manager.set_source_file(str(translation_key), locale, file_path)
            elif self._topology_manager.get_source_file(str(translation_key), locale) is None:
                self._topology_manager.set_source_file(str(translation_key), locale, file_path)

            if value is None:
                value = ""
            value = self._decode_properties_value(value)

            if translation_key not in self.translations:
                self.translations[translation_key] = TranslationGroup(key, is_in_base=is_base, context=bundle_id)
            group = self.translations[translation_key]
            if is_base:
                group.is_in_base = True
            group.add_translation(locale, value)

    def _bundle_templates_for_writing(self) -> Dict[str, str]:
        templates = dict(self._default_bundle_templates)
        if not templates:
            templates[self.BASE_BUNDLE_NAME] = self._default_primary_bundle_template()

        locale_dir = os.path.join(self._directory, self._locale_dir)
        for key, group in self.translations.items():
            if not group.is_in_base:
                continue
            bundle_id = key.context or self.BASE_BUNDLE_NAME
            if bundle_id not in templates:
                templates[bundle_id] = os.path.join(locale_dir, f"{bundle_id}.properties")
        return templates

    def _bundle_file_path_for_locale(self, bundle_id: str, locale: str) -> str:
        templates = self._bundle_templates_for_writing()
        default_file = templates.get(bundle_id, self._default_primary_bundle_template())
        if locale == self.default_locale:
            return default_file
        translated = self._topology_manager.translate_file_path(default_file, locale)
        if translated:
            return translated
        stem = os.path.splitext(default_file)[0]
        return f"{stem}_{locale}.properties"

    def _collect_bundle_entries_for_locale(self, locale: str) -> Dict[str, Dict[str, str]]:
        bundle_entries: Dict[str, Dict[str, str]] = {}
        for key, group in self.translations.items():
            if not group.is_in_base:
                continue
            bundle_id = key.context or self.BASE_BUNDLE_NAME
            if bundle_id not in bundle_entries:
                bundle_entries[bundle_id] = {}
            bundle_entries[bundle_id][key.msgid] = group.get_translation_unescaped(locale) or ""
        return bundle_entries

    def _discover_locales_from_bundle_files(self, bundle_files_by_locale: Dict[str, Dict[str, str]]) -> list[str]:
        locales = sorted(bundle_files_by_locale.keys())
        if self.default_locale not in locales and bundle_files_by_locale:
            locales.insert(0, self.default_locale)
        return locales

    def _load_bundle_state(self):
        self._bundle_files_by_locale, self._default_bundle_templates = self._scan_bundle_files()
        self.locales = self._discover_locales_from_bundle_files(self._bundle_files_by_locale)
        self._topology_manager.reset()
        for path in self._default_bundle_templates.values():
            self._topology_manager.add_default_locale_file(path)

    def _parse_loaded_bundle_files(self):
        default_bundles = self._bundle_files_by_locale.get(self.default_locale, {})
        for bundle_id, file_path in default_bundles.items():
            if os.path.exists(file_path):
                self._parse_properties_file(file_path, self.default_locale, bundle_id, is_base=True)

        for locale, bundles in self._bundle_files_by_locale.items():
            if locale == self.default_locale:
                continue
            for bundle_id, file_path in bundles.items():
                if os.path.exists(file_path):
                    self._parse_properties_file(file_path, locale, bundle_id, is_base=False)

    def _load_current_bundle_file_path(self, locale: str, bundle_id: str) -> Optional[str]:
        if locale not in self._bundle_files_by_locale:
            return None
        return self._bundle_files_by_locale[locale].get(bundle_id)

    def _persist_bundle_file(self, file_path: str, locale: str, entries: Dict[str, str], bundle_id: str):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# Translations for locale: {locale}\n")
            f.write(f"# Bundle: {bundle_id}\n")
            for msgid in sorted(entries.keys()):
                f.write(
                    f"{self._encode_properties_key(msgid)}={self._encode_properties_value(entries[msgid])}\n"
                )

    def _ensure_default_primary_template(self):
        if self._default_bundle_templates:
            return
        primary = self._default_primary_bundle_template()
        self._default_bundle_templates = {self.BASE_BUNDLE_NAME: primary}
        self._topology_manager.add_default_locale_file(primary)

    def manage_translations(
        self,
        action: TranslationAction = TranslationAction.CHECK_STATUS,
        modified_locales=None,
    ):
        results = self._create_results(action)
        results.failed_locales = []
        results.action_successful = True

        try:
            if action == TranslationAction.CHECK_STATUS:
                self.translations = {}
                self._load_bundle_state()
                self._parse_loaded_bundle_files()

            if self.translations:
                results.total_strings = len(self.translations)
                results.total_locales = len(self.locales)
                results.invalid_groups = self.get_invalid_translations()

            if action == TranslationAction.WRITE_PO_FILES:
                if self.fix_invalid_translations():
                    logger.debug("Applied automatic translation fixes before Java write")
                self.write_po_files(modified_locales, results)
            elif action == TranslationAction.WRITE_MO_FILES:
                self.create_mo_files(results)
            elif action == TranslationAction.GENERATE_POT:
                if not self.generate_pot_file():
                    results.action_successful = False
                    results.extend_error_message("Failed to generate Java base properties file")

            results.determine_action_successful()
            return results
        except Exception as exc:
            logger.error(f"Error in Java manager: {exc}", exc_info=True)
            results.action_successful = False
            results.error_message = str(exc)
            return results

    def get_po_file_path(self, locale: str) -> str:
        return self._bundle_path_for_locale(locale)

    def get_pot_file_path(self) -> str:
        return self._bundle_path_for_locale(self.default_locale)

    def generate_pot_file(self) -> bool:
        try:
            os.makedirs(os.path.join(self._directory, self._locale_dir), exist_ok=True)
            self._load_bundle_state()
            self._ensure_default_primary_template()
            base_path = self._default_primary_bundle_template()
            if os.path.exists(base_path):
                return True
            with open(base_path, "w", encoding="utf-8") as f:
                f.write("# Base translations for Java ResourceBundle\n")
            return True
        except Exception as exc:
            logger.error(f"Failed generating Java base properties: {exc}", exc_info=True)
            return False

    def create_mo_files(self, results: TranslationManagerResults):
        logger.info("Java properties translations do not require compilation. Skipping.")

    def write_po_files(self, modified_locales, results: TranslationManagerResults):
        self._load_bundle_state()
        self._ensure_default_primary_template()
        # TODO(java-i18n-parity-policy): We currently align locale file topology
        # with the default locale templates. If a non-default locale intentionally
        # diverges (client-specific split/merge), add an opt-out policy and avoid
        # forcing parity for that locale.
        locales_to_write = set(modified_locales or self.locales or [self.default_locale])
        locales_to_write.add(self.default_locale)

        for locale in sorted(locales_to_write):
            try:
                entries_by_bundle = self._collect_bundle_entries_for_locale(locale)
                for bundle_id in sorted(self._bundle_templates_for_writing().keys()):
                    file_path = self._bundle_file_path_for_locale(bundle_id, locale)
                    entries = entries_by_bundle.get(bundle_id, {})
                    self._persist_bundle_file(file_path, locale, entries, bundle_id)
                self.written_locales.add(locale)
            except Exception as exc:
                logger.error(f"Failed writing Java translations for {locale}: {exc}", exc_info=True)
                results.failed_locales.append(locale)

        if results.failed_locales:
            results.extend_error_message(f"Failed to write properties files for locales: {results.failed_locales}")
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
        literal_pattern = re.compile(r'"([^"\n]{3,})"')

        for root, _, files in os.walk(project_dir):
            for file_name in files:
                if not file_name.endswith((".java", ".kt")):
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
                        if "getString(" in content[max(0, match.start() - 40):match.start() + 5]:
                            continue
                        strings.append(text)
                    if strings:
                        results[os.path.relpath(file_path, project_dir)] = strings
                except Exception as exc:
                    logger.warning(f"Error scanning file {file_path}: {exc}")
        return results

    def check_translations_changed(self, include_stale_translations: bool = False) -> bool:
        # TODO(java-i18n): Compare all default-locale bundle templates, not only
        # the first primary bundle file. Current check is conservative.
        base_path = self.get_pot_file_path()
        if not os.path.exists(base_path):
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

