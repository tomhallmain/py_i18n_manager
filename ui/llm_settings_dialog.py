"""Dialog for configuring LLM translation prompt template."""

from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QTextEdit, QFrame, QCheckBox,
                            QMessageBox, QGroupBox, QScrollArea, QWidget, QSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from lib.multi_display import SmartDialog
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager
from utils.translations import I18N

_ = I18N._

logger = get_logger("llm_settings_dialog")


class LLMSettingsDialog(SmartDialog):
    """Dialog for editing the LLM translation prompt template."""
    
    settings_saved = pyqtSignal()  # Emitted when settings are saved
    
    def __init__(self, project_path=None, parent=None):
        """Initialize the LLM settings dialog.
        
        Args:
            project_path (str, optional): Path to the current project for project-specific overrides
            parent: Parent widget
        """
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=_("LLM Translation Settings"),
            geometry="700x600",
            offset_x=50,
            offset_y=50,
        )
        self.project_path = project_path
        self.settings_manager = SettingsManager()
        self.setMinimumSize(600, 500)
        self.setup_ui()
        self.load_settings()
        
    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Info label
        info_label = QLabel(
            _("Configure the prompt template used when translating with LLM.\n"
              "Use the variables below to customize how translation requests are formatted.")
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Variables reference section
        variables_group = QGroupBox(_("Available Variables"))
        variables_layout = QVBoxLayout(variables_group)
        
        variables_info = SettingsManager.get_llm_prompt_variables()
        for var_info in variables_info:
            var_label = QLabel(f"<b>{var_info['name']}</b> - {var_info['description']}")
            var_label.setTextFormat(Qt.TextFormat.RichText)
            variables_layout.addWidget(var_label)
        
        # Note about escaping braces
        escape_note = QLabel(
            _("<i>Note: To include literal braces in the output, use double braces: {{{{ or }}}}</i>")
        )
        escape_note.setTextFormat(Qt.TextFormat.RichText)
        escape_note.setStyleSheet("color: gray;")
        variables_layout.addWidget(escape_note)
        
        layout.addWidget(variables_group)
        
        # Prompt template editor section
        template_group = QGroupBox(_("Prompt Template"))
        template_layout = QVBoxLayout(template_group)
        
        self.template_editor = QTextEdit()
        self.template_editor.setMinimumHeight(200)
        self.template_editor.setFont(QFont("Consolas", 10))
        self.template_editor.setPlaceholderText(_("Enter your prompt template here..."))
        self.template_editor.textChanged.connect(self.on_template_changed)
        template_layout.addWidget(self.template_editor)
        
        layout.addWidget(template_group)

        # CJK filtering settings
        cjk_group = QGroupBox(_("CJK Response Filtering"))
        cjk_layout = QVBoxLayout(cjk_group)

        cjk_info = QLabel(
            _("Reject LLM responses with high CJK character ratio for non-CJK target locales.\n"
              "CJK target locales always bypass this filter.")
        )
        cjk_info.setWordWrap(True)
        cjk_layout.addWidget(cjk_info)

        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel(_("Reject threshold:")))
        self.cjk_threshold_spinbox = QSpinBox()
        self.cjk_threshold_spinbox.setRange(0, 100)
        self.cjk_threshold_spinbox.setSuffix("%")
        self.cjk_threshold_spinbox.setToolTip(
            _("If CJK characters exceed this percentage, the response is rejected for non-CJK locales.")
        )
        threshold_layout.addWidget(self.cjk_threshold_spinbox)
        threshold_layout.addStretch()
        cjk_layout.addLayout(threshold_layout)
        layout.addWidget(cjk_group)
        
        # Preview section
        preview_group = QGroupBox(_("Preview (Example Output)"))
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(150)
        self.preview_text.setFont(QFont("Consolas", 9))
        self.preview_text.setStyleSheet("background-color: #f5f5f5;")
        preview_layout.addWidget(self.preview_text)
        
        layout.addWidget(preview_group)
        
        # Project override checkbox
        if self.project_path:
            self.project_override_checkbox = QCheckBox(
                _("Save as project-specific override (only for this project)")
            )
            self.project_override_checkbox.setToolTip(
                _("If checked, this template will only be used for the current project.\n"
                  "If unchecked, it will be saved as the global default for all projects.")
            )
            layout.addWidget(self.project_override_checkbox)
        else:
            self.project_override_checkbox = None
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.reset_btn = QPushButton(_("Reset to Default"))
        self.reset_btn.clicked.connect(self.reset_to_default)
        button_layout.addWidget(self.reset_btn)
        
        if self.project_path:
            self.clear_override_btn = QPushButton(_("Clear Project Override"))
            self.clear_override_btn.clicked.connect(self.clear_project_override)
            self.clear_override_btn.setToolTip(_("Remove project-specific template and use global default"))
            button_layout.addWidget(self.clear_override_btn)
        
        button_layout.addStretch()
        
        self.save_btn = QPushButton(_("Save"))
        self.save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = QPushButton(_("Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def load_settings(self):
        """Load current settings into the dialog."""
        # Get current template
        template = self.settings_manager.get_llm_prompt_template(self.project_path)
        self.template_editor.setText(template)
        threshold = self.settings_manager.get_llm_cjk_reject_threshold_percentage(self.project_path)
        self.cjk_threshold_spinbox.setValue(threshold)
        
        # Set checkbox state if project path is set
        if self.project_path and self.project_override_checkbox:
            has_override = (
                self.settings_manager.has_project_llm_prompt_template(self.project_path) or
                self.settings_manager.has_project_llm_cjk_reject_threshold(self.project_path)
            )
            self.project_override_checkbox.setChecked(has_override)
            
            # Update clear override button state
            if hasattr(self, 'clear_override_btn'):
                self.clear_override_btn.setEnabled(has_override)
        
        self.update_preview()
    
    def on_template_changed(self):
        """Handle template text changes."""
        self.update_preview()
    
    def update_preview(self):
        """Update the preview with example values."""
        template = self.template_editor.toPlainText()
        
        # Example values for preview
        example_values = {
            "source_locale": "en",
            "target_locale": "es",
            "source_text": "Welcome to our application",
            "context": "Context: Translation key: views.home.welcome_message"
        }
        
        try:
            preview = template.format(**example_values)
            self.preview_text.setText(preview)
            self.preview_text.setStyleSheet("background-color: #f5f5f5;")
        except KeyError as e:
            self.preview_text.setText(f"Error: Unknown variable {e}")
            self.preview_text.setStyleSheet("background-color: #ffe0e0;")
        except Exception as e:
            self.preview_text.setText(f"Error: {str(e)}")
            self.preview_text.setStyleSheet("background-color: #ffe0e0;")
    
    def reset_to_default(self):
        """Reset the template to the default."""
        reply = QMessageBox.question(
            self,
            _("Reset to Default"),
            _("Are you sure you want to reset the template to the default?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            default_template = SettingsManager.get_default_llm_prompt_template()
            self.template_editor.setText(default_template)
            self.cjk_threshold_spinbox.setValue(SettingsManager.DEFAULT_LLM_CJK_REJECT_THRESHOLD_PERCENTAGE)
    
    def clear_project_override(self):
        """Clear the project-specific template override."""
        if not self.project_path:
            return
            
        reply = QMessageBox.question(
            self,
            _("Clear Project Override"),
            _("Are you sure you want to remove the project-specific template?\n"
              "The global default will be used instead."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            clear_template_ok = self.settings_manager.clear_project_llm_prompt_template(self.project_path)
            clear_threshold_ok = self.settings_manager.clear_project_llm_cjk_reject_threshold(self.project_path)
            if clear_template_ok and clear_threshold_ok:
                # Reload with global template
                global_template = self.settings_manager.get_llm_prompt_template(None)
                self.template_editor.setText(global_template)
                global_threshold = self.settings_manager.get_llm_cjk_reject_threshold_percentage(None)
                self.cjk_threshold_spinbox.setValue(global_threshold)
                
                if self.project_override_checkbox:
                    self.project_override_checkbox.setChecked(False)
                
                if hasattr(self, 'clear_override_btn'):
                    self.clear_override_btn.setEnabled(False)
                    
                QMessageBox.information(
                    self,
                    _("Success"),
                    _("Project override cleared. Using global default template.")
                )
            else:
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _("Failed to clear project override.")
                )
    
    def save_settings(self):
        """Save the current settings."""
        template = self.template_editor.toPlainText().strip()
        cjk_threshold = self.cjk_threshold_spinbox.value()
        
        if not template:
            QMessageBox.warning(
                self,
                _("Invalid Template"),
                _("The template cannot be empty.")
            )
            return
        
        # Validate template has required variables
        required_vars = ["{source_text}", "{target_locale}"]
        missing_vars = [v for v in required_vars if v not in template]
        
        if missing_vars:
            reply = QMessageBox.warning(
                self,
                _("Missing Variables"),
                _("The template is missing recommended variables: {vars}\n\n"
                  "This may cause translation issues. Save anyway?").format(vars=", ".join(missing_vars)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # Determine where to save
        save_to_project = (
            self.project_path and 
            self.project_override_checkbox and 
            self.project_override_checkbox.isChecked()
        )
        
        if save_to_project:
            success_template = self.settings_manager.save_llm_prompt_template(template, self.project_path)
            success_threshold = self.settings_manager.save_llm_cjk_reject_threshold_percentage(cjk_threshold, self.project_path)
            location = _("project")
        else:
            success_template = self.settings_manager.save_llm_prompt_template(template, None)
            success_threshold = self.settings_manager.save_llm_cjk_reject_threshold_percentage(cjk_threshold, None)
            location = _("global")
        success = success_template and success_threshold
        
        if success:
            logger.info(f"LLM prompt template saved to {location} settings")
            self.settings_saved.emit()
            self.accept()
        else:
            QMessageBox.warning(
                self,
                _("Error"),
                _("Failed to save settings.")
            )
    
    def get_template(self) -> str:
        """Get the current template text.
        
        Returns:
            str: The current template
        """
        return self.template_editor.toPlainText()
