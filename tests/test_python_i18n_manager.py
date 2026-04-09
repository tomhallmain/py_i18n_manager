"""Integration tests for PythonI18NManager using real temp-file fixtures."""

import os
import tempfile
import textwrap

from i18n.python.python_i18n_manager import PythonI18NManager
from i18n.translation_manager_results import TranslationAction

# Minimal valid POT / PO content
_POT_CONTENT = textwrap.dedent("""\
    msgid ""
    msgstr ""
    "Content-Type: text/plain; charset=UTF-8\\n"

    msgid "Hello"
    msgstr ""

    msgid "Item {0} of {1}"
    msgstr ""
""")

_PO_FR_CONTENT = textwrap.dedent("""\
    msgid ""
    msgstr ""
    "Content-Type: text/plain; charset=UTF-8\\n"
    "Language: fr\\n"

    msgid "Hello"
    msgstr "Bonjour"

    msgid "Item {0} of {1}"
    msgstr "Élément {0} sur {1}"
""")


def _build_python_project(root: str) -> str:
    """Create a minimal Python gettext project under *root* and return the root."""
    locale_dir = os.path.join(root, "locale")
    os.makedirs(locale_dir)

    # POT file
    with open(os.path.join(locale_dir, "base.pot"), "w", encoding="utf-8") as f:
        f.write(_POT_CONTENT)

    # FR PO file
    fr_lc = os.path.join(locale_dir, "fr", "LC_MESSAGES")
    os.makedirs(fr_lc)
    with open(os.path.join(fr_lc, "base.po"), "w", encoding="utf-8") as f:
        f.write(_PO_FR_CONTENT)

    return root


class TestPythonI18NManagerLocaleDirectory:
    def test_detects_locale_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locale"))
            mgr = PythonI18NManager(tmpdir)
            assert mgr._locale_dir == "locale"

    def test_detects_locales_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locales"))
            mgr = PythonI18NManager(tmpdir)
            assert mgr._locale_dir == "locales"

    def test_defaults_to_locale_when_neither_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PythonI18NManager(tmpdir)
            assert mgr._locale_dir == "locale"

    def test_prefers_locale_when_both_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locale"))
            os.makedirs(os.path.join(tmpdir, "locales"))
            mgr = PythonI18NManager(tmpdir)
            assert mgr._locale_dir == "locale"


class TestPythonI18NManagerSetDirectory:
    def test_set_directory_resets_translations(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = PythonI18NManager(d1)
            from i18n.translation_group import TranslationKey, TranslationGroup
            mgr.translations[TranslationKey("x")] = TranslationGroup("x")
            mgr.set_directory(d2)
            assert mgr.translations == {}

    def test_set_directory_resets_locales_and_written(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = PythonI18NManager(d1)
            mgr.locales = ["en", "fr"]
            mgr.written_locales = {"en"}
            mgr.set_directory(d2)
            assert mgr.locales == []
            assert mgr.written_locales == set()

    def test_set_directory_updates_locale_dir(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            mgr = PythonI18NManager(d1)
            os.makedirs(os.path.join(d2, "locales"))
            mgr.set_directory(d2)
            assert mgr._locale_dir == "locales"


class TestPythonI18NManagerFilePaths:
    def test_get_pot_file_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PythonI18NManager(tmpdir)
            expected = os.path.join(tmpdir, "locale", "base.pot")
            assert os.path.normpath(mgr.get_pot_file_path()) == os.path.normpath(expected)

    def test_get_po_file_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PythonI18NManager(tmpdir)
            expected = os.path.join(tmpdir, "locale", "fr", "LC_MESSAGES", "base.po")
            assert os.path.normpath(mgr.get_po_file_path("fr")) == os.path.normpath(expected)


class TestPythonI18NManagerGatherFiles:
    def test_gather_files_finds_pot_and_po(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            pot, po_files = mgr.gather_files()
            assert pot.endswith("base.pot")
            assert len(po_files) == 1
            assert po_files[0].endswith("base.po")

    def test_gather_files_raises_when_no_pot(self):
        import pytest
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locale"))
            mgr = PythonI18NManager(tmpdir)
            with pytest.raises(Exception):
                mgr.gather_files()


class TestPythonI18NManagerParsing:
    def test_parse_pot_populates_translations_as_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            pot_path = os.path.join(tmpdir, "locale", "base.pot")
            mgr._parse_pot(pot_path)
            msgids = [k.msgid for k in mgr.translations]
            assert "Hello" in msgids
            assert "Item {0} of {1}" in msgids

    def test_parse_pot_marks_groups_as_in_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            pot_path = os.path.join(tmpdir, "locale", "base.pot")
            mgr._parse_pot(pot_path)
            for group in mgr.translations.values():
                assert group.is_in_base

    def test_parse_po_adds_locale_translation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            pot_path = os.path.join(tmpdir, "locale", "base.pot")
            po_path = os.path.join(tmpdir, "locale", "fr", "LC_MESSAGES", "base.po")
            mgr._parse_pot(pot_path)
            mgr._parse_po(po_path, "fr")
            from i18n.translation_group import TranslationKey
            hello_group = mgr.translations[TranslationKey("Hello")]
            assert hello_group.get_translation("fr") == "Bonjour"

    def test_fill_translations_populates_locales_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            pot_path = os.path.join(tmpdir, "locale", "base.pot")
            mgr._parse_pot(pot_path)
            _, po_files = mgr.gather_files()
            mgr._fill_translations(po_files)
            assert "fr" in mgr.locales


class TestPythonI18NManagerManageTranslations:
    def test_check_status_returns_successful_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert result.action_successful
            assert result.error_message is None

    def test_check_status_populates_total_strings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert result.total_strings > 0

    def test_check_status_detects_fr_locale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert "fr" in mgr.locales

    def test_check_status_sets_latest_mtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            assert result.latest_translation_file_mtime is not None

    def test_check_status_on_empty_project_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "locale"))
            mgr = PythonI18NManager(tmpdir)
            # No POT file → gather_files raises, manage_translations catches it
            result = mgr.manage_translations(TranslationAction.CHECK_STATUS)
            # Should return a result (even on failure), not propagate the exception
            assert result is not None

    def test_list_translation_file_paths_includes_pot_and_po(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            paths = mgr.list_translation_file_paths()
            assert any(p.endswith(".pot") for p in paths)
            assert any(p.endswith(".po") for p in paths)


class TestPythonI18NManagerWritePOFile:
    def test_write_po_file_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            po_path = mgr.get_po_file_path("fr")
            mgr.write_po_file(po_path, "fr")
            assert os.path.exists(po_path)

    def test_write_po_file_contains_translation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _build_python_project(tmpdir)
            mgr = PythonI18NManager(tmpdir)
            mgr.manage_translations(TranslationAction.CHECK_STATUS)
            po_path = mgr.get_po_file_path("fr")
            mgr.write_po_file(po_path, "fr")
            with open(po_path, encoding="utf-8") as f:
                content = f.read()
            assert "Bonjour" in content
