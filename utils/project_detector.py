import os
import glob
from typing import Optional

from utils.globals import ProjectType
from utils.logging_setup import get_logger

logger = get_logger("project_detector")

class ProjectDetector:
    """Detects the type of internationalization project based on file structure and configuration."""
    
    @staticmethod
    def detect_project_type(project_path: str) -> Optional[ProjectType]:
        """Detect the project type based on the project directory structure.
        
        Args:
            project_path (str): Path to the project directory
            
        Returns:
            Optional[ProjectType]: The detected project type, or None if unknown
        """
        if not os.path.exists(project_path):
            logger.warning(f"Project path does not exist: {project_path}")
            return None
            
        # Check for Python project indicators
        if ProjectDetector._is_python_project(project_path):
            logger.info(f"Detected Python project: {project_path}")
            return ProjectType.PYTHON
            
        # Check for Ruby project indicators
        if ProjectDetector._is_ruby_project(project_path):
            logger.info(f"Detected Ruby project: {project_path}")
            return ProjectType.RUBY
            
        logger.warning(f"Could not determine project type for: {project_path}")
        return None
    
    @staticmethod
    def _is_python_project(project_path: str) -> bool:
        """Check if the project is a Python project.
        
        Args:
            project_path (str): Path to the project directory
            
        Returns:
            bool: True if this appears to be a Python project
        """
        # Check for Python-specific files
        python_indicators = [
            "requirements.txt",
            "setup.py",
            "pyproject.toml",
            "Pipfile",
            "poetry.lock",
            "manage.py",  # Django
            "app.py",     # Flask
            "main.py",
            "__init__.py"
        ]
        
        # Check for Python files in the project
        python_files = glob.glob(os.path.join(project_path, "**/*.py"), recursive=True)
        if python_files:
            logger.debug(f"Found {len(python_files)} Python files in {project_path}")
            
        # Check for Python-specific configuration files
        for indicator in python_indicators:
            if os.path.exists(os.path.join(project_path, indicator)):
                logger.debug(f"Found Python indicator: {indicator}")
                return True
                
        # If we have Python files and no other clear indicators, assume Python
        if python_files:
            return True
            
        return False
    
    @staticmethod
    def _is_ruby_project(project_path: str) -> bool:
        """Check if the project is a Ruby project.
        
        Args:
            project_path (str): Path to the project directory
            
        Returns:
            bool: True if this appears to be a Ruby project
        """
        # Check for Ruby-specific files
        ruby_indicators = [
            "Gemfile",
            "Gemfile.lock",
            "Rakefile",
            "config.ru",      # Rack
            "config/application.rb",  # Rails
            "app/controllers/",       # Rails
            "app/models/",            # Rails
            "app/views/",             # Rails
            "db/migrate/",            # Rails
            "config/routes.rb",       # Rails
            "config/environments/",   # Rails
        ]
        
        # Check for Ruby files in the project
        ruby_files = glob.glob(os.path.join(project_path, "**/*.rb"), recursive=True)
        if ruby_files:
            logger.debug(f"Found {len(ruby_files)} Ruby files in {project_path}")
            
        # Check for Ruby-specific configuration files and directories
        for indicator in ruby_indicators:
            indicator_path = os.path.join(project_path, indicator)
            if os.path.exists(indicator_path):
                logger.debug(f"Found Ruby indicator: {indicator}")
                return True
                
        # Check for Rails-specific patterns
        if ProjectDetector._is_rails_project(project_path):
            return True
            
        # If we have Ruby files and no other clear indicators, assume Ruby
        if ruby_files:
            return True
            
        return False
    
    @staticmethod
    def _is_rails_project(project_path: str) -> bool:
        """Check if the project is a Ruby on Rails project.
        
        Args:
            project_path (str): Path to the project directory
            
        Returns:
            bool: True if this appears to be a Rails project
        """
        # Rails-specific indicators
        rails_indicators = [
            "config/application.rb",
            "config/routes.rb",
            "app/controllers/",
            "app/models/",
            "app/views/",
            "db/migrate/",
            "config/environments/",
            "config/initializers/",
            "config/locales/",  # Rails i18n directory
        ]
        
        # Check for multiple Rails indicators
        found_indicators = 0
        for indicator in rails_indicators:
            if os.path.exists(os.path.join(project_path, indicator)):
                found_indicators += 1
                logger.debug(f"Found Rails indicator: {indicator}")
                
        # If we find multiple Rails indicators, it's likely a Rails project
        if found_indicators >= 3:
            logger.debug(f"Detected Rails project with {found_indicators} indicators")
            return True
            
        return False
