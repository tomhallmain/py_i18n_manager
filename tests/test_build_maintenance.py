"""utils/build_maintenance.py with the cleanup and drift check stubbed."""

import pytest

from utils import app_paths, build_maintenance, unpack_cleanup, version


@pytest.fixture
def stubs(monkeypatch):
    """Counts cleanup calls; the drift result is set through the returned dict."""
    state = {"cleanups": 0, "drift": None}

    def cleanup():
        state["cleanups"] += 1

    monkeypatch.setattr(unpack_cleanup, "remove_stale_unpack_dirs", cleanup)
    monkeypatch.setattr(version, "source_drift", lambda: state["drift"])
    return state


def test_cleans_up_old_folders(stubs):
    build_maintenance.run_build_maintenance()
    assert stubs["cleanups"] == 1


def test_reports_drift(stubs):
    stubs["drift"] = (True, "behind by 2 commits")
    reported = []
    build_maintenance.run_build_maintenance(on_drift=reported.append)
    assert reported == ["behind by 2 commits"]


@pytest.mark.parametrize("drift", [None, (False, "matches")])
def test_does_not_report_a_match_or_a_checkout(stubs, drift):
    stubs["drift"] = drift
    reported = []
    build_maintenance.run_build_maintenance(on_drift=reported.append)
    assert reported == []


def test_a_failed_cleanup_still_checks_drift(stubs, monkeypatch):
    def broken():
        raise OSError("disk gone")

    monkeypatch.setattr(unpack_cleanup, "remove_stale_unpack_dirs", broken)
    stubs["drift"] = (True, "differs")
    reported = []
    build_maintenance.run_build_maintenance(on_drift=reported.append)
    assert reported == ["differs"]


def test_failures_are_logged_not_raised(stubs, monkeypatch):
    def broken():
        raise RuntimeError("git exploded")

    monkeypatch.setattr(version, "source_drift", broken)
    build_maintenance.run_build_maintenance()


def test_starts_no_thread_in_a_checkout(monkeypatch):
    monkeypatch.setattr(app_paths, "IS_BUILD", False)
    assert build_maintenance.start_build_maintenance() is None


def test_runs_on_a_daemon_thread_in_a_build(stubs, monkeypatch):
    monkeypatch.setattr(app_paths, "IS_BUILD", True)
    thread = build_maintenance.start_build_maintenance()
    thread.join(5)
    assert thread.daemon
    assert stubs["cleanups"] == 1
