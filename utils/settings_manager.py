import json
import os
from pathlib import Path
from typing import Optional, Any

from utils.logging_setup import get_logger

logger = get_logger("settings_manager")

class SettingsManager:
    MAX_RECENT_PROJECTS = 10
    
    def __init__(self):
        self.settings_file = Path.home() / '.i18n_manager' / 'settings.json'
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.default_config_path = Path(__file__).parent.parent / 'configs' / 'default_config.json'
        
    def load_config(self) -> dict:
        """Load configuration from default config file.
        
        Returns:
            dict: Configuration dictionary
        """
        try:
            if self.default_config_path.exists():
                with open(self.default_config_path, 'r') as f:
                    return json.load(f)
            else:
                logger.warning(f"Default config file not found at {self.default_config_path}")
                return {}
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
            
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
                if project_path and os.path.exists(project_path):
                    return project_path
                return None
        except Exception:
            return None
            
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
                valid_projects = [p for p in recent_projects if os.path.exists(p)]
                
                # Update settings if we removed any invalid paths
                if len(valid_projects) != len(recent_projects):
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
        except Exception:
            pass  # Silently fail if we can't save settings
            
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
            
        # Fall back to global default
        try:
            config = self.load_config()
            return config.get('translation', {}).get('default_locale', 'en')
        except Exception:
            return 'en'
            
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

    def get_project_type(self, project_path: str) -> Optional[str]:
        """Get the project type for a specific project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[str]: Project type if set, None otherwise
        """
        return self.get_project_setting(project_path, 'project_type')
        
    def save_project_type(self, project_path: str, project_type: str) -> bool:
        """Save the project type for a specific project.
        
        Args:
            project_path (str): Path to the project
            project_type (str): Project type to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.save_project_setting(project_path, 'project_type', project_type)

    def get_intro_details(self) -> dict[str, str]:
        """Get the intro details from the config.
        
        Returns:
            dict: Dictionary containing intro details with keys:
                - first_author
                - last_translator
                - application_name
                - version
        """
        try:
            config = self.load_config()
            intro_details = config.get("intro_details", {})
            return {
                "first_author": intro_details.get("default_first_author", "THOMAS HALL <tomhall.main@gmail.com>"),
                "last_translator": intro_details.get("default_last_translator", "Thomas Hall <tomhall.main@gmail.com>"),
                "application_name": intro_details.get("default_application_name", "APPLICATION"),
                "version": intro_details.get("default_version", "1.0")
            }
        except Exception as e:
            logger.error(f"Error getting intro details from config: {e}")
            # Return default values if there's an error
            return {
                "first_author": "THOMAS HALL <tomhall.main@gmail.com>",
                "last_translator": "Thomas Hall <tomhall.main@gmail.com>",
                "application_name": "APPLICATION",
                "version": "1.0"
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