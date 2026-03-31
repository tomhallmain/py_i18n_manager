import json
import os
from collections import Counter
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.globals import ProjectType

from utils.logging_setup import get_logger
from utils.utils import Utils

logger = get_logger("settings_manager")

class SettingsManager:
    MAX_RECENT_PROJECTS = 10
    DEFAULT_LLM_CJK_REJECT_THRESHOLD_PERCENTAGE = 30
    DEFAULT_QUALITY_REVIEW_SCRIPT_IGNORE_PATTERNS = [
        # Keyboard shortcuts / key combos (e.g. Ctrl+S, Cmd+Shift+P).
        r"(?i)\b(?:Ctrl|Cmd|Shift)(?:(?:\+Shift)?\+[A-Za-z])?\b",
        # Common UX acknowledgements and short acronyms often left untranslated.
        r"(?i)\b(?:OK|FAQ|ETA|TBD|FYI|ASAP)\b",
        # Common technical acronyms often kept in English.
        r"(?i)\b(?:API|SDK|CLI|GUI|UI|UX|CPU|GPU|RAM|DNS|TCP|UDP|HTTP|HTTPS|URL|URI|SQL|UTC|ID)\b",
        r"(?i)\bCSV\b",
        r"(?i)\bHTML\b",
        r"(?i)\bJSON\b",
        r"(?i)\bXML\b",
        r"(?i)\bYAML\b",
        # Common uppercase file-type terms (no leading dot), e.g. "PDF", "JSON", "MP4".
        # Keep this practical/common only: no single-letter and no niche extensions.
        r"\b(?:JSON|YML|YAML|XML|CSV|TSV|TXT|LOG|MD|PDF|PNG|JPG|JPEG|GIF|WEBP|SVG|MP3|MP4|WAV|ZIP|EXE|APK|IPA|JS|TS|JSX|TSX|PY|RB|JAVA|KT|GO|RS|SQL|INI|CFG|CONF|TOML)s?\b",
        # Common file extensions.
        r"(?i)\.(?:json|yml|yaml|xml|csv|tsv|txt|log|md|pdf|png|jpe?g|gif|webp|svg|mp3|mp4|wav|zip|tar|gz|7z|exe|msi|dmg|apk|ipa|js|ts|jsx|tsx|py|rb|java|kt|go|rs|c|cpp|h|hpp|ini|cfg|conf|toml|lock|sql)\b",
    ]

    # Conservative default for local / low-context models: catalog slice only (system + reply live outside).
    DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS = 2400
    
    def __init__(self):
        override_path = os.environ.get("PY_I18N_MANAGER_SETTINGS_PATH", "").strip()
        if override_path:
            self.settings_file = Path(override_path)
        else:
            self.settings_file = Path.home() / '.i18n_manager' / 'settings.json'
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_settings_schema()

    def _migrate_settings_schema(self) -> None:
        """Migrate legacy settings keys to current schema."""
        if not self.settings_file.exists():
            return
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if not isinstance(settings, dict):
                return
            project_settings = settings.get("project_settings")
            if not isinstance(project_settings, dict):
                return

            changed = False
            for _project_path, cfg in project_settings.items():
                if not isinstance(cfg, dict):
                    continue

                old_patterns_key = "quality_review_latin_ignore_patterns"
                new_patterns_key = "quality_review_script_ignore_patterns"
                old_init_key = "quality_review_latin_ignore_patterns_initialized"
                new_init_key = "quality_review_script_ignore_patterns_initialized"

                if old_patterns_key in cfg:
                    if new_patterns_key not in cfg:
                        cfg[new_patterns_key] = cfg[old_patterns_key]
                    del cfg[old_patterns_key]
                    changed = True

                if old_init_key in cfg:
                    if new_init_key not in cfg:
                        cfg[new_init_key] = cfg[old_init_key]
                    del cfg[old_init_key]
                    changed = True

            if changed:
                with open(self.settings_file, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=4)
        except Exception as e:
            logger.warning("Could not migrate settings schema: %s", e)

    def load_last_project(self) -> Optional[str]:
        """Load the last selected project path from settings.
        
        Returns:
            str: The project path if it exists and is valid, None otherwise
        """
        if not self.settings_file.exists():
            return None
            
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                project_path = settings.get('last_project')
                
                # Validate the project path
                if project_path and Utils.exists_with_retry(project_path):
                    return project_path
                return None
        except Exception:
            return None

    def _fill_recent_projects_to_max(self, existing_valid: list[str], settings: dict) -> list[str]:
        """Merge stored recent paths with last_project and project_settings, up to MAX_RECENT_PROJECTS.

        Order: last_project first (if valid and not already placed), then existing list order,
        then other paths from project_settings by last_bulk_analysis_time (newest first).
        """
        out: list[str] = []
        seen: set[str] = set()
        max_n = self.MAX_RECENT_PROJECTS

        last = settings.get("last_project")
        if last and Utils.exists_with_retry(last):
            out.append(last)
            seen.add(last)

        for p in existing_valid:
            if len(out) >= max_n:
                break
            if p not in seen and Utils.exists_with_retry(p):
                out.append(p)
                seen.add(p)

        project_settings = settings.get("project_settings") or {}

        def sort_key(p: str) -> tuple:
            cfg = project_settings.get(p, {})
            t = cfg.get("last_bulk_analysis_time") or ""
            return (t, p)

        candidates = sorted(
            (p for p in project_settings if p not in seen and Utils.exists_with_retry(p)),
            key=sort_key,
            reverse=True,
        )
        for p in candidates:
            if len(out) >= max_n:
                break
            out.append(p)
            seen.add(p)

        return out

    def load_recent_projects(self) -> list[str]:
        """Load the list of recent projects from settings.
        
        Returns:
            list: List of valid project paths
        """
        if not self.settings_file.exists():
            return []
            
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                recent_projects = settings.get('recent_projects', [])
                
                # Filter out invalid paths
                valid_before = [p for p in recent_projects if Utils.exists_with_retry(p)]
                valid_projects = self._fill_recent_projects_to_max(valid_before, settings)
                merged = valid_projects != valid_before

                # Persist when we pruned invalid entries or merged in paths to reach up to MAX_RECENT_PROJECTS
                if len(valid_before) != len(recent_projects) or merged:
                    settings['recent_projects'] = valid_projects
                    with open(self.settings_file, 'w') as f:
                        json.dump(settings, f, indent=4)
                        
                return valid_projects
        except Exception:
            return []
            
    def save_last_project(self, project_path):
        """Save the last selected project path to settings and update recent projects.
        
        Args:
            project_path (str): The path to save
        """
        try:
            settings = {}
            if self.settings_file.exists():
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    
            # Update last project
            settings['last_project'] = project_path
            
            # Update recent projects
            recent_projects = settings.get('recent_projects', [])
            
            # Remove if already exists
            if project_path in recent_projects:
                recent_projects.remove(project_path)
                
            # Add to front
            recent_projects.insert(0, project_path)
            
            # Limit to MAX_RECENT_PROJECTS
            recent_projects = recent_projects[:self.MAX_RECENT_PROJECTS]
            
            settings['recent_projects'] = recent_projects
            
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            logger.warning("Could not save last project / recent projects: %s", e)
            
    def remove_project(self, project_path):
        """Remove a project from recent projects list.
        
        Args:
            project_path (str): The path to remove
        """
        try:
            if not self.settings_file.exists():
                return
                
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                
            # Remove from recent projects
            recent_projects = settings.get('recent_projects', [])
            if project_path in recent_projects:
                recent_projects.remove(project_path)
                settings['recent_projects'] = recent_projects
                
            # If it was the last project, clear that too
            if settings.get('last_project') == project_path:
                settings['last_project'] = None
                
            # Also remove project-specific settings
            project_settings = settings.get('project_settings', {})
            if project_path in project_settings:
                del project_settings[project_path]
                settings['project_settings'] = project_settings
                
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass  # Silently fail if we can't save settings

    def get_project_setting(self, project_path: str, key: str, default: Any = None) -> Any:
        """Get a project-specific setting.
        
        Args:
            project_path (str): Path to the project
            key (str): Setting key to retrieve
            default (Any): Default value if setting doesn't exist
            
        Returns:
            Any: The setting value or default
        """
        try:
            if not self.settings_file.exists():
                return default
                
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                
            project_settings = settings.get('project_settings', {})
            project_config = project_settings.get(project_path, {})
            
            return project_config.get(key, default)
            
        except Exception as e:
            logger.error(f"Error getting project setting {key} for {project_path}: {e}")
            return default
            
    def save_project_setting(self, project_path: str, key: str, value: Any) -> bool:
        """Save a project-specific setting.
        
        Args:
            project_path (str): Path to the project
            key (str): Setting key to save
            value (Any): Value to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            settings = {}
            if self.settings_file.exists():
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    
            # Initialize project_settings if it doesn't exist
            if 'project_settings' not in settings:
                settings['project_settings'] = {}
                
            # Initialize project config if it doesn't exist
            if project_path not in settings['project_settings']:
                settings['project_settings'][project_path] = {}
                
            # Save the setting
            settings['project_settings'][project_path][key] = value
            
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
                
            return True
            
        except Exception as e:
            logger.error(f"Error saving project setting {key} for {project_path}: {e}")
            return False
            
    def get_project_default_locale(self, project_path: str) -> str:
        """Get the default locale for a specific project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            str: Default locale for the project, or global default if not set
        """
        # Try to get project-specific default locale
        project_default = self.get_project_setting(project_path, 'default_locale')
        if project_default:
            return project_default
            
        # Fall back to global default from config_manager
        from utils.config import config_manager
        return config_manager.get('translation.default_locale', 'en')
            
    def save_project_default_locale(self, project_path: str, default_locale: str) -> bool:
        """Save the default locale for a specific project.
        
        Args:
            project_path (str): Path to the project
            default_locale (str): Default locale to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.save_project_setting(project_path, 'default_locale', default_locale)
        
    def get_project_locales(self, project_path: str) -> list[str]:
        """Get the list of locales for a specific project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            list[str]: List of locales for the project, or empty list if not set
        """
        return self.get_project_setting(project_path, 'locales', [])
        
    def save_project_locales(self, project_path: str, locales: list[str]) -> bool:
        """Save the list of locales for a specific project.
        
        Args:
            project_path (str): Path to the project
            locales (list[str]): List of locales to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.save_project_setting(project_path, 'locales', locales)

    def get_commonly_used_locale_counts(
        self,
        exclude_locales: Optional[set[str] | frozenset[str]] = None,
    ) -> dict[str, int]:
        """Count how often each locale appears across all projects' saved ``locales`` lists.

        Excludes any locale in ``exclude_locales`` (e.g. locales already configured for
        the project being edited). Result order is descending by count, then by locale id.

        Returns:
            dict[str, int]: Locale tag -> number of projects that list it.
        """
        excluded = frozenset(exclude_locales or ())
        counts: Counter[str] = Counter()
        if not self.settings_file.exists():
            return {}
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
            for _path, cfg in (settings.get("project_settings") or {}).items():
                for loc in cfg.get("locales") or []:
                    if not isinstance(loc, str) or not loc.strip():
                        continue
                    loc = loc.strip()
                    if loc in excluded:
                        continue
                    counts[loc] += 1
            # Preserve descending count, then alphabetical
            ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
            return dict(ordered)
        except Exception as e:
            logger.warning("Could not aggregate commonly used locales: %s", e)
            return {}

    def get_project_type(self, project_path: str) -> Optional[str]:
        """Get the project type for a specific project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[str]: Project type if set, None otherwise
        """
        return self.get_project_setting(project_path, 'project_type')
    
    def get_project_type_as_type(self, project_path: str) -> Optional['ProjectType']:
        """Get the project type for a specific project as a ProjectType enum.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[ProjectType]: ProjectType enum if set and valid, None otherwise
        """
        project_type_str = self.get_project_setting(project_path, 'project_type')
        if not project_type_str:
            return None
        
        try:
            from utils.globals import ProjectType
            return ProjectType(project_type_str)
        except ValueError:
            return None
        
    def save_project_type(self, project_path: str, project_type: str) -> bool:
        """Save the project type for a specific project.
        
        Args:
            project_path (str): Path to the project
            project_type (str): Project type to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.save_project_setting(project_path, 'project_type', project_type)

    # --- Translation quality review (per-project) ---------------------------------

    def get_quality_review_excluded_msgids(self, project_path: str) -> list[str]:
        """Msgids skipped by built-in heuristic quality review for this project."""
        raw = self.get_project_setting(project_path, "quality_review_excluded_msgids", [])
        if not isinstance(raw, list):
            return []
        return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]

    def save_quality_review_excluded_msgids(self, project_path: str, msgids: list[str]) -> bool:
        """Persist excluded msgids for quality review heuristics."""
        cleaned = sorted({str(x).strip() for x in msgids if isinstance(x, str) and str(x).strip()})
        return self.save_project_setting(project_path, "quality_review_excluded_msgids", cleaned)

    def get_quality_review_custom_rules(self, project_path: str) -> list[dict]:
        """User-defined business rules for quality review (schema TBD; stored as JSON objects)."""
        raw = self.get_project_setting(project_path, "quality_review_custom_rules", [])
        if not isinstance(raw, list):
            return []
        return [x for x in raw if isinstance(x, dict)]

    def save_quality_review_custom_rules(self, project_path: str, rules: list[dict]) -> bool:
        """Persist custom quality-review rules for this project."""
        cleaned = [dict(x) for x in rules if isinstance(x, dict)]
        return self.save_project_setting(project_path, "quality_review_custom_rules", cleaned)

    def get_quality_review_script_ignore_patterns(self, project_path: str) -> list[str]:
        """Regex patterns removed before script-based quality/character-set checks."""
        self._ensure_quality_review_script_ignore_patterns_seeded(project_path)
        raw = self.get_project_setting(project_path, "quality_review_script_ignore_patterns", [])
        if not isinstance(raw, list):
            return []
        return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]

    def save_quality_review_script_ignore_patterns(self, project_path: str, patterns: list[str]) -> bool:
        """Persist regex ignore patterns for script-based checks."""
        cleaned = sorted({str(x).strip() for x in patterns if isinstance(x, str) and str(x).strip()})
        ok_patterns = self.save_project_setting(
            project_path, "quality_review_script_ignore_patterns", cleaned
        )
        ok_marker = self.save_project_setting(
            project_path, "quality_review_script_ignore_patterns_initialized", True
        )
        return ok_patterns and ok_marker

    @classmethod
    def get_default_quality_review_script_ignore_patterns(cls) -> list[str]:
        """Default regex patterns seeded per project for false-positive reduction."""
        return list(cls.DEFAULT_QUALITY_REVIEW_SCRIPT_IGNORE_PATTERNS)

    def reset_quality_review_script_ignore_patterns_to_defaults(self, project_path: str) -> bool:
        """Reset project ignore patterns to defaults."""
        return self.save_quality_review_script_ignore_patterns(
            project_path, self.get_default_quality_review_script_ignore_patterns()
        )

    def _ensure_quality_review_script_ignore_patterns_seeded(self, project_path: str) -> None:
        """Seed per-project ignore patterns once; user edits remain authoritative afterwards."""
        initialized = bool(
            self.get_project_setting(
                project_path, "quality_review_script_ignore_patterns_initialized", False
            )
        )
        if initialized:
            return
        existing = self.get_project_setting(project_path, "quality_review_script_ignore_patterns")
        if not isinstance(existing, list):
            # One-time migration path from old key naming.
            existing = self.get_project_setting(
                project_path, "quality_review_latin_ignore_patterns"
            )
        if isinstance(existing, list) and existing:
            cleaned = sorted(
                {
                    str(x).strip()
                    for x in existing
                    if isinstance(x, str) and str(x).strip()
                }
            )
            self.save_project_setting(
                project_path, "quality_review_script_ignore_patterns", cleaned
            )
            self.save_project_setting(
                project_path, "quality_review_script_ignore_patterns_initialized", True
            )
            return
        self.save_project_setting(
            project_path,
            "quality_review_script_ignore_patterns",
            self.get_default_quality_review_script_ignore_patterns(),
        )
        self.save_project_setting(
            project_path, "quality_review_script_ignore_patterns_initialized", True
        )

    def get_quality_review_llm_max_catalog_tokens(self, project_path: str) -> int:
        """Max estimated tokens per catalog batch for LLM review (conservative for local / small context)."""
        v = self.get_project_setting(project_path, "quality_review_llm_max_catalog_tokens")
        if v is None:
            return self.DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS
        try:
            n = int(v)
            return max(128, min(n, 32000))
        except (TypeError, ValueError):
            return self.DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS

    def save_quality_review_llm_max_catalog_tokens(self, project_path: str, max_tokens: int) -> bool:
        """Save max estimated catalog tokens per LLM batch for this project."""
        try:
            n = int(max_tokens)
        except (TypeError, ValueError):
            n = self.DEFAULT_QUALITY_REVIEW_LLM_MAX_CATALOG_TOKENS
        n = max(128, min(n, 32000))
        return self.save_project_setting(project_path, "quality_review_llm_max_catalog_tokens", n)

    def get_intro_details(self) -> dict[str, str]:
        """Get the intro details from config_manager (default config).
        
        Returns:
            dict: Dictionary containing intro details with keys:
                - first_author
                - last_translator
                - application_name
                - version
        """
        from utils.config import config_manager
        defaults = (
            "THOMAS HALL <tomhall.main@gmail.com>",
            "Thomas Hall <tomhall.main@gmail.com>",
            "APPLICATION",
            "1.0",
        )
        return {
            "first_author": config_manager.get("intro_details.default_first_author", defaults[0]),
            "last_translator": config_manager.get("intro_details.default_last_translator", defaults[1]),
            "application_name": config_manager.get("intro_details.default_application_name", defaults[2]),
            "version": config_manager.get("intro_details.default_version", defaults[3]),
        }

    def save_intro_details(self, intro_details: dict[str, str]):
        """Save intro details to settings.
        
        Args:
            intro_details (dict): Dictionary containing intro details
        """
        try:
            settings = {}
            if self.settings_file.exists():
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    
            settings['intro_details'] = intro_details
            
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving intro details: {e}")

    def get_llm_prompt_template(self, project_path: Optional[str] = None) -> str:
        """Get the LLM prompt template, with project override if available.
        
        Args:
            project_path (str, optional): Path to the project for project-specific override
            
        Returns:
            str: The prompt template (project-specific if set, otherwise global default)
        """
        # Try project-specific override first
        if project_path:
            project_template = self.get_project_setting(project_path, 'llm_prompt_template')
            if project_template:
                return project_template
        
        # Fall back to global default from config_manager
        from utils.config import config_manager
        return config_manager.get('translation.llm_prompt_template', self.get_default_llm_prompt_template())
    
    def save_llm_prompt_template(self, template: str, project_path: Optional[str] = None) -> bool:
        """Save the LLM prompt template.
        
        Args:
            template (str): The prompt template to save
            project_path (str, optional): If provided, saves as project-specific override
            
        Returns:
            bool: True if successful, False otherwise
        """
        if project_path:
            return self.save_project_setting(project_path, 'llm_prompt_template', template)
        else:
            # Save to global config
            from utils.config import config_manager
            return config_manager.set('translation.llm_prompt_template', template)
    
    def clear_project_llm_prompt_template(self, project_path: str) -> bool:
        """Clear the project-specific LLM prompt template (revert to global default).
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.settings_file.exists():
                return True
                
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
            
            project_settings = settings.get('project_settings', {})
            project_config = project_settings.get(project_path, {})
            
            if 'llm_prompt_template' in project_config:
                del project_config['llm_prompt_template']
                settings['project_settings'][project_path] = project_config
                
                with open(self.settings_file, 'w') as f:
                    json.dump(settings, f, indent=4)
            
            return True
            
        except Exception as e:
            logger.error(f"Error clearing project LLM prompt template for {project_path}: {e}")
            return False
    
    def has_project_llm_prompt_template(self, project_path: str) -> bool:
        """Check if a project has a custom LLM prompt template override.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            bool: True if project has a custom template, False otherwise
        """
        return self.get_project_setting(project_path, 'llm_prompt_template') is not None

    def get_llm_cjk_reject_threshold_percentage(self, project_path: Optional[str] = None) -> int:
        """Get the CJK rejection threshold percentage for LLM responses.

        Args:
            project_path (str, optional): Path to project for project-specific override.

        Returns:
            int: Threshold percentage (0-100).
        """
        default_threshold = self.DEFAULT_LLM_CJK_REJECT_THRESHOLD_PERCENTAGE
        threshold = None

        if project_path:
            threshold = self.get_project_setting(project_path, 'llm_cjk_reject_threshold_percentage')

        if threshold is None:
            from utils.config import config_manager
            threshold = config_manager.get('translation.llm_cjk_reject_threshold_percentage', default_threshold)

        try:
            return max(0, min(100, int(threshold)))
        except (TypeError, ValueError):
            return default_threshold

    def save_llm_cjk_reject_threshold_percentage(self, threshold_percentage: int,
                                                 project_path: Optional[str] = None) -> bool:
        """Save the CJK rejection threshold percentage for LLM responses."""
        threshold_percentage = max(0, min(100, int(threshold_percentage)))
        if project_path:
            return self.save_project_setting(project_path, 'llm_cjk_reject_threshold_percentage', threshold_percentage)
        from utils.config import config_manager
        return config_manager.set('translation.llm_cjk_reject_threshold_percentage', threshold_percentage)

    def clear_project_llm_cjk_reject_threshold(self, project_path: str) -> bool:
        """Clear the project-specific CJK rejection threshold override."""
        try:
            if not self.settings_file.exists():
                return True

            with open(self.settings_file, 'r') as f:
                settings = json.load(f)

            project_settings = settings.get('project_settings', {})
            project_config = project_settings.get(project_path, {})

            if 'llm_cjk_reject_threshold_percentage' in project_config:
                del project_config['llm_cjk_reject_threshold_percentage']
                settings['project_settings'][project_path] = project_config

                with open(self.settings_file, 'w') as f:
                    json.dump(settings, f, indent=4)

            return True

        except Exception as e:
            logger.error(f"Error clearing project CJK threshold for {project_path}: {e}")
            return False

    def has_project_llm_cjk_reject_threshold(self, project_path: str) -> bool:
        """Check if a project has a CJK rejection threshold override."""
        return self.get_project_setting(project_path, 'llm_cjk_reject_threshold_percentage') is not None
    
    @staticmethod
    def get_default_llm_prompt_template() -> str:
        """Get the hardcoded default LLM prompt template.
        
        Returns:
            str: The default prompt template
        """
        return """Translate the following text from {source_locale} to {target_locale}.
Return the response as a JSON object with a single key "translation" containing the translated text.

Source text: {source_text}

{context}

Rules:
1. Maintain any placeholders like {{0}}, {{1}}, %s, %d, etc.
2. Preserve any special characters or formatting
3. Keep the same tone and style as the original
4. If the text contains technical terms, translate them appropriately for the target language

Return only the JSON object, no additional text."""
    
    @staticmethod
    def get_llm_prompt_variables() -> list[dict[str, str]]:
        """Get the list of available variables for LLM prompt templates.
        
        Returns:
            list[dict]: List of variable definitions with 'name' and 'description'
        """
        return [
            {"name": "{source_locale}", "description": "Source language code (e.g., 'en')"},
            {"name": "{target_locale}", "description": "Target language code (e.g., 'es', 'fr')"},
            {"name": "{source_text}", "description": "The text to be translated"},
            {"name": "{context}", "description": "Optional context about the translation (key info when different from text)"},
        ] 