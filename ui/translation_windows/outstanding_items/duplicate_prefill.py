"""Duplicate default-value detection and pre-fill bookkeeping for the Outstanding Items window.

Extracted as-is from OutstandingItemsWindow: detecting when an outstanding translation shares
its default-locale value with an existing (already-translated) key, or with another outstanding
key, offering to pre-fill/group those, and tracking the resulting state across load_data
refreshes.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from utils.globals import config_manager
from utils.translations import I18N

_ = I18N._


def detect_duplicate_values(translations, locales, ignore_patterns=()):
    """Detect duplicate translation values in the default locale.

    Returns:
        tuple: (existing_to_outstanding_matches, outstanding_duplicates)
            - existing_to_outstanding_matches: dict mapping default_value to list of (existing_msgid, outstanding_msgid) tuples
            - outstanding_duplicates: dict mapping default_value to list of outstanding msgids
    """
    default_locale = config_manager.get('translation.default_locale', 'en')

    # Build map of default locale values to translation keys (normalized text; lists use join)
    value_to_keys = {}
    for key, group in translations.items():
        if not group.is_in_base:
            continue
        default_text = group.get_translation_as_text(default_locale)
        if default_text and default_text.strip():
            if default_text not in value_to_keys:
                value_to_keys[default_text] = []
            value_to_keys[default_text].append(key)

    # Find duplicates (values with multiple keys)
    existing_to_outstanding_matches = {}  # {default_value: [(existing_key, outstanding_key), ...]}
    outstanding_duplicates = {}  # {default_value: [outstanding_keys]}

    # Find all outstanding translations (those with errors)
    outstanding_keys = set()
    for key, group in translations.items():
        if not group.is_in_base:
            continue
        invalid_locales = group.get_invalid_translations(
            locales, ignore_patterns=ignore_patterns
        )
        if invalid_locales.has_errors:
            outstanding_keys.add(key)

    # Check for matches
    for default_value, keys in value_to_keys.items():
        if len(keys) > 1:
            # This value appears in multiple keys
            existing_keys = []
            outstanding_keys_for_value = []

            for key in keys:
                # Check if this translation has existing translations for non-default locales
                group = translations[key]
                has_existing_translations = False
                for locale in locales:
                    if locale != default_locale:
                        if locale in group.values and group.value_as_text(
                            group.values[locale]
                        ).strip():
                            has_existing_translations = True
                            break

                if key in outstanding_keys:
                    outstanding_keys_for_value.append(key)
                elif has_existing_translations:
                    existing_keys.append(key)

            # If we have both existing and outstanding, create matches
            if existing_keys and outstanding_keys_for_value:
                if default_value not in existing_to_outstanding_matches:
                    existing_to_outstanding_matches[default_value] = []
                for outstanding_key in outstanding_keys_for_value:
                    for existing_key in existing_keys:
                        existing_to_outstanding_matches[default_value].append((existing_key, outstanding_key))

            # If we have multiple outstanding with same value, track them
            if len(outstanding_keys_for_value) > 1:
                outstanding_duplicates[default_value] = outstanding_keys_for_value

    return existing_to_outstanding_matches, outstanding_duplicates


def ask_combine_duplicates(parent, existing_to_outstanding_count, outstanding_duplicates_count):
    """Ask user if they want to combine duplicate translations.

    Args:
        parent: Widget to parent the confirmation dialog on.
        existing_to_outstanding_count: Number of matches between existing and outstanding
        outstanding_duplicates_count: Number of duplicate groups in outstanding translations

    Returns:
        str: One of "yes", "no", "cancel". "cancel" means user closed the dialog (X/Escape)
             and the outstanding window should not open.
    """
    total_matches = existing_to_outstanding_count + outstanding_duplicates_count
    if total_matches == 0:
        return "no"

    message_parts = []
    if existing_to_outstanding_count > 0:
        message_parts.append(f"{existing_to_outstanding_count} match(es) between existing translations and outstanding translations")
    if outstanding_duplicates_count > 0:
        message_parts.append(f"{outstanding_duplicates_count} duplicate value group(s) in outstanding translations")

    message = (
        f"Found {total_matches} duplicate translation value(s) in the default locale:\n\n"
        f"{' | '.join(message_parts)}\n\n"
        "Would you like to combine these translations to avoid re-translation?\n\n"
        "- Yes: Pre-fill from existing translations and group duplicates (one row per value)\n"
        "- No: Open without combining; show all outstanding items\n"
        "- Cancel: Do not open Outstanding Translations"
    )

    msgbox = QMessageBox(parent)
    msgbox.setWindowTitle(_("Combine Duplicate Translations?"))
    msgbox.setText(message)
    msgbox.setStandardButtons(
        QMessageBox.StandardButton.Yes
        | QMessageBox.StandardButton.No
        | QMessageBox.StandardButton.Cancel
    )
    msgbox.setDefaultButton(QMessageBox.StandardButton.Yes)
    msgbox.setEscapeButton(QMessageBox.StandardButton.Cancel)

    reply = msgbox.exec()

    if reply == QMessageBox.StandardButton.Yes:
        return "yes"
    if reply == QMessageBox.StandardButton.No:
        return "no"
    # Cancel, or X, or Escape
    return "cancel"


class DuplicatePrefillState:
    """Owns outstanding-duplicate grouping and pending prefill-change bookkeeping.

    ``outstanding_duplicate_groups`` maps a representative outstanding key to every key that
    shares its default-locale value (only populated when the user chooses to combine
    duplicates); a table edit on the representative row is fanned out to every key in its group
    on save. Pending prefill changes are locale updates applied directly to the in-memory
    translations dict during load_data's pre-fill step -- they may reference keys not currently
    visible in the table, so they're tracked separately here and merged in on save.
    """

    def __init__(self):
        self.outstanding_duplicate_groups = {}
        self.last_combine_choice = "no"
        self._pending_prefill_changes_by_locale = {}

    def reset_for_load(self):
        """Reset per-load state; called at the start of every load_data() call."""
        self.outstanding_duplicate_groups = {}
        self._pending_prefill_changes_by_locale = {}

    def record_prefill_change(self, locale, key, value):
        per_locale = self._pending_prefill_changes_by_locale.setdefault(locale, {})
        per_locale[key] = value

    def iter_pending_prefill_changes(self):
        for locale, key_to_value in self._pending_prefill_changes_by_locale.items():
            yield locale, list(key_to_value.items())

    def pending_prefill_update_count(self):
        return sum(len(key_to_value) for key_to_value in self._pending_prefill_changes_by_locale.values())

    def clear_pending_prefill_changes(self):
        self._pending_prefill_changes_by_locale = {}

    def update_notice(self, notice_label):
        count = self.pending_prefill_update_count()
        if count <= 0:
            notice_label.hide()
            return
        notice_label.setText(
            _(
                "Pending duplicate-prefill updates: {count}. These may include keys not currently visible in the table and will be saved."
            ).format(count=count)
        )
        notice_label.show()
