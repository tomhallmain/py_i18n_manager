from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt
from utils.translations import I18N

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
        
    def update_stats(self, total_translations, total_locales, missing_translations, stale_translations=0, invalid_unicode=0, invalid_indices=0):
        self.total_translations_value.setText(str(total_translations))
        self.total_locales_value.setText(str(total_locales))
        
        # Update missing translations with color
        missing_text = f"{missing_translations}"
        if missing_translations == 0:
            self.missing_translations_value.setText(f'<span style="color: #2ecc71;">{missing_text}</span>')
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
            self.missing_translations_value.setText(missing_text)
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
        invalid_unicode_text = f"{invalid_unicode}"
        if invalid_unicode == 0:
            self.invalid_unicode_value.setText(f'<span style="color: #2ecc71;">{invalid_unicode_text}</span>')
        else:
            self.invalid_unicode_value.setText(invalid_unicode_text)
            
        # Update invalid indices with color
        invalid_indices_text = f"{invalid_indices}"
        if invalid_indices == 0:
            self.invalid_indices_value.setText(f'<span style="color: #2ecc71;">{invalid_indices_text}</span>')
        else:
            self.invalid_indices_value.setText(invalid_indices_text)
            
        # Update stale translations with color
        stale_text = f"{stale_translations}"
        if stale_translations == 0:
            self.stale_translations_value.setText(f'<span style="color: #2ecc71;">{stale_text}</span>')
        else:
            self.stale_translations_value.setText(f'<span style="color: #f1c40f;">{stale_text}</span>') 