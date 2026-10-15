"""External tools started with output redirected get an explicit stdin and no
console window (utils/subprocess_flags.py): a windowed Windows build can
have invalid standard handles, and each console program would flash a
window of its own."""

import subprocess
import sys
from unittest.mock import Mock

import pytest

from i18n.bulk_pot_analyzer import BulkPotAnalyzer, GitStatus
from i18n.ruby import i18n_tasks_sync
from i18n.ruby.ruby_i18n_manager import RubyI18NManager
from utils.subprocess_flags import NO_CONSOLE_WINDOW


@pytest.fixture
def run_calls(monkeypatch):
    """Replaces subprocess.run for the test; returns the kwargs of each call."""
    calls = []

    def run(command, **kwargs):
        calls.append(kwargs)
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def _assert_detached(kwargs):
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["creationflags"] == NO_CONSOLE_WINDOW


def test_no_console_window_is_zero_off_windows():
    if sys.platform != "win32":
        assert NO_CONSOLE_WINDOW == 0
    else:
        assert NO_CONSOLE_WINDOW == subprocess.CREATE_NO_WINDOW


def test_git_status_in_bulk_analysis(run_calls, tmp_path):
    (tmp_path / ".git").mkdir()
    analyzer = BulkPotAnalyzer(settings_manager=Mock())
    assert analyzer._get_git_status(str(tmp_path)) == GitStatus.CLEAN
    _assert_detached(run_calls[0])


@pytest.mark.parametrize("runner", [i18n_tasks_sync.run_i18n_tasks_missing, i18n_tasks_sync.run_i18n_tasks_unused])
def test_i18n_tasks_report_commands(run_calls, monkeypatch, tmp_path, runner):
    monkeypatch.setattr(i18n_tasks_sync, "_resolve_bundle_executable", lambda: "bundle")
    runner(str(tmp_path))
    _assert_detached(run_calls[0])


def test_i18n_tasks_add_missing(run_calls, monkeypatch, tmp_path):
    # Only the subprocess call is under test, so skip the manager's project loading.
    manager = RubyI18NManager.__new__(RubyI18NManager)
    monkeypatch.setattr(manager, "_resolve_bundle_executable", lambda: "bundle", raising=False)
    monkeypatch.setattr(manager, "_get_project_root", lambda: str(tmp_path), raising=False)
    manager._run_i18n_tasks_add_missing()
    _assert_detached(run_calls[0])
