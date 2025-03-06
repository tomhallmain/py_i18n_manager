import argostranslate.package
import argostranslate.translate
from pathlib import Path
from utils.config import ConfigManager
import logging
import os
from PyQt6.QtCore import QObject, pyqtSignal
from ui.download_dialog import DownloadDialog

logger = logging.getLogger(__name__)

class ArgosTranslate(QObject):
    """Handles translation using Argos Translate models."""
    
    # Signal for download progress updates
    download_progress = pyqtSignal(str)
    
    def __init__(self):
        """Initialize Argos Translate with configuration from settings."""
        super().__init__()
        
        # Get configuration
        self.config = ConfigManager()
        
        # Initialize state
        self.is_usable = False
        
        # Configure model storage path from settings
        try:
            models_dir = self.config.get('translation.models_dir', 'models/argos')
            self.models_dir = Path(models_dir)
            
            # Try to create the directory
            try:
                self.models_dir.mkdir(parents=True, exist_ok=True)
                if not self.models_dir.is_dir():
                    raise RuntimeError(f"Failed to create models directory: {self.models_dir}")
            except Exception as e:
                logger.error(f"Failed to create models directory {self.models_dir}: {e}")
                self.is_usable = False
                return
                
            # Initialize Argos Translate
            self._init_argos()
            
        except Exception as e:
            logger.error(f"Failed to initialize Argos Translate configuration: {e}")
            self.is_usable = False
            return
            
    def _init_argos(self):
        """Initialize Argos Translate with the configured models directory."""
        try:
            # Set the environment variable for package directory
            os.environ['ARGOS_PACKAGES_DIR'] = str(self.models_dir)
            
            # Get installed packages
            installed_packages = argostranslate.package.get_installed_packages()
            logger.info(f"Found {len(installed_packages)} installed Argos Translate packages")
            
            # Log available language pairs
            for package in installed_packages:
                logger.info(f"Package: {package.from_code} -> {package.to_code}")
                
            self.is_usable = True
                
        except Exception as e:
            logger.error(f"Failed to initialize Argos Translate: {e}")
            self.is_usable = False
            
    def install_language_package(self, from_code, to_code, parent=None):
        """Install a language package for Argos Translate.
        
        Args:
            from_code (str): Source language code (e.g., 'en')
            to_code (str): Target language code (e.g., 'es')
            parent: Parent widget for the download dialog
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if package is already installed
            installed_packages = argostranslate.package.get_installed_packages()
            for package in installed_packages:
                if package.from_code == from_code and package.to_code == to_code:
                    logger.info(f"Package {from_code}->{to_code} already installed")
                    return True
                    
            # Create and show download dialog
            dialog = DownloadDialog(parent)
            
            # Download and install package
            dialog.update_status("Updating package index...")
            argostranslate.package.update_package_index()
            
            dialog.update_status("Finding available packages...")
            available_packages = argostranslate.package.get_available_packages()
            
            # Find the package we want to install
            package_to_install = next(
                filter(
                    lambda x: x.from_code == from_code and x.to_code == to_code,
                    available_packages
                ),
                None
            )
            
            if not package_to_install:
                dialog.close()
                logger.error(f"No package found for {from_code}->{to_code}")
                return False
                
            # Download and install the package
            dialog.update_status("Downloading package...")
            package_path = package_to_install.download()
            
            dialog.update_status("Installing package...")
            argostranslate.package.install_from_path(package_path)
            
            dialog.close()
            logger.info(f"Successfully installed package for {from_code}->{to_code}")
            return True
            
        except Exception as e:
            if 'dialog' in locals():
                dialog.close()
            logger.error(f"Failed to install language package {from_code}->{to_code}: {e}")
            return False
            
    def is_language_pair_available(self, from_code, to_code):
        """Check if a language pair is available for translation.
        
        Args:
            from_code (str): Source language code (e.g., 'en')
            to_code (str): Target language code (e.g., 'es')
            
        Returns:
            bool: True if the language pair is available, False otherwise
        """
        try:
            from_lang = argostranslate.translate.get_language_from_code(from_code)
            to_lang = argostranslate.translate.get_language_from_code(to_code)
            
            if not from_lang or not to_lang:
                logger.warning(f"Language code not recognized: {from_code}->{to_code}")
                return False
                
            translation = from_lang.get_translation(to_lang)
            if not translation:
                logger.warning(f"Translation package not installed for {from_code}->{to_code}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error checking language pair availability: {e}")
            return False
            
    def translate(self, text, target_locale, source_locale=None, parent=None):
        """Translate text to the target locale using Argos Translate.
        
        Args:
            text (str): The text to translate
            target_locale (str): The target locale code (e.g., 'es', 'fr')
            source_locale (str, optional): Source locale code. Defaults to config value.
            parent: Parent widget for the download dialog
            
        Returns:
            str: The translated text
        """
        if not self.is_usable:
            logger.error("Argos Translate service is not usable")
            return ""
            
        if source_locale is None:
            source_locale = self.config.get('translation.default_locale', 'en')
            
        try:
            # Check if language pair is available
            if not self.is_language_pair_available(source_locale, target_locale):
                logger.info(f"Attempting to download translation package for {source_locale}->{target_locale}")
                if not self.install_language_package(source_locale, target_locale, parent):
                    logger.error(f"Failed to install translation package for {source_locale}->{target_locale}")
                    return ""
                # Recheck availability after installation
                if not self.is_language_pair_available(source_locale, target_locale):
                    logger.error(f"Translation package installation failed for {source_locale}->{target_locale}")
                    return ""
                
            # Get the translation
            from_lang = argostranslate.translate.get_language_from_code(source_locale)
            to_lang = argostranslate.translate.get_language_from_code(target_locale)
            translation = from_lang.get_translation(to_lang)
                
            translated_text = translation.translate(text)
            logger.debug(f"Successfully translated using Argos Translate")
            return translated_text
            
        except Exception as e:
            logger.error(f"Argos Translate translation failed: {e}")
            return ""
            
    def get_installed_packages(self):
        """Get list of installed language packages.
        
        Returns:
            list: List of tuples (from_code, to_code) for installed packages
        """
        try:
            packages = argostranslate.package.get_installed_packages()
            return [(p.from_code, p.to_code) for p in packages]
        except Exception as e:
            logger.error(f"Failed to get installed packages: {e}")
            return [] 