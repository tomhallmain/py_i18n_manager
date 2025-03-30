import logging

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from i18n.translation_manager_results import TranslationManagerResults
from utils.translations import I18N

logger = logging.getLogger(__name__)

_ = I18N._

class StatsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.setStyleSheet("""
            QWidget {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Create a frame for better visual separation
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        frame_layout = QVBoxLayout(frame)
        
        # Title
        title = QLabel(_("Translation Statistics"))
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        frame_layout.addWidget(title)
        
        # Stats grid
        stats_layout = QHBoxLayout()
        
        # Total translations
        total_translations_layout = QVBoxLayout()
        self.total_translations_label = QLabel(_("Total Translations:"))
        self.total_translations_value = QLabel("0")
        self.total_translations_value.setStyleSheet("font-size: 16px; font-weight: bold;")
        total_translations_layout.addWidget(self.total_translations_label)
        total_translations_layout.addWidget(self.total_translations_value)
        stats_layout.addLayout(total_translations_layout)
        
        # Total locales
        total_locales_layout = QVBoxLayout()
        self.total_locales_label = QLabel(_("Total Locales:"))
        self.total_locales_value = QLabel("0")
        self.total_locales_value.setStyleSheet("font-size: 16px; font-weight: bold;")
        total_locales_layout.addWidget(self.total_locales_label)
        total_locales_layout.addWidget(self.total_locales_value)
        stats_layout.addLayout(total_locales_layout)
        
        # Missing translations
        missing_translations_layout = QVBoxLayout()
        self.missing_translations_label = QLabel(_("Missing Translations:"))
        self.missing_translations_value = QLabel("0")
        self.missing_translations_value.setStyleSheet("font-size: 16px; font-weight: bold; color: red;")
        missing_translations_layout.addWidget(self.missing_translations_label)
        missing_translations_layout.addWidget(self.missing_translations_value)
        stats_layout.addLayout(missing_translations_layout)
        
        # Invalid Unicode translations
        invalid_unicode_layout = QVBoxLayout()
        self.invalid_unicode_label = QLabel(_("Invalid Unicode:"))
        self.invalid_unicode_value = QLabel("0")
        self.invalid_unicode_value.setStyleSheet("font-size: 16px; font-weight: bold; color: red;")
        invalid_unicode_layout.addWidget(self.invalid_unicode_label)
        invalid_unicode_layout.addWidget(self.invalid_unicode_value)
        stats_layout.addLayout(invalid_unicode_layout)
        
        # Invalid indices translations
        invalid_indices_layout = QVBoxLayout()
        self.invalid_indices_label = QLabel(_("Invalid Indices:"))
        self.invalid_indices_value = QLabel("0")
        self.invalid_indices_value.setStyleSheet("font-size: 16px; font-weight: bold; color: red;")
        invalid_indices_layout.addWidget(self.invalid_indices_label)
        invalid_indices_layout.addWidget(self.invalid_indices_value)
        stats_layout.addLayout(invalid_indices_layout)
        
        # Invalid braces translations
        invalid_braces_layout = QVBoxLayout()
        self.invalid_braces_label = QLabel(_("Invalid Braces:"))
        self.invalid_braces_value = QLabel("0")
        self.invalid_braces_value.setStyleSheet("font-size: 16px; font-weight: bold; color: orange;")
        invalid_braces_layout.addWidget(self.invalid_braces_label)
        invalid_braces_layout.addWidget(self.invalid_braces_value)
        stats_layout.addLayout(invalid_braces_layout)
        
        # Invalid leading space translations
        invalid_leading_space_layout = QVBoxLayout()
        self.invalid_leading_space_label = QLabel(_("Invalid Leading Space:"))
        self.invalid_leading_space_value = QLabel("0")
        self.invalid_leading_space_value.setStyleSheet("font-size: 16px; font-weight: bold; color: orange;")
        invalid_leading_space_layout.addWidget(self.invalid_leading_space_label)
        invalid_leading_space_layout.addWidget(self.invalid_leading_space_value)
        stats_layout.addLayout(invalid_leading_space_layout)
        
        # Invalid newline translations
        invalid_newline_layout = QVBoxLayout()
        self.invalid_newline_label = QLabel(_("Invalid Newline:"))
        self.invalid_newline_value = QLabel("0")
        self.invalid_newline_value.setStyleSheet("font-size: 16px; font-weight: bold; color: orange;")
        invalid_newline_layout.addWidget(self.invalid_newline_label)
        invalid_newline_layout.addWidget(self.invalid_newline_value)
        stats_layout.addLayout(invalid_newline_layout)
        
        # Stale translations
        stale_translations_layout = QVBoxLayout()
        self.stale_translations_label = QLabel(_("Stale Translations:"))
        self.stale_translations_value = QLabel("0")
        self.stale_translations_value.setStyleSheet("font-size: 16px; font-weight: bold;")
        stale_translations_layout.addWidget(self.stale_translations_label)
        stale_translations_layout.addWidget(self.stale_translations_value)
        stats_layout.addLayout(stale_translations_layout)
        
        frame_layout.addLayout(stats_layout)
        layout.addWidget(frame)

    def update_stats(self, results: TranslationManagerResults):
        """Update the statistics display.
        
        Args:
            results: TranslationManagerResults object containing all translation data
        """
        # Calculate basic stats
        total_translations = results.total_strings
        total_locales = results.total_locales

        # Update basic stats
        self.total_translations_value.setText(str(total_translations))
        self.total_locales_value.setText(str(total_locales))
        
        # Calculate counts from invalid_groups
        missing_count = 0
        invalid_unicode_count = 0
        invalid_indices_count = 0
        invalid_braces_count = 0
        invalid_leading_space_count = 0
        invalid_newline_count = 0
        stale_count = 0
        if results.invalid_groups:
            invalid_groups = results.invalid_groups
            missing_count = sum(len(locales) for _, locales in invalid_groups.missing_locale_groups)
            invalid_unicode_count = sum(len(locales) for _, locales in invalid_groups.invalid_unicode_locale_groups)
            invalid_indices_count = sum(len(locales) for _, locales in invalid_groups.invalid_index_locale_groups)
            invalid_braces_count = sum(len(locales) for _, locales in invalid_groups.invalid_brace_locale_groups)
            invalid_leading_space_count = sum(len(locales) for _, locales in invalid_groups.invalid_leading_space_locale_groups)
            invalid_newline_count = sum(len(locales) for _, locales in invalid_groups.invalid_newline_locale_groups)
            stale_count = len(invalid_groups.not_in_base)

        logger.debug(f"Calculated stats - total_translations: {total_translations}, "
                    f"total_locales: {total_locales}, missing_translations: {missing_count}")

        # Update missing translations with color
        if missing_count == 0:
            self.missing_translations_value.setText(f'<span style="color: #2ecc71;">{missing_count}</span>')
            # Set light green background for the entire widget
            self.setStyleSheet("""
                QWidget {
                    background-color: #e8f5e9;
                    border: 1px solid #a5d6a7;
                    border-radius: 4px;
                    padding: 10px;
                }
            """)
        else:
            self.missing_translations_value.setText(f"{missing_count}")
            # Reset to default style
            self.setStyleSheet("""
                QWidget {
                    background-color: #f0f0f0;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 10px;
                }
            """)
            
        # Update invalid Unicode with color
        if invalid_unicode_count == 0:
            self.invalid_unicode_value.setText(f'<span style="color: #2ecc71;">{invalid_unicode_count}</span>')
        else:
            self.invalid_unicode_value.setText(f"{invalid_unicode_count}")
            
        # Update invalid indices with color
        if invalid_indices_count == 0:
            self.invalid_indices_value.setText(f'<span style="color: #2ecc71;">{invalid_indices_count}</span>')
        else:
            self.invalid_indices_value.setText(f"{invalid_indices_count}")
            
        # Update invalid braces with color
        if invalid_braces_count == 0:
            self.invalid_braces_value.setText(f'<span style="color: #2ecc71;">{invalid_braces_count}</span>')
        else:
            self.invalid_braces_value.setText(f"{invalid_braces_count}")
            
        # Update invalid leading space with color
        if invalid_leading_space_count == 0:
            self.invalid_leading_space_value.setText(f'<span style="color: #2ecc71;">{invalid_leading_space_count}</span>')
        else:
            self.invalid_leading_space_value.setText(f"{invalid_leading_space_count}")
            
        # Update invalid newline with color
        if invalid_newline_count == 0:
            self.invalid_newline_value.setText(f'<span style="color: #2ecc71;">{invalid_newline_count}</span>')
        else:
            self.invalid_newline_value.setText(f"{invalid_newline_count}")
            
        # Update stale translations with color
        if stale_count == 0:
            self.stale_translations_value.setText(f'<span style="color: #2ecc71;">{stale_count}</span>')
        else:
            self.stale_translations_value.setText(f'<span style="color: #f1c40f;">{stale_count}</span>') 