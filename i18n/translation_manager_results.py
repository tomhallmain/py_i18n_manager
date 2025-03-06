from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Dict, List, Optional
import os

class TranslationAction(Enum):
    CHECK_STATUS = auto()
    WRITE_PO_FILES = auto()
    WRITE_MO_FILES = auto()
    GENERATE_POT = auto()

@dataclass
class LocaleStatus:
    """Status of a specific locale directory and its files."""
    locale_code: str
    has_directory: bool
    has_po_file: bool
    has_mo_file: bool
    po_file_path: Optional[str] = None
    mo_file_path: Optional[str] = None
    last_modified: Optional[datetime] = None
    
    @classmethod
    def from_directory(cls, locale_dir: str, locale_code: str) -> 'LocaleStatus':
        """Create a LocaleStatus instance by scanning a locale directory."""
        has_dir = os.path.isdir(locale_dir)
        po_path = os.path.join(locale_dir, 'LC_MESSAGES', 'base.po')
        mo_path = os.path.join(locale_dir, 'LC_MESSAGES', 'base.mo')
        
        has_po = os.path.exists(po_path)
        has_mo = os.path.exists(mo_path)
        
        last_mod = None
        if has_po:
            last_mod = datetime.fromtimestamp(os.path.getmtime(po_path))
        
        return cls(
            locale_code=locale_code,
            has_directory=has_dir,
            has_po_file=has_po,
            has_mo_file=has_mo,
            po_file_path=po_path if has_po else None,
            mo_file_path=mo_path if has_mo else None,
            last_modified=last_mod
        )

@dataclass
class TranslationManagerResults:
    """Results from a translation manager operation."""
    # Project structure
    project_dir: str
    action: TranslationAction
    action_timestamp: datetime
    action_successful: bool
    locale_statuses: Dict[str, LocaleStatus]
    failed_locales: List[str]
    default_locale: str
    has_locale_dir: bool
    has_pot_file: bool
    pot_file_path: Optional[str]
    pot_last_modified: Optional[datetime]
    
    # Optional fields with defaults
    error_message: Optional[str] = None
    total_strings: int = 0
    total_locales: int = 0
    missing_translations: int = 0
    stale_translations: int = 0
    invalid_unicode: int = 0
    invalid_indices: int = 0
    
    # PO/MO file update tracking
    po_files_updated: bool = False
    updated_locales: List[str] = field(default_factory=list)
    
    @classmethod
    def create(cls, project_dir: str, action: TranslationAction) -> 'TranslationManagerResults':
        """Create a new TranslationManagerResults instance by scanning a project directory."""
        locale_dir = os.path.join(project_dir, 'locale')
        pot_file = os.path.join(locale_dir, 'base.pot')
        
        has_locale = os.path.isdir(locale_dir)
        has_pot = os.path.exists(pot_file)
        pot_modified = datetime.fromtimestamp(os.path.getmtime(pot_file)) if has_pot else None
        
        # Scan for locales
        locale_statuses = {}
        if has_locale:
            for item in os.listdir(locale_dir):
                full_path = os.path.join(locale_dir, item)
                if os.path.isdir(full_path) and not item.startswith('__'):
                    status = LocaleStatus.from_directory(full_path, item)
                    locale_statuses[item] = status
        
        return cls(
            project_dir=project_dir,
            action=action,
            action_timestamp=datetime.now(),
            action_successful=True,  # Will be updated after action completes
            locale_statuses=locale_statuses,
            failed_locales=[],
            default_locale='en',  # Will be updated from settings
            has_locale_dir=has_locale,
            has_pot_file=has_pot,
            pot_file_path=pot_file if has_pot else None,
            pot_last_modified=pot_modified,
        )
    
    def needs_setup(self) -> bool:
        """Check if the project needs initial setup.
        
        A project needs setup if:
        1. There is no POT file, or
        2. There are no locale directories, or
        3. There are locale directories but some are missing PO files
        
        Returns:
            bool: True if the project needs setup, False otherwise
        """
        # No POT file means we need setup
        if not self.has_pot_file:
            return True
            
        # No locale directories means we need setup
        if not self.has_locale_dir or not self.locale_statuses:
            return True
            
        # Check if any locale directory is missing its PO file
        for status in self.locale_statuses.values():
            if not status.has_po_file:
                return True
                
        return False
    
    def get_missing_po_files(self) -> List[str]:
        """Get list of locales that are missing PO files."""
        return [
            locale for locale, status in self.locale_statuses.items()
            if not status.has_po_file
        ]
    
    def get_missing_mo_files(self) -> List[str]:
        """Get list of locales that are missing MO files."""
        return [
            locale for locale, status in self.locale_statuses.items()
            if not status.has_mo_file
        ]
    
    def get_outdated_po_files(self) -> List[str]:
        """Get list of locales whose PO files are older than the POT file."""
        if not self.pot_last_modified:
            return []
            
        return [
            locale for locale, status in self.locale_statuses.items()
            if status.last_modified and status.last_modified < self.pot_last_modified
        ]

    def extend_error_message(self, message: str):
        """Extend the error message with a new message."""
        if self.error_message:
            self.error_message += "\n" + message
        else:
            self.error_message = message

    def determine_action_successful(self):
        """Determine if the action was successful based on the results."""
        self.action_successful = self.action_successful and not self.error_message and not self.failed_locales
    
    def format_status_report(self) -> str:
        """Generate a human-readable status report."""
        lines = [
            f"Project Directory: {self.project_dir}",
            f"Action: {self.action.name} at {self.action_timestamp}",
            f"Status: {'Success' if self.action_successful else 'Failed'}"
        ]
        
        if self.error_message:
            lines.append(f"Error: {self.error_message}")
            
        lines.extend([
            "\nProject Structure:",
            f"- Locale Directory: {'✓' if self.has_locale_dir else '✗'}",
            f"- POT File: {'✓' if self.has_pot_file else '✗'}"
        ])
        
        if self.locale_statuses:
            lines.append("\nLocale Status:")
            for locale, status in self.locale_statuses.items():
                lines.append(f"- {locale}:")
                lines.append(f"  • Directory: {'✓' if status.has_directory else '✗'}")
                lines.append(f"  • PO File: {'✓' if status.has_po_file else '✗'}")
                lines.append(f"  • MO File: {'✓' if status.has_mo_file else '✗'}")
                if status.last_modified:
                    lines.append(f"  • Last Modified: {status.last_modified}")
                    
        if any([self.total_strings, self.total_locales, self.missing_translations,
                self.stale_translations, self.invalid_unicode, self.invalid_indices]):
            lines.extend([
                "\nTranslation Statistics:",
                f"- Total Strings: {self.total_strings}",
                f"- Total Locales: {self.total_locales}",
                f"- Missing Translations: {self.missing_translations}",
                f"- Stale Translations: {self.stale_translations}",
                f"- Invalid Unicode: {self.invalid_unicode}",
                f"- Invalid Indices: {self.invalid_indices}"
            ])
            
        return "\n".join(lines) 