"""Worker thread for handling translation tasks."""

from PyQt6.QtCore import QThread, pyqtSignal
from i18n.i18n_manager import I18NManager
import sys
import io
import logging

logger = logging.getLogger(__name__)

class PrintCapture:
    def __init__(self, callback):
        self.callback = callback
        self.buffer = io.StringIO()
        
    def write(self, text):
        if text.strip():  # Only emit non-empty lines
            self.callback(text)
            
    def flush(self):
        pass

class TranslationWorker(QThread):
    finished = pyqtSignal(int)
    output = pyqtSignal(str)
    stats_updated = pyqtSignal(int, int, int)  # total_translations, total_locales, missing_translations
    translations_ready = pyqtSignal(dict, list)  # translations, locales
    
    def __init__(self, directory, mode=None, modified_locales=None, intro_details=None, manager=None):
        super().__init__()
        self.directory = directory
        self.mode = mode
        self.modified_locales = modified_locales or set()
        self.intro_details = intro_details
        self.manager = manager
        logger.debug(f"Initialized TranslationWorker with directory: {directory}, mode: {mode}, modified_locales: {modified_locales}")
        
    def run(self):
        try:
            logger.debug("Starting translation worker run")
            # Capture print output
            print_capture = PrintCapture(self.output.emit)
            old_stdout = sys.stdout
            sys.stdout = print_capture
            
            # Use existing manager if provided, otherwise create new one
            if not self.manager:
                self.manager = I18NManager(self.directory, intro_details=self.intro_details)
                logger.debug("Created new I18NManager instance")
            else:
                logger.debug("Using existing I18NManager instance")
            
            if self.mode == 0:  # Update PO files
                if self.modified_locales:
                    logger.debug(f"Updating specific locales: {self.modified_locales}")
                    # Only update specific locales
                    result = self.manager.update_po_files(self.modified_locales)
                else:
                    logger.debug("Updating all PO files")
                    # Update all PO files
                    result = self.manager.manage_translations(create_new_po_files=True)
            elif self.mode == 1:  # Create MO files
                logger.debug("Creating MO files")
                result = self.manager.manage_translations(create_mo_files=True)
            else:  # Check status
                logger.debug("Checking translation status")
                result = self.manager.manage_translations()
                
            # Calculate statistics
            total_translations = len(self.manager.translations)
            total_locales = len(self.manager.locales)
            missing_translations = sum(1 for group in self.manager.translations.values() 
                                     if len(group.get_missing_locales(self.manager.locales)) > 0)
            
            logger.debug(f"Calculated stats - total_translations: {total_translations}, "
                        f"total_locales: {total_locales}, missing_translations: {missing_translations}")
            
            # Emit statistics and translations data
            self.stats_updated.emit(total_translations, total_locales, missing_translations)
            self.translations_ready.emit(self.manager.translations, self.manager.locales)
                
            # Restore stdout
            sys.stdout = old_stdout
            logger.debug(f"Translation worker finished with result: {result}")
            self.finished.emit(result)
        except Exception as e:
            # Restore stdout even if there's an error
            sys.stdout = old_stdout
            logger.error(f"Error in translation worker: {e}", exc_info=True)
            self.output.emit(f"Error: {str(e)}")
            self.finished.emit(1)