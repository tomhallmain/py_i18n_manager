import json
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class SettingsManager:
    MAX_RECENT_PROJECTS = 10
    
    def __init__(self):
        self.settings_file = Path.home() / '.i18n_manager' / 'settings.json'
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        
    def load_last_project(self):
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
            
    def load_recent_projects(self):
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
                
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass  # Silently fail if we can't save settings 

    def get_intro_details(self):
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