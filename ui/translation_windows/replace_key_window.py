from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QMenu,
    QMessageBox,
)

from i18n.translation_group import TranslationGroup, TranslationKey
from ui.translation_windows.base_translation_window import BaseTranslationWindow
from utils.translations import I18N

_ = I18N._


def _key_display(key: Any) -> str:
    if isinstance(key, TranslationKey):
        return f"{key.context} | {key.msgid}" if key.context else key.msgid
    return str(key)


class ReplaceKeyWindow(BaseTranslationWindow):
    """Replace an existing translation key with a new one.

    Particularly useful for Python projects, where the key *is* the default-locale text:
    renaming a key there is really "the English source string changed", and the old
    translations for other locales are usually still a reasonable starting point for the new
    key rather than something to retype from scratch. The new key's msgid is edited directly in
    the (here, editable) key cell, matching how OutstandingItemsWindow/AllTranslationsWindow
    already show one row per key with a locale-per-column table; every other locale's carried-
    over value is editable the same way, and can be filled in with Argos/LLM via the same
    per-cell context-menu translate action those windows offer.

    Doesn't touch the shared translations dict or write anything itself -- collects the new key
    and its per-locale values, then emits ``key_replaced`` for the opening window to apply,
    exactly like that window already handles delete (see e.g.
    OutstandingItemsWindow.delete_translation_group_for_row / AllTranslationsWindow's own).
    """

    key_replaced = pyqtSignal(object, object)  # old_key, new_group (TranslationGroup)

    def __init__(
        self,
        parent,
        project_path: Optional[str],
        old_key: Any,
        group: TranslationGroup,
        locales: list,
        translations: Dict[Any, TranslationGroup],
    ):
        super().__init__(parent, title=_("Replace Translation Key"), geometry="900x400")
        self.project_path = project_path
        self.old_key = old_key
        self.group = group
        self.locales = locales
        self.translations = translations  # read-only reference, used for collision checks only

        self.setup_translation_service(project_path)
        self.setup_ui()
        self.load_data()

    # -- BaseTranslationWindow hooks: route per-cell translate at the *old* key/group, so
    # "Translate with Argos/LLM" on a locale cell suggests a value from the old source text.
    def _get_translations_catalog(self) -> Optional[Dict[Any, TranslationGroup]]:
        return {self.old_key: self.group}

    def _translation_key_for_row(self, row: int) -> Any:
        return self.old_key

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        info_label = QLabel(
            _("Replacing key: {key}").format(key=_key_display(self.old_key))
        )
        info_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(info_label)

        note = QLabel(
            _(
                "Edit the key text in the first column below to define the new key. Existing "
                "translations for other locales are carried over as a starting point -- edit or "
                "clear any that no longer apply. Right-click a locale cell to translate it with "
                "Argos or an LLM."
            )
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(note)

        context_form = QFormLayout()
        self.context_edit = QLineEdit(self.old_key.context if isinstance(self.old_key, TranslationKey) else "")
        self.context_edit.setPlaceholderText(_("Optional -- leave blank unless this project uses msgctxt"))
        context_form.addRow(_("Context:"), self.context_edit)
        layout.addLayout(context_form)

        self.table = self.setup_table()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        if hasattr(self.table, "_frozen_table"):
            self.table._frozen_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table._frozen_table.customContextMenuRequested.connect(self.show_frozen_context_menu)
        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        self.replace_btn = QPushButton(_("Replace Key"))
        self.replace_btn.setDefault(True)
        self.replace_btn.clicked.connect(self._on_replace_clicked)
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.close)
        button_layout.addWidget(self.replace_btn)
        button_layout.addWidget(cancel_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def load_data(self) -> None:
        self.table.setColumnCount(len(self.locales) + 1)
        self.table.setHorizontalHeaderLabels([_("New Key")] + list(self.locales))
        self.set_dynamic_column_widths(len(self.locales))
        self.table.setRowCount(1)

        old_msgid = self.old_key.msgid if isinstance(self.old_key, TranslationKey) else str(self.old_key)
        key_item = QTableWidgetItem(old_msgid)
        self.table.setItem(0, 0, key_item)

        for col, locale in enumerate(self.locales, 1):
            item = QTableWidgetItem(self.group.get_translation_as_text(locale))
            self.table.setItem(0, col, item)

    # -- Context menu: translate a locale cell using the old key's source text --------------

    def show_context_menu(self, position) -> None:
        item = self.table.itemAt(position)
        if not item:
            return
        self._show_context_menu_for_item(item, self.table.mapToGlobal(position))

    def show_frozen_context_menu(self, position) -> None:
        frozen = self.table._frozen_table
        index = frozen.indexAt(position)
        if not index.isValid():
            return
        item = self.table.item(index.row(), index.column())
        if not item:
            return
        self._show_context_menu_for_item(item, frozen.viewport().mapToGlobal(position))

    def _show_context_menu_for_item(self, item, global_position) -> None:
        if item.column() == 0:
            return
        menu = QMenu()
        argos = QAction(_("Translate with Argos Translate"), self)
        argos.triggered.connect(lambda: self.translate_selected_item(item, use_llm=False))
        menu.addAction(argos)
        llm = QAction(_("Translate with LLM"), self)
        llm.triggered.connect(lambda: self.translate_selected_item(item, use_llm=True))
        menu.addAction(llm)
        menu.exec(global_position)

    # -- Replace -------------------------------------------------------------------------

    def _on_replace_clicked(self) -> None:
        key_item = self.table.item(0, 0)
        new_msgid = (key_item.text() if key_item else "").strip()
        if not new_msgid:
            QMessageBox.warning(self, _("Replace Key"), _("The new key cannot be empty."))
            return

        new_context = self.context_edit.text().strip()
        new_key = TranslationKey(new_msgid, context=new_context)

        if new_key != self.old_key and new_key in self.translations:
            QMessageBox.warning(
                self,
                _("Replace Key"),
                _(
                    "A translation key with this text already exists (\"{key}\"). Choose a "
                    "different key, or edit that key directly instead."
                ).format(key=_key_display(new_key)),
            )
            return

        reply = QMessageBox.question(
            self,
            _("Confirm Replace"),
            _(
                "Replace key \"{old}\" with \"{new}\"?\n\n"
                "The old key and its translations will be removed; the values shown above will "
                "be saved under the new key."
            ).format(old=_key_display(self.old_key), new=_key_display(new_key)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        new_group = TranslationGroup(
            new_msgid,
            is_in_base=self.group.is_in_base,
            usage_comment=self.group.usage_comment,
            tcomment=self.group.tcomment,
            context=new_context or None,
        )
        new_group.occurrences = list(self.group.occurrences)
        for col, locale in enumerate(self.locales, 1):
            item = self.table.item(0, col)
            new_group.add_translation(locale, item.text() if item else "")

        self.key_replaced.emit(self.old_key, new_group)
        self.close()
