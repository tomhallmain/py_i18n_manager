from dataclasses import dataclass, field
from enum import Enum
import os
import subprocess
from typing import Dict, List, Optional

from .i18n_manager import I18NManager
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager

logger = get_logger("bulk_pot_analyzer")

class GitStatus(Enum):
    """Enumeration of possible git repository statuses."""
    CLEAN = "clean"
    MODIFIED = "modified"
    UNTRACKED = "untracked"
    ERROR = "error"
    UNKNOWN = "unknown"

@dataclass
class ProjectAnalysisResult:
    """Results of analyzing a single project for POT generation and missing translations."""
    project_path: str
    project_name: str
    pot_file_path: str
    has_missing_translations: bool = False
    missing_translations_count: int = 0
    total_translations: int = 0
    locales_with_missing: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    pot_was_modified: bool = False
    git_status: GitStatus = GitStatus.UNKNOWN
    
    @property
    def has_outstanding_items(self) -> bool:
        """Check if this project has any outstanding items (missing translations)."""
        return self.has_missing_translations

class BulkPotAnalyzer:
    """Analyzes all loaded projects for POT generation and missing translations."""
    
    def __init__(self, settings_manager: SettingsManager):
        self.settings_manager = settings_manager
        self._translation_managers: Dict[str, I18NManager] = {}
        
    def get_available_projects(self) -> List[str]:
        """Get list of available projects from recent projects.
        
        Returns:
            List[str]: List of valid project paths
        """
        projects = self.settings_manager.load_recent_projects()
        logger.debug(f"Settings manager returned projects: {projects}")
        return projects
    
    def _get_or_create_manager(self, project_path: str) -> Optional[I18NManager]:
        """Get or create an I18NManager for a project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[I18NManager]: Manager instance or None if project is invalid
        """
        if project_path in self._translation_managers:
            logger.debug(f"Using cached manager for project: {project_path}")
            return self._translation_managers[project_path]
            
        logger.debug(f"Creating new manager for project: {project_path}")
        
        try:
            # Create manager and load translations
            manager = I18NManager(project_path, intro_details=self.settings_manager.get_intro_details(), settings_manager=self.settings_manager)
            
            # Run status check to load translations
            logger.debug(f"Running status check for project: {project_path}")
            results = manager.manage_translations()
            if not results.action_successful:
                logger.warning(f"Failed to load translations for project {project_path}: {results.error_message}")
                return None
                
            logger.debug(f"Successfully loaded project {project_path}: {len(manager.translations)} translations, {len(manager.locales)} locales")
            self._translation_managers[project_path] = manager
            return manager
            
        except Exception as e:
            logger.error(f"Error creating manager for project {project_path}: {e}")
            return None
    
    def _get_git_status(self, project_path: str) -> GitStatus:
        """Get the git status of a project directory.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            GitStatus: Git status enum value
        """
        try:
            # Check if this is a git repository
            git_dir = os.path.join(project_path, ".git")
            if not os.path.exists(git_dir):
                return GitStatus.UNTRACKED
            
            # Run git status to check for changes
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.warning(f"Git status failed for {project_path}: {result.stderr}")
                return GitStatus.ERROR
            
            # Check if there are any changes
            if result.stdout.strip():
                return GitStatus.MODIFIED
            else:
                return GitStatus.CLEAN
                
        except subprocess.TimeoutExpired:
            logger.warning(f"Git status timeout for {project_path}")
            return GitStatus.ERROR
        except Exception as e:
            logger.warning(f"Error checking git status for {project_path}: {e}")
            return GitStatus.ERROR
    
    def analyze_project(self, project_path: str) -> ProjectAnalysisResult:
        """Analyze a single project for POT generation and missing translations.
        
        Args:
            project_path (str): Path to the project to analyze
            
        Returns:
            ProjectAnalysisResult: Analysis results for the project
        """
        project_name = os.path.basename(project_path)
        logger.info(f"Analyzing project: {project_name} ({project_path})")
        
        result = ProjectAnalysisResult(
            project_path=project_path,
            project_name=project_name,
            pot_file_path=""
        )
        
        try:
            # Get git status first
            result.git_status = self._get_git_status(project_path)
            
            # Create manager for the project
            manager = self._get_or_create_manager(project_path)
            if not manager:
                result.error_message = "Failed to create project manager"
                return result
            
            # Get POT file path using the manager's locale directory
            result.pot_file_path = manager.get_pot_file_path()
            
            # Check if translations actually changed
            result.pot_was_modified = manager.check_translations_changed()
            
            # Reload translations after POT generation
            manager.translations.clear()
            results = manager.manage_translations()
            if not results.action_successful:
                result.error_message = f"Failed to reload translations: {results.error_message}"
                return result
            
            # Analyze missing translations
            result.total_translations = len(manager.translations)
            result.missing_translations_count = 0
            result.locales_with_missing = []
            
            for locale in manager.locales:
                locale_missing_count = 0
                for msgid, group in manager.translations.items():
                    if group.is_in_base:  # Only check base translations
                        translation = group.get_translation(locale)
                        if not translation or not translation.strip():
                            locale_missing_count += 1
                
                if locale_missing_count > 0:
                    result.locales_with_missing.append(locale)
                    result.missing_translations_count += locale_missing_count
            
            result.has_missing_translations = result.missing_translations_count > 0
            
            logger.info(f"Analysis complete for {project_name}: {result.missing_translations_count} missing translations across {len(result.locales_with_missing)} locales")
            
        except Exception as e:
            logger.error(f"Error analyzing project {project_name}: {e}")
            result.error_message = str(e)
        
        return result
    
    def analyze_all_projects(self) -> List[ProjectAnalysisResult]:
        """Analyze all available projects for POT generation and missing translations.
        
        Returns:
            List[ProjectAnalysisResult]: List of analysis results for each project
        """
        logger.info("Starting bulk analysis of all projects")
        
        projects = self.get_available_projects()
        if not projects:
            logger.warning("No projects available for analysis")
            return []
        
        results = []
        for project_path in projects:
            result = self.analyze_project(project_path)
            results.append(result)
        
        # Sort results: projects with missing translations first, then by project name
        results.sort(key=lambda r: (not r.has_missing_translations, r.project_name.lower()))
        
        logger.info(f"Bulk analysis complete: {len(results)} projects analyzed")
        return results
    
    def clear_cache(self):
        """Clear the cached project managers."""
        self._translation_managers.clear()
        logger.debug("Cleared project manager cache") 