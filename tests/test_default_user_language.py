"""UI language detection (Utils.get_default_user_language) and the import-time catalog load."""

import ctypes
import gettext
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from utils.utils import DEFAULT_UI_LANGUAGE, Utils

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def non_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.fixture
def fake_windows(monkeypatch):
    """Windows branch with a fake ``GetUserDefaultUILanguage``; returns the mock to configure."""
    monkeypatch.setattr(sys, "platform", "win32")
    windll = MagicMock()
    monkeypatch.setattr(ctypes, "windll", windll, raising=False)
    return windll.kernel32.GetUserDefaultUILanguage


class TestLangEnvironmentVariable:
    @pytest.mark.parametrize("lang, expected", [
        ("fr_FR.UTF-8", "fr"),
        ("de_DE", "de"),
        ("de.UTF-8", "de"),
        ("de_DE.UTF-8@euro", "de"),
        ("sr_RS@latin", "sr"),
        ("en", "en"),
    ])
    def test_language_part_is_extracted(self, monkeypatch, non_windows, lang, expected):
        monkeypatch.setenv("LANG", lang)
        assert Utils.get_default_user_language() == expected

    @pytest.mark.parametrize("lang", ["C.UTF-8", "C", "POSIX", "POSIX.UTF-8", "", "  "])
    def test_c_posix_and_empty_fall_back_to_default(self, monkeypatch, non_windows, lang):
        monkeypatch.setenv("LANG", lang)
        assert Utils.get_default_user_language() == DEFAULT_UI_LANGUAGE

    def test_unset_falls_back_to_default(self, monkeypatch, non_windows):
        monkeypatch.delenv("LANG", raising=False)
        assert Utils.get_default_user_language() == DEFAULT_UI_LANGUAGE


class TestWindowsUiLanguage:
    def test_ui_language_used_when_lang_unset(self, monkeypatch, fake_windows):
        monkeypatch.delenv("LANG", raising=False)
        fake_windows.return_value = 0x0407  # de_DE

        assert Utils.get_default_user_language() == "de"
        fake_windows.assert_called_once_with()

    def test_ui_language_used_for_c_locale(self, monkeypatch, fake_windows):
        monkeypatch.setenv("LANG", "C.UTF-8")
        fake_windows.return_value = 0x040C  # fr_FR

        assert Utils.get_default_user_language() == "fr"

    def test_unknown_language_id_falls_back_to_default(self, monkeypatch, fake_windows):
        monkeypatch.delenv("LANG", raising=False)
        fake_windows.return_value = 0xFFFF

        assert Utils.get_default_user_language() == DEFAULT_UI_LANGUAGE

    def test_lang_takes_precedence(self, monkeypatch, fake_windows):
        monkeypatch.setenv("LANG", "it_IT.UTF-8")

        assert Utils.get_default_user_language() == "it"
        fake_windows.assert_not_called()


class TestTranslationsImport:
    """``utils.translations`` loads its catalog at import time, so each case runs in a fresh
    interpreter; reloading it in-process would leave other modules holding a stale ``I18N``."""

    @staticmethod
    def _run_after_import(lang: str, code: str) -> list[str]:
        """Import ``utils.translations`` with ``LANG=lang`` in a fresh interpreter, run ``code``
        (which prints one value per line) and return the printed lines."""
        env = dict(os.environ, LANG=lang)
        result = subprocess.run(
            [sys.executable, "-c", f"import builtins\nfrom utils.translations import I18N\n{code}"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.splitlines()

    def test_c_locale_does_not_break_import(self):
        # Resolves to the default (or, on Windows, the user's UI language); must not raise.
        self._run_after_import("C.UTF-8", "print(I18N.locale)")

    def test_language_without_catalog_falls_back_to_msgids(self):
        assert not (REPO_ROOT / "locale" / "ja").exists()
        locale, translated = self._run_after_import(
            "ja_JP.UTF-8", "print(I18N.locale); print(I18N._('Error'))"
        )
        assert locale == "ja"
        assert translated == "Error"

    def test_detected_language_is_installed(self):
        """``I18N.locale``, ``I18N._`` and builtins ``_`` all follow the detected language."""
        expected = gettext.translation(
            "base", str(REPO_ROOT / "locale"), languages=["fr"]
        ).gettext("Error")
        locale, via_i18n, via_builtins = self._run_after_import(
            "fr_FR.UTF-8",
            "print(I18N.locale); print(I18N._('Error')); print(builtins._('Error'))",
        )
        assert locale == "fr"
        assert via_i18n == expected
        assert via_builtins == expected


class TestLlmResponseLanguage:
    """``response_language_name_for_prompts`` names the language of ``I18N.locale``, which the
    import-time install sets from the detected UI language (see ``TestTranslationsImport``)."""

    @pytest.mark.parametrize("locale, expected", [
        ("de", "German"),
        ("fr", "French"),
        ("pt_BR", "Portuguese"),
        ("en", "English"),
        ("xx", "xx"),
    ])
    def test_language_name_follows_installed_locale(self, monkeypatch, locale, expected):
        from i18n.llm_catalog_review import response_language_name_for_prompts
        from utils.translations import I18N

        monkeypatch.setattr(I18N, "locale", locale)
        assert response_language_name_for_prompts() == expected
