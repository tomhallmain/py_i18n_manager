from dataclasses import dataclass, field
from datetime import datetime
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
    
    def _get_project_last_modified_time(self, project_path: str) -> Optional[datetime]:
        """Get the last modification time of relevant files in the project.
        
        This checks Python files, POT files, and PO files for the most recent
        modification time. This is a relatively fast operation.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[datetime]: Last modification time or None if error
        """
        try:
            max_mtime = 0.0
            
            # Check Python files recursively
            for root, dirs, files in os.walk(project_path):
                # Skip common directories that don't contain source code
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'build', 'dist'}]
                
                for file in files:
                    if file.endswith(('.py', '.pot', '.po')):
                        file_path = os.path.join(root, file)
                        try:
                            mtime = os.path.getmtime(file_path)
                            max_mtime = max(max_mtime, mtime)
                        except (OSError, IOError):
                            continue
            
            if max_mtime > 0:
                return datetime.fromtimestamp(max_mtime)
            return None
            
        except Exception as e:
            logger.warning(f"Error getting last modified time for {project_path}: {e}")
            return None
    
    def _get_cached_analysis_time(self, project_path: str) -> Optional[datetime]:
        """Get the timestamp of the last analysis for this project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[datetime]: Last analysis timestamp or None if not cached
        """
        cached_time_str = self.settings_manager.get_project_setting(project_path, 'last_bulk_analysis_time')
        if cached_time_str:
            try:
                return datetime.fromisoformat(cached_time_str)
            except (ValueError, TypeError):
                logger.warning(f"Invalid cached analysis time for {project_path}: {cached_time_str}")
        return None
    
    def _save_analysis_time(self, project_path: str, analysis_time: datetime) -> bool:
        """Save the analysis timestamp for this project.
        
        Args:
            project_path (str): Path to the project
            analysis_time (datetime): Timestamp of the analysis
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.settings_manager.save_project_setting(
            project_path, 
            'last_bulk_analysis_time', 
            analysis_time.isoformat()
        )
    
    def _should_skip_analysis(self, project_path: str) -> bool:
        """Check if we should skip analysis for this project based on cache.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            bool: True if analysis should be skipped, False otherwise
        """
        # Get cached analysis time
        cached_time = self._get_cached_analysis_time(project_path)
        if not cached_time:
            return False
        
        # Get current project modification time
        current_mtime = self._get_project_last_modified_time(project_path)
        if not current_mtime:
            return False
        
        # Skip if project hasn't been modified since last analysis
        should_skip = current_mtime <= cached_time
        if should_skip:
            logger.debug(f"Skipping analysis for {project_path} - no changes since {cached_time}")
        
        return should_skip
    
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
            
            # Save analysis time for caching
            analysis_time = datetime.now()
            self._save_analysis_time(project_path, analysis_time)
            
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
        skipped_count = 0
        
        for project_path in projects:
            # Check if we should skip this project based on cache
            if self._should_skip_analysis(project_path):
                skipped_count += 1
                logger.debug(f"Skipping cached analysis for {os.path.basename(project_path)}")
                continue
                
            result = self.analyze_project(project_path)
            results.append(result)
        
        # Sort results: projects with missing translations first, then by project name
        results.sort(key=lambda r: (not r.has_missing_translations, r.project_name.lower()))
        
        logger.info(f"Bulk analysis complete: {len(results)} projects analyzed, {skipped_count} projects skipped (cached)")
        return results
    
    def clear_cache(self):
        """Clear the cached project managers."""
        self._translation_managers.clear()
        logger.debug("Cleared project manager cache")
    
    def clear_project_cache(self, project_path: str) -> bool:
        """Clear the analysis cache for a specific project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Remove from translation managers cache
            if project_path in self._translation_managers:
                del self._translation_managers[project_path]
            
            # Remove cached analysis time
            return self.settings_manager.save_project_setting(project_path, 'last_bulk_analysis_time', None)
        except Exception as e:
            logger.error(f"Error clearing cache for project {project_path}: {e}")
            return False
    
    def force_analyze_project(self, project_path: str) -> ProjectAnalysisResult:
        """Force analysis of a project, ignoring cache.
        
        Args:
            project_path (str): Path to the project to analyze
            
        Returns:
            ProjectAnalysisResult: Analysis results for the project
        """
        # Clear cache for this project first
        self.clear_project_cache(project_path)
        
        # Run analysis
        return self.analyze_project(project_path) 