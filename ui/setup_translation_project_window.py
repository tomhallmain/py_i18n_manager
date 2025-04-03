from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QLineEdit, QFormLayout, QListWidget, QListWidgetItem,
                            QMessageBox, QFrame, QComboBox)
from PyQt6.QtCore import Qt, pyqtSignal
import os
from utils.translations import I18N
from utils.settings_manager import SettingsManager

_ = I18N._

class SetupTranslationProjectWindow(QDialog):
    project_configured = pyqtSignal()  # Emitted when project setup is complete
    
    def __init__(self, project_dir, parent=None):
        super().__init__(parent)
        self.project_dir = project_dir
        self.settings_manager = SettingsManager()
        self.intro_details = self.settings_manager.get_intro_details()
        self.setWindowTitle(_("Setup Translation Project"))
        self.setMinimumSize(600, 500)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Project Info Section
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        info_layout = QFormLayout(info_frame)
        
        # Project details
        self.app_name = QLineEdit(self.intro_details.get("application_name", ""))
        self.app_name.setPlaceholderText(_("Application name"))
        info_layout.addRow(_("Application Name:"), self.app_name)
        
        self.version = QLineEdit(self.intro_details.get("version", "1.0"))
        self.version.setPlaceholderText("1.0")
        info_layout.addRow(_("Version:"), self.version)
        
        self.author = QLineEdit(self.intro_details.get("first_author", ""))
        self.author.setPlaceholderText(_("Author Name <author@example.com>"))
        info_layout.addRow(_("Author:"), self.author)
        
        self.translator = QLineEdit(self.intro_details.get("last_translator", ""))
        self.translator.setPlaceholderText(_("Translator Name <translator@example.com>"))
        info_layout.addRow(_("Default Translator:"), self.translator)
        
        # Default locale selection
        self.default_locale = QComboBox()
        self.default_locale.addItems(["en", "fr", "de", "es", "it", "ja", "ko", "zh"])
        current_default = self.intro_details.get("translation.default_locale", "en")
        self.default_locale.setCurrentText(current_default)
        info_layout.addRow(_("Default Locale:"), self.default_locale)
        
        layout.addWidget(info_frame)
        
        # Locales Section
        locales_frame = QFrame()
        locales_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        locales_layout = QVBoxLayout(locales_frame)
        
        # Title for locales section
        locales_title = QLabel(_("Project Locales"))
        locales_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        locales_layout.addWidget(locales_title)
        
        # Locale management
        locale_controls = QHBoxLayout()
        
        self.locale_input = QLineEdit()
        self.locale_input.setPlaceholderText(_("Enter locale code (e.g., fr, de, es)"))
        locale_controls.addWidget(self.locale_input)
        
        add_locale_btn = QPushButton(_("Add Locale"))
        add_locale_btn.clicked.connect(self.add_locale)
        locale_controls.addWidget(add_locale_btn)
        
        locales_layout.addLayout(locale_controls)
        
        # List of locales
        self.locales_list = QListWidget()
        self.locales_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.load_existing_locales()
        locales_layout.addWidget(self.locales_list)
        
        # Remove locale button
        remove_locale_btn = QPushButton(_("Remove Selected Locale"))
        remove_locale_btn.clicked.connect(self.remove_locale)
        locales_layout.addWidget(remove_locale_btn)
        
        layout.addWidget(locales_frame)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton(_("Save Configuration"))
        save_btn.clicked.connect(self.save_configuration)
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
    def load_existing_locales(self):
        """Load existing locales from the project directory."""
        locale_dir = os.path.join(self.project_dir, 'locale')
        if os.path.exists(locale_dir):
            for item in os.listdir(locale_dir):
                full_path = os.path.join(locale_dir, item)
                if os.path.isdir(full_path) and not item.startswith('__'):
                    self.locales_list.addItem(item)
                    
    def add_locale(self):
        """Add a new locale to the project."""
        locale_code = self.locale_input.text().strip().lower()
        if not locale_code:
            QMessageBox.warning(self, _("Error"), _("Please enter a locale code."))
            return
            
        # Basic validation of locale code
        if not locale_code.isalnum() or len(locale_code) not in [2, 5]:
            QMessageBox.warning(self, _("Error"), 
                              _("Invalid locale code. Use format 'xx' or 'xx_YY' (e.g., 'fr' or 'fr_FR')."))
            return
            
        # Check if locale already exists
        existing_items = self.locales_list.findItems(locale_code, Qt.MatchFlag.MatchExactly)
        if existing_items:
            QMessageBox.warning(self, _("Error"), _("This locale already exists."))
            return
            
        # Add to list
        self.locales_list.addItem(locale_code)
        self.locale_input.clear()
        
    def remove_locale(self):
        """Remove the selected locale."""
        current_item = self.locales_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, _("Error"), _("Please select a locale to remove."))
            return
            
        locale_code = current_item.text()
        if locale_code == self.default_locale.currentText():
            QMessageBox.warning(self, _("Error"), _("Cannot remove the default locale."))
            return
            
        reply = QMessageBox.question(self, _("Confirm Removal"),
                                   _("Are you sure you want to remove locale '{}'? This will delete the locale directory and all its translations.").format(locale_code),
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                                   
        if reply == QMessageBox.StandardButton.Yes:
            self.locales_list.takeItem(self.locales_list.row(current_item))
            
    def save_configuration(self):
        """Save the project configuration and create necessary directories."""
        try:
            # Check if default locale is in the list
            default_locale = self.default_locale.currentText()
            locales = [self.locales_list.item(i).text().strip() for i in range(self.locales_list.count())]
            
            if default_locale not in locales:
                reply = QMessageBox.warning(
                    self,
                    _("Warning"),
                    _("The default locale '{}' is not in the list of locales. Do you want to add it?").format(default_locale),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.locales_list.addItem(default_locale)
                else:
                    return  # Don't save if user doesn't want to add default locale
            
            # Validate locale codes
            invalid_locales = []
            for locale in locales:
                validation_result = self.is_valid_locale_code(locale)
                if validation_result is not None:
                    invalid_locales.append((locale, validation_result))
            
            if invalid_locales:
                error_message = _("The following locale codes are invalid:") + "\n\n"
                for locale, reason in invalid_locales:
                    error_message += f"• {locale}: {reason}\n"
                error_message += "\n\n" + _("Locale codes must follow ISO 639-1 (language) and optionally ISO 3166-1 (country) standards.")
                
                QMessageBox.warning(
                    self,
                    _("Invalid Locale Codes"),
                    error_message,
                    QMessageBox.StandardButton.Ok
                )
                return  # Don't save if there are invalid locales
            
            # Update intro details
            self.intro_details.update({
                "application_name": self.app_name.text(),
                "version": self.version.text(),
                "first_author": self.author.text(),
                "last_translator": self.translator.text(),
                "translation.default_locale": self.default_locale.currentText()
            })
            
            # Save to settings
            self.settings_manager.save_intro_details(self.intro_details)
            
            # Create locale directories
            locale_dir = os.path.join(self.project_dir, 'locale')
            os.makedirs(locale_dir, exist_ok=True)
            
            for i in range(self.locales_list.count()):
                locale_code = self.locales_list.item(i).text().strip()
                locale_path = os.path.join(locale_dir, locale_code, 'LC_MESSAGES')
                os.makedirs(locale_path, exist_ok=True)
                
                # Create empty PO file if it doesn't exist
                po_file = os.path.join(locale_path, 'base.po')
                if not os.path.exists(po_file):
                    with open(po_file, 'w', encoding='utf-8') as f:
                        f.write(self.get_po_header(locale_code))
            
            self.project_configured.emit()
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, _("Error"), 
                               _("Failed to save configuration: {}").format(str(e)))
            
    def get_po_header(self, locale):
        """Generate a PO file header for the given locale."""
        return f'''msgid ""
msgstr ""
"Project-Id-Version: {self.app_name.text()} {self.version.text()}\\n"
"Language: {locale}\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"First-Author: {self.author.text()}\\n"
"Last-Translator: {self.translator.text()}\\n"
'''
    
    def is_valid_locale_code(self, locale_code):
        """Validate a locale code against ISO standards.
        
        Valid formats:
        - Two-letter language code (ISO 639-1) (e.g., 'en', 'fr')
        - Language code with country code (ISO 639-1 + ISO 3166-1) (e.g., 'en_US', 'fr_FR')
        - Language code with script and country (e.g., 'zh_Hans_CN')
        
        Returns:
            True if valid, or a string error message if invalid
        """
        # Common ISO 639-1 language codes
        valid_language_codes = {
            'aa', 'ab', 'af', 'ak', 'sq', 'am', 'ar', 'an', 'hy', 'as', 'av', 'ae', 'ay', 'az', 
            'bm', 'ba', 'eu', 'be', 'bn', 'bh', 'bi', 'bs', 'br', 'bg', 'my', 'ca', 'ch', 'ce', 
            'ny', 'zh', 'cv', 'kw', 'co', 'cr', 'hr', 'cs', 'da', 'dv', 'nl', 'dz', 'eo', 'et', 
            'ee', 'fo', 'fj', 'fi', 'fr', 'ff', 'gl', 'ka', 'de', 'el', 'gn', 'gu', 'ht', 'ha', 
            'he', 'hz', 'hi', 'ho', 'hu', 'ia', 'id', 'ie', 'ga', 'ig', 'ik', 'io', 'is', 'it', 
            'iu', 'ja', 'jv', 'kl', 'kn', 'kr', 'ks', 'kk', 'km', 'ki', 'rw', 'ky', 'kv', 'kg', 
            'ko', 'ku', 'kj', 'lo', 'la', 'lv', 'li', 'ln', 'lt', 'lu', 'lb', 'lg', 'mk', 'mg', 
            'ms', 'ml', 'mt', 'mi', 'mr', 'mh', 'mn', 'na', 'nv', 'nd', 'ne', 'ng', 'nb', 'nn', 
            'no', 'ii', 'nr', 'oc', 'oj', 'or', 'om', 'os', 'pi', 'ps', 'fa', 'pl', 'pt', 'pa', 
            'qu', 'rm', 'rn', 'ro', 'ru', 'sa', 'sc', 'sd', 'se', 'sm', 'sg', 'sr', 'gd', 'sn', 
            'si', 'sk', 'sl', 'so', 'st', 'es', 'su', 'sw', 'ss', 'sv', 'ta', 'te', 'tg', 'th', 
            'ti', 'bo', 'tk', 'tl', 'tn', 'to', 'tr', 'ts', 'tt', 'tw', 'ty', 'ug', 'uk', 'ur', 
            'uz', 've', 'vi', 'vo', 'wa', 'cy', 'wo', 'fy', 'xh', 'yi', 'yo', 'za', 'zu'
        }
        
        # Common ISO 3166-1 country codes
        valid_country_codes = {
            'AF', 'AX', 'AL', 'DZ', 'AS', 'AD', 'AO', 'AI', 'AQ', 'AG', 'AR', 'AM', 'AW', 'AU', 
            'AT', 'AZ', 'BS', 'BH', 'BD', 'BB', 'BY', 'BE', 'BZ', 'BJ', 'BM', 'BT', 'BO', 'BQ', 
            'BA', 'BW', 'BV', 'BR', 'IO', 'BN', 'BG', 'BF', 'BI', 'KH', 'CM', 'CA', 'CV', 'KY', 
            'CF', 'TD', 'CL', 'CN', 'CX', 'CC', 'CO', 'KM', 'CG', 'CD', 'CK', 'CR', 'CI', 'HR', 
            'CU', 'CW', 'CY', 'CZ', 'DK', 'DJ', 'DM', 'DO', 'EC', 'EG', 'SV', 'GQ', 'ER', 'EE', 
            'ET', 'FK', 'FO', 'FJ', 'FI', 'FR', 'GF', 'PF', 'TF', 'GA', 'GM', 'GE', 'DE', 'GH', 
            'GI', 'GR', 'GL', 'GD', 'GP', 'GU', 'GT', 'GG', 'GN', 'GW', 'GY', 'HT', 'HM', 'VA', 
            'HN', 'HK', 'HU', 'IS', 'IN', 'ID', 'IR', 'IQ', 'IE', 'IM', 'IL', 'IT', 'JM', 'JP', 
            'JE', 'JO', 'KZ', 'KE', 'KI', 'KP', 'KR', 'KW', 'KG', 'LA', 'LV', 'LB', 'LS', 'LR', 
            'LY', 'LI', 'LT', 'LU', 'MO', 'MK', 'MG', 'MW', 'MY', 'MV', 'ML', 'MT', 'MH', 'MQ', 
            'MR', 'MU', 'YT', 'MX', 'FM', 'MD', 'MC', 'MN', 'ME', 'MS', 'MA', 'MZ', 'MM', 'NA', 
            'NR', 'NP', 'NL', 'NC', 'NZ', 'NI', 'NE', 'NG', 'NU', 'NF', 'MP', 'NO', 'OM', 'PK', 
            'PW', 'PS', 'PA', 'PG', 'PY', 'PE', 'PH', 'PN', 'PL', 'PT', 'PR', 'QA', 'RE', 'RO', 
            'RU', 'RW', 'BL', 'SH', 'KN', 'LC', 'MF', 'PM', 'VC', 'WS', 'SM', 'ST', 'SA', 'SN', 
            'RS', 'SC', 'SL', 'SG', 'SX', 'SK', 'SI', 'SB', 'SO', 'ZA', 'GS', 'SS', 'ES', 'LK', 
            'SD', 'SR', 'SJ', 'SZ', 'SE', 'CH', 'SY', 'TW', 'TJ', 'TZ', 'TH', 'TL', 'TG', 'TK', 
            'TO', 'TT', 'TN', 'TR', 'TM', 'TC', 'TV', 'UG', 'UA', 'AE', 'GB', 'US', 'UM', 'UY', 
            'UZ', 'VU', 'VE', 'VN', 'VG', 'VI', 'WF', 'EH', 'YE', 'ZM', 'ZW'
        }
        
        # Common script codes
        valid_script_codes = {
            'Arab', 'Armn', 'Beng', 'Cans', 'Cher', 'Cyrl', 'Deva', 'Ethi', 'Geor', 'Grek', 'Gujr', 
            'Guru', 'Hang', 'Hani', 'Hans', 'Hant', 'Hebr', 'Hira', 'Jpan', 'Kana', 'Khmr', 'Knda', 
            'Kore', 'Laoo', 'Latn', 'Mlym', 'Mong', 'Mymr', 'Orya', 'Sinh', 'Taml', 'Telu', 'Thai', 
            'Tibt', 'Yiii', 'Zyyy', 'Zzzz'
        }
        
        # Basic format validation
        parts = locale_code.split('_')
        
        # Check if we have at least a language code
        if not parts or not parts[0].isalpha() or len(parts[0]) != 2:
            return _("Language code must be a two-letter ISO 639-1 code")
        
        # Check if language code is valid
        if parts[0].lower() not in valid_language_codes:
            return _("Invalid language code. Must be a valid ISO 639-1 code")
        
        # If we have more parts, validate them
        if len(parts) > 1:
            # Country code should be 2 uppercase letters
            if not parts[1].isalpha() or len(parts[1]) != 2 or not parts[1].isupper():
                return _("Country code must be a two-letter uppercase ISO 3166-1 code")
            
            # Check if country code is valid
            if parts[1] not in valid_country_codes:
                return _("Invalid country code. Must be a valid ISO 3166-1 code")
            
            # If we have a third part (script), it should be 4 letters with first uppercase
            if len(parts) > 2:
                if not parts[2].isalpha() or len(parts[2]) != 4 or not parts[2][0].isupper():
                    return _("Script code must be a four-letter code with first letter uppercase")
                
                # Check if script code is valid
                if parts[2] not in valid_script_codes:
                    return _("Invalid script code. Must be a valid ISO 15924 code")
        
        return None 