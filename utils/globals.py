from enum import Enum
import os

from utils.config import ConfigManager
from utils.translations import I18N

_ = I18N._

config_manager = ConfigManager()

class Globals:
    HOME = os.path.expanduser("~")
    DEFAULT_WORKFLOW = config_manager.get("default_workflow", "audit")
    SKIP_CONFIRMATIONS = config_manager.get("skip_confirmations", False)

class WorkflowType(Enum):
    AUDIT = "audit"
    OVERWRITE_PO_FILES = "overwrite_po_files"
    OVERWRITE_MO_FILES = "overwrite_mo_files"

class Language(Enum):
    PYTHON = "Python"

class TranslationStatus(Enum):
    """Enum for different translation status types."""
    MISSING = "Missing"
    INVALID_UNICODE = "Invalid Unicode"
    INVALID_INDICES = "Invalid Indices"
    INVALID_BRACES = "Invalid Braces"
    INVALID_LEADING_SPACE = "Invalid Leading Space"
    INVALID_NEWLINE = "Invalid Newline"

    def get_translated_value(self) -> str:
        """Get the translated value for this status.
        
        Returns:
            str: The translated value
        """
        if self == TranslationStatus.MISSING:
            return _("Missing")
        elif self == TranslationStatus.INVALID_UNICODE:
            return _("Invalid Unicode")
        elif self == TranslationStatus.INVALID_INDICES:
            return _("Invalid Indices")
        elif self == TranslationStatus.INVALID_BRACES:
            return _("Invalid Braces")
        elif self == TranslationStatus.INVALID_LEADING_SPACE:
            return _("Invalid Leading Space")
        elif self == TranslationStatus.INVALID_NEWLINE:
            return _("Invalid Newline")
        return self.value

    @classmethod
    def from_translated_value(cls, translated_value: str) -> 'TranslationStatus':
        """Get the enum value from a translated string.
        
        Args:
            translated_value: The translated string to match
            
        Returns:
            TranslationStatus: The matching enum value
        """
        if translated_value == _("Missing"):
            return cls.MISSING
        elif translated_value == _("Invalid Unicode"):
            return cls.INVALID_UNICODE
        elif translated_value == _("Invalid Indices"):
            return cls.INVALID_INDICES
        elif translated_value == _("Invalid Braces"):
            return cls.INVALID_BRACES
        elif translated_value == _("Invalid Leading Space"):
            return cls.INVALID_LEADING_SPACE
        elif translated_value == _("Invalid Newline"):
            return cls.INVALID_NEWLINE
        raise ValueError(f"Unknown translation status: {translated_value}")

class TranslationFilter(Enum):
    """Enum for translation filter options."""
    ALL = "All"
    MISSING = "Missing"
    INVALID_UNICODE = "Invalid Unicode"
    INVALID_INDICES = "Invalid Indices"
    INVALID_BRACES = "Invalid Braces"
    INVALID_LEADING_SPACE = "Invalid Leading Space"
    INVALID_NEWLINE = "Invalid Newline"

    def get_translated_value(self) -> str:
        """Get the translated value for this filter.
        
        Returns:
            str: The translated value
        """
        if self == TranslationFilter.ALL:
            return _("All")
        elif self == TranslationFilter.MISSING:
            return _("Missing")
        elif self == TranslationFilter.INVALID_UNICODE:
            return _("Invalid Unicode")
        elif self == TranslationFilter.INVALID_INDICES:
            return _("Invalid Indices")
        elif self == TranslationFilter.INVALID_BRACES:
            return _("Invalid Braces")
        elif self == TranslationFilter.INVALID_LEADING_SPACE:
            return _("Invalid Leading Space")
        elif self == TranslationFilter.INVALID_NEWLINE:
            return _("Invalid Newline")
        return self.value

    @classmethod
    def from_translated_value(cls, translated_value: str) -> 'TranslationFilter':
        """Get the enum value from a translated string.
        
        Args:
            translated_value: The translated string to match
            
        Returns:
            TranslationFilter: The matching enum value
        """
        if translated_value == _("All"):
            return cls.ALL
        elif translated_value == _("Missing"):
            return cls.MISSING
        elif translated_value == _("Invalid Unicode"):
            return cls.INVALID_UNICODE
        elif translated_value == _("Invalid Indices"):
            return cls.INVALID_INDICES
        elif translated_value == _("Invalid Braces"):
            return cls.INVALID_BRACES
        elif translated_value == _("Invalid Leading Space"):
            return cls.INVALID_LEADING_SPACE
        elif translated_value == _("Invalid Newline"):
            return cls.INVALID_NEWLINE
        raise ValueError(f"Unknown translation filter: {translated_value}")

    def to_status(self) -> TranslationStatus:
        """Convert filter to status if applicable.
        
        Returns:
            TranslationStatus: The corresponding status, or None if ALL
        """
        if self == TranslationFilter.ALL:
            return None
        return TranslationStatus[self.name]
