"""Worker thread for handling translation tasks."""

from PyQt6.QtCore import QThread, pyqtSignal
from i18n.i18n_manager import I18NManager
from i18n.translation_manager_results import TranslationAction, TranslationManagerResults
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
    finished = pyqtSignal(TranslationManagerResults)
    output = pyqtSignal(str)
    stats_updated = pyqtSignal(int, int, int)  # total_translations, total_locales, missing_translations
    translations_ready = pyqtSignal(dict, list)  # translations, locales
    
    def __init__(self, directory, action: TranslationAction = TranslationAction.CHECK_STATUS, 
                 modified_locales=None, intro_details=None, manager=None):
        super().__init__()
        self.directory = directory
        self.action = action
        self.modified_locales = modified_locales or set()
        self.intro_details = intro_details
        self.manager = manager
        logger.debug(f"Initialized TranslationWorker with directory: {directory}, action: {action.name}, modified_locales: {modified_locales}")
        
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
            
            # Apply any pending in-memory updates before running manage_translations
            if hasattr(self, 'pending_updates'):
                logger.debug("Applying pending in-memory updates before manage_translations")
                for locale, changes in self.pending_updates.items():
                    for msgid, new_value in changes:
                        if msgid in self.manager.translations:
                            logger.debug(f"Updating translation in memory for {msgid} in {locale}")
                            self.manager.translations[msgid].add_translation(locale, new_value)
            
            # Run the translation management task with the specified action
            result = self.manager.manage_translations(self.action, self.modified_locales)
                
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
            logger.debug(f"Translation worker finished with result.action_successful: {result.action_successful}")
            self.finished.emit(result)
            
        except Exception as e:
            # Restore stdout even if there's an error
            sys.stdout = old_stdout
            logger.error(f"Error in translation worker: {e}", exc_info=True)
            self.output.emit(f"Error: {str(e)}")
            
            # Create error result
            error_result = TranslationManagerResults.create(self.directory, self.action)
            error_result.action_successful = False
            error_result.error_message = str(e)
            self.finished.emit(error_result)