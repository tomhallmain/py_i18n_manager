"""Dialog for adding a locale with ISO-based fields and cross-project suggestions."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display import SmartDialog
from ui.app_style import AppStyle
from utils.globals import (
    FALLBACK_SUGGESTED_LANGUAGE_CODES,
    valid_country_codes,
    valid_language_codes,
    valid_script_codes,
)
from utils.settings_manager import SettingsManager
from utils.translations import I18N

_ = I18N._

MAX_SUGGESTION_BUTTONS = 18


def validate_locale_code(locale_code: str) -> str | None:
    """Validate a locale tag against stored ISO sets.

    Supported shapes (underscore-separated), matching existing project validation:
    - ``xx`` — ISO 639-1 language
    - ``xx_YY`` — language + ISO 3166-1 country (uppercase)
    - ``xx_YY_Ssss`` — language + country + ISO 15924 script (title case, e.g. Latn)

    Returns:
        None if valid, otherwise a translated error message string.
    """
    parts = locale_code.split("_")

    if not parts or not parts[0].isalpha() or len(parts[0]) != 2:
        return _("Language code must be a two-letter ISO 639-1 code")

    if parts[0].lower() not in valid_language_codes:
        return _("Invalid language code. Must be a valid ISO 639-1 code")

    if len(parts) > 1:
        if not parts[1].isalpha() or len(parts[1]) != 2 or not parts[1].isupper():
            return _("Country code must be a two-letter uppercase ISO 3166-1 code")

        if parts[1] not in valid_country_codes:
            return _("Invalid country code. Must be a valid ISO 3166-1 code")

        if len(parts) > 2:
            if not parts[2].isalpha() or len(parts[2]) != 4 or not parts[2][0].isupper():
                return _("Script code must be a four-letter code with first letter uppercase")

            if parts[2] not in valid_script_codes:
                return _("Invalid script code. Must be a valid ISO 15924 code")

    return None


def compose_locale_tag(language: str, country: str, script: str) -> str:
    """Build a locale tag from fields. Country and script may be empty."""
    lang = language.strip().lower()
    cc = country.strip().upper()
    sc = script.strip()
    if len(sc) == 4:
        sc = sc[0].upper() + sc[1:].lower()
    if not cc and not sc:
        return lang
    if not cc:
        raise ValueError("country required when script is set")
    if not sc:
        return f"{lang}_{cc}"
    return f"{lang}_{cc}_{sc}"


class LocaleSelectionWindow(SmartDialog):
    """Pick a locale with optional region and script, plus usage-based suggestions."""

    locale_selected = pyqtSignal(str)

    def __init__(
        self,
        *,
        settings_manager: SettingsManager,
        existing_locales: set[str] | frozenset[str],
        parent=None,
    ):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=_("Add locale"),
            geometry="720x620",
            offset_x=50,
            offset_y=50,
        )
        self.settings_manager = settings_manager
        self._exclude = frozenset(existing_locales)
        self.setMinimumSize(720, 620)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        AppStyle.sync_theme_from_widget(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        intro = QLabel(
            _(
                "Choose a language code (required). Country and script are optional. "
                "A script requires a country code."
            )
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        sugg_box = QGroupBox(_("Suggestions from other projects"))
        sugg_layout = QVBoxLayout(sugg_box)
        sugg_layout.setSpacing(8)

        self._suggestions_scroll = QScrollArea()
        self._suggestions_scroll.setWidgetResizable(True)
        self._suggestions_scroll.setMinimumHeight(140)
        self._suggestions_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._suggestions_inner = QWidget()
        self._suggestions_grid = QGridLayout(self._suggestions_inner)
        self._suggestions_grid.setContentsMargins(8, 8, 8, 8)
        self._suggestions_grid.setHorizontalSpacing(8)
        self._suggestions_grid.setVerticalSpacing(8)
        self._suggestions_scroll.setWidget(self._suggestions_inner)
        sugg_layout.addWidget(self._suggestions_scroll)

        self._populate_suggestions()
        root.addWidget(sugg_box)

        form_frame = QFrame()
        form_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        form = QFormLayout(form_frame)
        form.setSpacing(12)
        form.setContentsMargins(12, 12, 12, 12)

        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        for code in sorted(valid_language_codes):
            self.lang_combo.addItem(code)
        le = self.lang_combo.lineEdit()
        if le:
            le.setPlaceholderText(_("ISO 639-1 (e.g. de)"))
        lang_completer = QCompleter(sorted(valid_language_codes), self.lang_combo)
        lang_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        lang_completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self.lang_combo.setCompleter(lang_completer)

        self.country_edit = QLineEdit()
        self.country_edit.setMaxLength(2)
        self.country_edit.setPlaceholderText(_("Optional — ISO 3166-1 (e.g. US)"))

        self.script_edit = QLineEdit()
        self.script_edit.setMaxLength(4)
        self.script_edit.setPlaceholderText(_("Optional — ISO 15924 (e.g. Latn); requires country"))

        form.addRow(_("Language:"), self.lang_combo)
        form.addRow(_("Country:"), self.country_edit)
        form.addRow(_("Script:"), self.script_edit)

        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px 0;")
        form.addRow(_("Preview:"), self.preview_label)

        root.addWidget(form_frame)

        for w in (self.lang_combo, self.country_edit, self.script_edit):
            w_edit = w.lineEdit() if isinstance(w, QComboBox) else w
            if w_edit:
                w_edit.textChanged.connect(self._update_preview)
        self.lang_combo.currentTextChanged.connect(self._update_preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText(_("Add locale"))
        root.addWidget(buttons)

        self._update_preview()

    def _clear_suggestion_grid(self) -> None:
        while self._suggestions_grid.count():
            item = self._suggestions_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate_suggestions(self) -> None:
        self._clear_suggestion_grid()
        counts = self.settings_manager.get_commonly_used_locale_counts(self._exclude)
        rows: list[tuple[str, str]] = []

        if counts:
            for i, (loc, n) in enumerate(counts.items()):
                if i >= MAX_SUGGESTION_BUTTONS:
                    break
                rows.append((f"{loc}  ({n})", loc))
        else:
            for lang in FALLBACK_SUGGESTED_LANGUAGE_CODES:
                if lang in self._exclude:
                    continue
                rows.append((lang, lang))

        if not rows:
            empty = QLabel(_("No suggestions yet — use the fields below."))
            empty.setWordWrap(True)
            self._suggestions_grid.addWidget(empty, 0, 0, 1, 3)
            return

        cols = 3
        for i, (label, tag) in enumerate(rows):
            btn = QPushButton(label)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(36)
            btn.clicked.connect(lambda _checked=False, t=tag: self._apply_suggestion(t))
            r, c = divmod(i, cols)
            self._suggestions_grid.addWidget(btn, r, c)

    def _apply_suggestion(self, locale_tag: str) -> None:
        parts = locale_tag.split("_")
        lang = parts[0].lower() if parts else ""
        idx = self.lang_combo.findText(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        else:
            self.lang_combo.setCurrentText(lang)
        if len(parts) >= 2:
            self.country_edit.setText(parts[1].upper())
        else:
            self.country_edit.clear()
        if len(parts) >= 3:
            self.script_edit.setText(parts[2])
        else:
            self.script_edit.clear()
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            lang = self.lang_combo.currentText().strip().lower()
            cc = self.country_edit.text().strip().upper()
            sc = self.script_edit.text().strip()
            if not lang:
                self.preview_label.setText("—")
                return
            if not cc and not sc:
                self.preview_label.setText(lang)
                return
            tag = compose_locale_tag(lang, cc, sc)
            self.preview_label.setText(tag)
        except Exception:
            self.preview_label.setText(_("(invalid combination)"))

    def _on_accept(self) -> None:
        lang = self.lang_combo.currentText().strip().lower()
        if not lang:
            QMessageBox.warning(self, _("Error"), _("Please enter a language code."))
            return

        cc = self.country_edit.text().strip().upper()
        sc = self.script_edit.text().strip()
        if len(sc) == 4:
            sc = sc[0].upper() + sc[1:].lower()

        if not cc and sc:
            QMessageBox.warning(
                self,
                _("Error"),
                _("A country code is required when a script code is set."),
            )
            return

        if cc and len(cc) != 2:
            QMessageBox.warning(
                self,
                _("Error"),
                _("Country code must be exactly two letters when provided."),
            )
            return

        try:
            candidate = compose_locale_tag(lang, cc, sc)
        except ValueError as e:
            QMessageBox.warning(self, _("Error"), str(e))
            return

        err = validate_locale_code(candidate)
        if err:
            QMessageBox.warning(self, _("Invalid locale"), err)
            return

        self.locale_selected.emit(candidate)
        self.accept()
