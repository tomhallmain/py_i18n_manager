"""Dialog for configuring LLM translation settings: prompt templates (one per mode), the
translation mode itself, per-mode models, and CJK response filtering."""

from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                            QLabel, QTextEdit, QFrame, QCheckBox,
                            QMessageBox, QGroupBox, QScrollArea, QWidget, QSpinBox,
                            QRadioButton, QButtonGroup, QLineEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from lib.multi_display import SmartDialog
from utils.globals import LLMTranslationMode
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager
from utils.translations import I18N

_ = I18N._

logger = get_logger("llm_settings_dialog")


class LLMSettingsDialog(SmartDialog):
    """Dialog for editing LLM translation settings.

    The prompt-template editor is mode-aware: "one locale at a time" and "all locales per key"
    each have their own template (the latter must keep a locale-list variable, since its response
    is parsed as one JSON key per locale). Switching the mode radio swaps the editor's content;
    edits to whichever template isn't currently shown are buffered in memory and only written to
    settings on Save, so flipping the radio never discards unsaved changes.
    """

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
            geometry="700x850",
            offset_x=50,
            offset_y=50,
        )
        self.project_path = project_path
        self.settings_manager = SettingsManager()
        self.setMinimumSize(600, 750)

        # In-memory buffers for the template not currently shown in the editor (see class
        # docstring). Populated for real in load_settings(); placeholder values here only matter
        # if something reads them before that.
        self._single_locale_template_text = ""
        self._multi_locale_template_text = ""
        self._editor_mode = LLMTranslationMode.PER_LOCALE
        # Suppresses the mode-radio toggle handler while we set radio state programmatically
        # (load/reset/clear-override), so it doesn't also try to swap the editor mid-update.
        self._loading_settings = False

        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Info label
        info_label = QLabel(
            _("Configure the prompt templates used when translating with LLM.\n"
              "Use the variables below to customize how translation requests are formatted.")
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Translation mode + model settings
        mode_group = QGroupBox(_("Translation Mode & Model"))
        mode_layout = QVBoxLayout(mode_group)

        mode_info = QLabel(
            _("Choose how \"Translate All (LLM)\" issues requests. Translating all locales for "
              "a key at once is much faster (far fewer requests), but needs a model that "
              "reliably returns structured JSON covering multiple locales in one response - "
              "local models are often unreliable at this. Translating one locale at a time is "
              "slower but works better with small/local models. Each mode has its own prompt "
              "template, below.")
        )
        mode_info.setWordWrap(True)
        mode_layout.addWidget(mode_info)

        self.mode_button_group = QButtonGroup(self)
        self.per_locale_radio = QRadioButton(_("Translate one locale at a time (default)"))
        self.per_key_radio = QRadioButton(_("Translate all locales for a key at once"))
        self.mode_button_group.addButton(self.per_locale_radio)
        self.mode_button_group.addButton(self.per_key_radio)
        mode_layout.addWidget(self.per_locale_radio)
        mode_layout.addWidget(self.per_key_radio)
        self.per_locale_radio.toggled.connect(self._on_prompt_mode_radio_toggled)
        self.per_key_radio.toggled.connect(self._on_prompt_mode_radio_toggled)

        single_model_layout = QHBoxLayout()
        single_model_layout.addWidget(QLabel(_("Model (one locale at a time):")))
        self.single_model_edit = QLineEdit()
        self.single_model_edit.setPlaceholderText(SettingsManager.DEFAULT_LLM_MODEL)
        single_model_layout.addWidget(self.single_model_edit)
        mode_layout.addLayout(single_model_layout)

        multi_model_layout = QHBoxLayout()
        multi_model_layout.addWidget(QLabel(_("Model (all locales per key):")))
        self.multi_model_edit = QLineEdit()
        self.multi_model_edit.setPlaceholderText(SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE)
        multi_model_layout.addWidget(self.multi_model_edit)
        mode_layout.addLayout(multi_model_layout)

        model_note = QLabel(
            _("Models are Ollama model names (Ollama supports both local and cloud-hosted "
              "models). The default for \"all locales per key\" is {model}, a capable cloud "
              "model that follows multi-locale JSON instructions more reliably than typical "
              "local models. Some Ollama cloud models require a paid subscription - if you see "
              "a \"403 Forbidden\" error, try a different model here or run \"ollama run "
              "<model>\" in a terminal to check access first.").format(
                model=SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE
            )
        )
        model_note.setWordWrap(True)
        model_note.setStyleSheet("color: gray;")
        mode_layout.addWidget(model_note)

        layout.addWidget(mode_group)

        # Variables reference section - contents depend on which template is currently shown
        # below (e.g. {target_locale} vs {target_locales}); see _rebuild_variable_labels().
        variables_group = QGroupBox(_("Available Variables"))
        variables_outer_layout = QVBoxLayout(variables_group)

        self.variables_list_layout = QVBoxLayout()
        variables_outer_layout.addLayout(self.variables_list_layout)

        # Note about escaping braces
        escape_note = QLabel(
            _("<i>Note: To include literal braces in the output, use double braces: {{{{ or }}}}</i>")
        )
        escape_note.setTextFormat(Qt.TextFormat.RichText)
        escape_note.setStyleSheet("color: gray;")
        variables_outer_layout.addWidget(escape_note)

        layout.addWidget(variables_group)

        # Prompt template editor section - title reflects which mode's template is shown;
        # see _update_template_group_title().
        self.template_group = QGroupBox(_("Prompt Template"))
        template_layout = QVBoxLayout(self.template_group)

        self.template_editor = QTextEdit()
        self.template_editor.setMinimumHeight(200)
        self.template_editor.setFont(QFont("Consolas", 10))
        self.template_editor.setPlaceholderText(_("Enter your prompt template here..."))
        self.template_editor.textChanged.connect(self.on_template_changed)
        template_layout.addWidget(self.template_editor)

        layout.addWidget(self.template_group)

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
                _("If checked, these settings will only be used for the current project.\n"
                  "If unchecked, they will be saved as the global defaults for all projects.")
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
            self.clear_override_btn.setToolTip(_("Remove project-specific settings and use global defaults"))
            button_layout.addWidget(self.clear_override_btn)

        button_layout.addStretch()

        self.save_btn = QPushButton(_("Save"))
        self.save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton(_("Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

    # --- Mode-aware template editor -------------------------------------------------------

    def _current_mode_selection(self) -> LLMTranslationMode:
        """The mode implied by the current radio selection (not necessarily saved yet)."""
        return (
            LLMTranslationMode.PER_KEY_ALL_LOCALES
            if self.per_key_radio.isChecked()
            else LLMTranslationMode.PER_LOCALE
        )

    def _capture_editor_into_buffer(self):
        """Save the editor's current text into the buffer for whichever mode it's showing."""
        text = self.template_editor.toPlainText()
        if self._editor_mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
            self._multi_locale_template_text = text
        else:
            self._single_locale_template_text = text

    def _load_buffer_into_editor(self, mode: LLMTranslationMode):
        """Populate the editor from the buffer for the given mode and update everything that
        depends on which template is currently shown (group title, variables list, preview)."""
        text = (
            self._multi_locale_template_text
            if mode == LLMTranslationMode.PER_KEY_ALL_LOCALES
            else self._single_locale_template_text
        )
        self._editor_mode = mode
        self.template_editor.setPlainText(text)
        self._update_template_group_title()
        self._rebuild_variable_labels(multi_locale=(mode == LLMTranslationMode.PER_KEY_ALL_LOCALES))
        self.update_preview()

    def _update_template_group_title(self):
        if self._editor_mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
            self.template_group.setTitle(_("Prompt Template (all locales per key mode)"))
        else:
            self.template_group.setTitle(_("Prompt Template (one locale at a time mode)"))

    def _rebuild_variable_labels(self, multi_locale: bool):
        """Replace the variables reference list with the set that applies to the currently
        shown template (e.g. {target_locale} vs {target_locales})."""
        while self.variables_list_layout.count():
            item = self.variables_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for var_info in SettingsManager.get_llm_prompt_variables(multi_locale=multi_locale):
            var_label = QLabel(f"<b>{var_info['name']}</b> - {var_info['description']}")
            var_label.setTextFormat(Qt.TextFormat.RichText)
            self.variables_list_layout.addWidget(var_label)

    def _on_prompt_mode_radio_toggled(self, checked):
        """Swap the editor between the two templates when the mode selection changes, without
        losing whichever one was being edited - each mode's edits are buffered in memory and
        only written to settings on Save."""
        if not checked or self._loading_settings:
            return
        self._capture_editor_into_buffer()
        self._load_buffer_into_editor(self._current_mode_selection())

    # --- Load / reset / clear --------------------------------------------------------------

    def load_settings(self):
        """Load current settings into the dialog."""
        self._loading_settings = True
        try:
            self._single_locale_template_text = self.settings_manager.get_llm_prompt_template(self.project_path)
            self._multi_locale_template_text = self.settings_manager.get_llm_prompt_template_multi_locale(
                self.project_path
            )
            threshold = self.settings_manager.get_llm_cjk_reject_threshold_percentage(self.project_path)
            self.cjk_threshold_spinbox.setValue(threshold)

            mode = self.settings_manager.get_llm_translation_mode(self.project_path)
            if mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
                self.per_key_radio.setChecked(True)
            else:
                self.per_locale_radio.setChecked(True)
            self._load_buffer_into_editor(mode)

            self.single_model_edit.setText(self.settings_manager.get_llm_model(self.project_path))
            self.multi_model_edit.setText(self.settings_manager.get_llm_model_multi_locale(self.project_path))

            # Set checkbox state if project path is set
            if self.project_path and self.project_override_checkbox:
                has_override = (
                    self.settings_manager.has_project_llm_prompt_template(self.project_path) or
                    self.settings_manager.has_project_llm_prompt_template_multi_locale(self.project_path) or
                    self.settings_manager.has_project_llm_cjk_reject_threshold(self.project_path) or
                    self.settings_manager.has_project_llm_translation_mode(self.project_path) or
                    self.settings_manager.has_project_llm_model(self.project_path) or
                    self.settings_manager.has_project_llm_model_multi_locale(self.project_path)
                )
                self.project_override_checkbox.setChecked(has_override)

                # Update clear override button state
                if hasattr(self, 'clear_override_btn'):
                    self.clear_override_btn.setEnabled(has_override)
        finally:
            self._loading_settings = False

    def on_template_changed(self):
        """Handle template text changes."""
        self.update_preview()

    def update_preview(self):
        """Update the preview with example values."""
        template = self.template_editor.toPlainText()

        # Example values for preview - covers variables from both templates so whichever one
        # is currently shown previews without an "unknown variable" error.
        example_values = {
            "source_locale": "en",
            "target_locale": "es",
            "target_locales": "es, fr, de",
            "source_text": "Welcome to our application",
            "context": "Context: Translation key: views.home.welcome_message"
        }

        try:
            preview = template.format(**example_values)
            self.preview_text.setText(preview)
            self.preview_text.setStyleSheet("background-color: #f5f5f5;")
        except KeyError as e:
            self.preview_text.setText(_("Error: Unknown variable {var}").format(var=e))
            self.preview_text.setStyleSheet("background-color: #ffe0e0;")
        except Exception as e:
            self.preview_text.setText(_("Error: {error}").format(error=str(e)))
            self.preview_text.setStyleSheet("background-color: #ffe0e0;")

    def reset_to_default(self):
        """Reset the templates, mode, models, and CJK threshold to their defaults."""
        reply = QMessageBox.question(
            self,
            _("Reset to Default"),
            _("Are you sure you want to reset the prompt templates, translation mode, models, "
              "and CJK threshold to their defaults?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._loading_settings = True
            try:
                self._single_locale_template_text = SettingsManager.get_default_llm_prompt_template()
                self._multi_locale_template_text = SettingsManager.get_default_llm_prompt_template_multi_locale()
                self.cjk_threshold_spinbox.setValue(SettingsManager.DEFAULT_LLM_CJK_REJECT_THRESHOLD_PERCENTAGE)
                self.per_locale_radio.setChecked(True)
                self.single_model_edit.setText(SettingsManager.DEFAULT_LLM_MODEL)
                self.multi_model_edit.setText(SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE)
                self._load_buffer_into_editor(LLMTranslationMode.PER_LOCALE)
            finally:
                self._loading_settings = False

    def clear_project_override(self):
        """Clear the project-specific settings override."""
        if not self.project_path:
            return

        reply = QMessageBox.question(
            self,
            _("Clear Project Override"),
            _("Are you sure you want to remove the project-specific settings?\n"
              "The global defaults will be used instead."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            cleared = all([
                self.settings_manager.clear_project_llm_prompt_template(self.project_path),
                self.settings_manager.clear_project_llm_prompt_template_multi_locale(self.project_path),
                self.settings_manager.clear_project_llm_cjk_reject_threshold(self.project_path),
                self.settings_manager.clear_project_llm_translation_mode(self.project_path),
                self.settings_manager.clear_project_llm_model(self.project_path),
                self.settings_manager.clear_project_llm_model_multi_locale(self.project_path),
            ])
            if cleared:
                self._loading_settings = True
                try:
                    self._single_locale_template_text = self.settings_manager.get_llm_prompt_template(None)
                    self._multi_locale_template_text = self.settings_manager.get_llm_prompt_template_multi_locale(None)
                    global_threshold = self.settings_manager.get_llm_cjk_reject_threshold_percentage(None)
                    self.cjk_threshold_spinbox.setValue(global_threshold)

                    global_mode = self.settings_manager.get_llm_translation_mode(None)
                    if global_mode == LLMTranslationMode.PER_KEY_ALL_LOCALES:
                        self.per_key_radio.setChecked(True)
                    else:
                        self.per_locale_radio.setChecked(True)
                    self.single_model_edit.setText(self.settings_manager.get_llm_model(None))
                    self.multi_model_edit.setText(self.settings_manager.get_llm_model_multi_locale(None))
                    self._load_buffer_into_editor(global_mode)
                finally:
                    self._loading_settings = False

                if self.project_override_checkbox:
                    self.project_override_checkbox.setChecked(False)

                if hasattr(self, 'clear_override_btn'):
                    self.clear_override_btn.setEnabled(False)

                QMessageBox.information(
                    self,
                    _("Success"),
                    _("Project override cleared. Using global defaults.")
                )
            else:
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _("Failed to clear project override.")
                )

    def save_settings(self):
        """Save the current settings."""
        # Make sure whichever template is currently visible is captured before validating/saving.
        self._capture_editor_into_buffer()

        single_template = self._single_locale_template_text.strip()
        multi_template = self._multi_locale_template_text.strip()
        cjk_threshold = self.cjk_threshold_spinbox.value()
        mode = self._current_mode_selection()
        single_model = self.single_model_edit.text().strip() or SettingsManager.DEFAULT_LLM_MODEL
        multi_model = self.multi_model_edit.text().strip() or SettingsManager.DEFAULT_LLM_MODEL_MULTI_LOCALE

        if not single_template or not multi_template:
            QMessageBox.warning(
                self,
                _("Invalid Template"),
                _("Neither prompt template can be empty.")
            )
            return

        # Validate each template has its own required variables
        missing_notes = []
        single_missing = [v for v in ("{source_text}", "{target_locale}") if v not in single_template]
        if single_missing:
            missing_notes.append(
                _("\"One locale at a time\" template is missing: {vars}").format(vars=", ".join(single_missing))
            )
        multi_missing = [v for v in ("{source_text}", "{target_locales}") if v not in multi_template]
        if multi_missing:
            missing_notes.append(
                _("\"All locales per key\" template is missing: {vars}").format(vars=", ".join(multi_missing))
            )

        if missing_notes:
            reply = QMessageBox.warning(
                self,
                _("Missing Variables"),
                _("Some templates are missing recommended variables:\n\n{issues}\n\n"
                  "This may cause translation issues. Save anyway?").format(issues="\n".join(missing_notes)),
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
        target_project_path = self.project_path if save_to_project else None

        success = all([
            self.settings_manager.save_llm_prompt_template(single_template, target_project_path),
            self.settings_manager.save_llm_prompt_template_multi_locale(multi_template, target_project_path),
            self.settings_manager.save_llm_cjk_reject_threshold_percentage(cjk_threshold, target_project_path),
            self.settings_manager.save_llm_translation_mode(mode, target_project_path),
            self.settings_manager.save_llm_model(single_model, target_project_path),
            self.settings_manager.save_llm_model_multi_locale(multi_model, target_project_path),
        ])
        location = _("project") if save_to_project else _("global")

        if success:
            logger.info(f"LLM settings saved to {location} settings")
            self.settings_saved.emit()
            self.accept()
        else:
            QMessageBox.warning(
                self,
                _("Error"),
                _("Failed to save settings.")
            )

    def get_template(self) -> str:
        """Get the currently-displayed template text (whichever mode is currently selected).

        Returns:
            str: The current template
        """
        return self.template_editor.toPlainText()
