"""TSV/Markdown export of outstanding translation rows for the Outstanding Items window.

Extracted as-is from OutstandingItemsWindow.export_outstanding_to_tsv and its formatting
helpers.
"""

from __future__ import annotations

import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from utils.globals import config_manager
from utils.logging_setup import get_logger
from utils.translations import I18N

_ = I18N._

logger = get_logger(__name__)


def sanitize_export_text(value):
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def truncate_export_text(value, max_len=280):
    text = str(value or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def escape_markdown(value):
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r", " ").replace("\n", " ")
    return text


def format_locale_list(locales_set, locales):
    """Format locale sets in the current locale order."""
    if not locales_set:
        return ""
    ordered = [loc for loc in locales if loc in locales_set]
    # Include any unexpected locales not present in `locales`
    extras = sorted([loc for loc in locales_set if loc not in locales])
    return ", ".join(ordered + extras)


def format_locale_value_pairs(group, locales_set, locales):
    if not locales_set:
        return ""
    ordered = [loc for loc in locales if loc in locales_set]
    extras = sorted([loc for loc in locales_set if loc not in locales])
    values = []
    for locale in ordered + extras:
        text = group.get_translation_as_text(locale)
        values.append(f"{locale}={sanitize_export_text(text)}")
    return " | ".join(values)


def export_outstanding_to_tsv(parent, current_invalid_groups, project_path, locales):
    """Export the current outstanding rows and invalid locale buckets to a TSV file.

    Args:
        parent: Widget to parent dialogs on.
        current_invalid_groups: ``{key: (invalid_locales, group)}`` as built by
            ``OutstandingItemsWindow.load_data``.
        project_path: Current project directory; used as the save dialog's default directory.
        locales: Ordered list of locale codes, used to order multi-locale cells.
    """
    if not current_invalid_groups:
        QMessageBox.information(parent, _("No Data"), _("There are no outstanding rows to export."))
        return

    default_locale = config_manager.get('translation.default_locale', 'en')
    headers = [
        "Translation Key",
        "Default Locale Value",
        "Defined without Error",
        "Missing",
        "Invalid Unicode",
        "Invalid Braces",
        "Invalid Leading Space",
        "Invalid Newline",
        "Invalid Character Set",
        "Invalid Locale Values",
    ]
    markdown_headers = [h for h in headers if h != "Invalid Locale Values"]

    lines = ["\t".join(headers)]
    markdown_rows = []
    markdown_details = []

    for _key, (invalid_locales, group) in current_invalid_groups.items():
        # Keep Invalid Unicode aligned with current outstanding UI behavior
        # where invalid indices are grouped as critical with unicode.
        invalid_unicode = set(invalid_locales.invalid_unicode_locales) | set(invalid_locales.invalid_index_locales)
        missing = set(invalid_locales.missing_locales)
        invalid_braces = set(invalid_locales.invalid_brace_locales)
        invalid_leading_space = set(invalid_locales.invalid_leading_space_locales)
        invalid_newline = set(invalid_locales.invalid_newline_locales)
        invalid_character_set = set(invalid_locales.invalid_character_set_locales)

        all_error_locales = (
            missing
            | invalid_unicode
            | invalid_braces
            | invalid_leading_space
            | invalid_newline
            | invalid_character_set
        )

        default_value = group.get_translation_as_text(default_locale)
        defined_without_error = set()
        for locale in locales:
            value = group.get_translation(locale)
            vt = group.value_as_text(value)
            if vt and vt.strip() and locale not in all_error_locales:
                defined_without_error.add(locale)
        # Default locale is often not in `locales` list from header filtering in this window.
        if default_value and default_value.strip() and default_locale not in all_error_locales:
            defined_without_error.add(default_locale)

        invalid_locale_values = format_locale_value_pairs(group, all_error_locales, locales)
        invalid_locale_values_tsv = truncate_export_text(invalid_locale_values)
        row_values = [
            group.key.msgid,
            default_value,
            format_locale_list(defined_without_error, locales),
            format_locale_list(missing, locales),
            format_locale_list(invalid_unicode, locales),
            format_locale_list(invalid_braces, locales),
            format_locale_list(invalid_leading_space, locales),
            format_locale_list(invalid_newline, locales),
            format_locale_list(invalid_character_set, locales),
            invalid_locale_values_tsv,
        ]
        # Keep TSV shape stable (no tabs/newlines in cell content)
        safe_values = [sanitize_export_text(v) for v in row_values]
        lines.append("\t".join(safe_values))

        markdown_rows.append(
            {
                "Translation Key": group.key.msgid,
                "Default Locale Value": default_value,
                "Defined without Error": format_locale_list(defined_without_error, locales),
                "Missing": format_locale_list(missing, locales),
                "Invalid Unicode": format_locale_list(invalid_unicode, locales),
                "Invalid Braces": format_locale_list(invalid_braces, locales),
                "Invalid Leading Space": format_locale_list(invalid_leading_space, locales),
                "Invalid Newline": format_locale_list(invalid_newline, locales),
                "Invalid Character Set": format_locale_list(invalid_character_set, locales),
            }
        )
        markdown_details.append(
            {
                "key": group.key.msgid,
                "default": default_value,
                "missing": missing,
                "invalid_unicode": invalid_unicode,
                "invalid_braces": invalid_braces,
                "invalid_leading_space": invalid_leading_space,
                "invalid_newline": invalid_newline,
                "invalid_character_set": invalid_character_set,
                "group": group,
            }
        )

    default_name = os.path.join(project_path or "", "outstanding_translation_keys.tsv")
    dialog_result = QFileDialog.getSaveFileName(
        parent,
        _("Export Outstanding TSV"),
        default_name,
        _("TSV Files (*.tsv);;All Files (*)"),
    )
    file_path = dialog_result[0]
    if not file_path:
        return

    try:
        with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write("\n".join(lines) + "\n")

        md_path = os.path.splitext(file_path)[0] + ".md"
        with open(md_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Outstanding Translation Export\n\n")
            f.write("| " + " | ".join(markdown_headers) + " |\n")
            f.write("|" + "|".join(["---"] * len(markdown_headers)) + "|\n")
            for row in markdown_rows:
                f.write(
                    "| "
                    + " | ".join(
                        escape_markdown(row.get(header, ""))
                        for header in markdown_headers
                        )
                    + " |\n"
                )
            f.write("\n## Invalid Issue Details\n\n")
            for detail in markdown_details:
                f.write(f"### {escape_markdown(detail['key'])}\n")
                f.write(f"- Default locale value: {escape_markdown(detail['default'])}\n")
                category_rows = [
                    ("Missing locales", detail["missing"]),
                    ("Invalid Unicode locales", detail["invalid_unicode"]),
                    ("Invalid braces locales", detail["invalid_braces"]),
                    ("Invalid leading-space locales", detail["invalid_leading_space"]),
                    ("Invalid newline locales", detail["invalid_newline"]),
                    ("Invalid character-set locales", detail["invalid_character_set"]),
                ]
                for label, locales_set in category_rows:
                    if locales_set:
                        f.write(
                            f"- {label}: {escape_markdown(format_locale_list(locales_set, locales))}\n"
                        )
                f.write(
                    f"- Invalid locale values: {escape_markdown(format_locale_value_pairs(detail['group'], detail['missing'] | detail['invalid_unicode'] | detail['invalid_braces'] | detail['invalid_leading_space'] | detail['invalid_newline'] | detail['invalid_character_set'], locales))}\n\n"
                )

        QMessageBox.information(
            parent,
            _("Export Complete"),
            _("Exported {count} outstanding key(s) to:\n{path}\n\nMarkdown companion:\n{md_path}").format(
                count=len(current_invalid_groups),
                path=file_path,
                md_path=md_path,
            ),
        )
    except Exception as e:
        logger.error(f"Failed to export outstanding TSV: {e}")
        QMessageBox.critical(
            parent,
            _("Export Failed"),
            _("Could not export TSV file:\n{error}").format(error=str(e)),
        )
