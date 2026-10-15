"""utils/smoke_test.py and ``app.py --smoke-test``."""

import faulthandler
import importlib.util
import os
import subprocess
import sys

import pytest

from utils import app_paths, smoke_test

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HAS_PYQT6 = importlib.util.find_spec("PyQt6") is not None
_HAS_ARGOS = importlib.util.find_spec("argostranslate") is not None


@pytest.fixture
def scratch(monkeypatch, tmp_path):
    """This process in the smoke test's environment, as app.py sets it up."""
    for name, value in smoke_test.smoke_test_environment(str(tmp_path)).items():
        monkeypatch.setenv(name, value)
    return str(tmp_path)


@pytest.fixture
def smoke(scratch):
    return smoke_test.SmokeTest(scratch)


def _assert_passed(smoke):
    assert smoke.failures == []


# The environment

def test_environment_points_every_location_into_scratch(tmp_path):
    env = smoke_test.smoke_test_environment(str(tmp_path))
    for name in (*app_paths.OVERRIDE_ENVS, "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                 "XDG_DATA_HOME", "ARGOS_PACKAGES_DIR"):
        assert env[name].startswith(str(tmp_path) + os.sep), name
    assert env["QT_QPA_PLATFORM"] == "offscreen"
    assert env[smoke_test.SCRATCH_DIR_ENV] == str(tmp_path)


def test_isolate_environment_uses_the_given_scratch_dir(monkeypatch, tmp_path):
    for name in smoke_test.smoke_test_environment(str(tmp_path)):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(smoke_test.SCRATCH_DIR_ENV, str(tmp_path))
    assert smoke_test.isolate_environment() == str(tmp_path)
    assert smoke_test.is_isolated()
    assert app_paths.app_data_dir().startswith(str(tmp_path) + os.sep)


def test_not_isolated_when_a_variable_differs(scratch, monkeypatch, tmp_path):
    assert smoke_test.is_isolated()
    monkeypatch.setenv("PY_I18N_MANAGER_CONFIG_DIR", str(tmp_path.parent / "elsewhere"))
    assert not smoke_test.is_isolated()


def test_not_isolated_without_a_scratch_dir(monkeypatch):
    monkeypatch.delenv(smoke_test.SCRATCH_DIR_ENV, raising=False)
    assert not smoke_test.is_isolated()


# Reporting

def test_guarded_records_any_failure_with_its_name(smoke):
    smoke.guarded("raises", lambda: 1 / 0)
    smoke.guarded("exits", lambda: sys.exit(3))
    smoke.guarded("passes", lambda: None)
    assert smoke.failures == ["raises", "exits"]
    assert smoke.result() == 1


def test_result_is_zero_when_every_check_passes(smoke):
    smoke.check("one", True)
    assert smoke.result() == 0


# The checks, each in the smoke environment

def test_bundled_files(smoke):
    smoke.check_bundled_files()
    _assert_passed(smoke)


def test_default_config(smoke):
    smoke.check_default_config()
    _assert_passed(smoke)


def test_user_data_round_trips_in_scratch(smoke, scratch):
    smoke.check_user_data()
    _assert_passed(smoke)
    assert os.path.isfile(os.path.join(scratch, "app_data", "configs", "user_config.json"))


def test_user_data_refuses_outside_scratch(smoke, monkeypatch, tmp_path):
    monkeypatch.setenv(app_paths.DATA_DIR_ENV, str(tmp_path.parent / "not_scratch"))
    with pytest.raises(RuntimeError, match="Refusing"):
        smoke.check_user_data()


def test_gettext_project(smoke):
    smoke.check_gettext_project()
    _assert_passed(smoke)


def test_yaml(smoke):
    smoke.check_yaml()
    _assert_passed(smoke)


@pytest.mark.parametrize("is_build, fails", [(True, True), (False, False)])
def test_process_list_is_required_in_a_build_only(smoke, monkeypatch, is_build, fails):
    from utils import unpack_cleanup

    monkeypatch.setattr(app_paths, "IS_BUILD", is_build)
    monkeypatch.setattr(unpack_cleanup, "_running_executables", lambda: None)
    smoke.check_process_list()
    assert (smoke.failures == ["process list"]) is fails


def test_fault_log_check(smoke, monkeypatch, scratch):
    from utils import crash_log

    monkeypatch.setattr(crash_log, "_fault_log", None)
    # Leave the test process's own fault handling as it is.
    monkeypatch.setattr(faulthandler, "enable", lambda **kwargs: None)
    try:
        smoke.check_fault_log()
        _assert_passed(smoke)
        assert crash_log._fault_log.name.startswith(scratch + os.sep)
    finally:
        if crash_log._fault_log is not None:
            crash_log._fault_log.close()


# Checks that run a Qt event loop or load Argos's native libraries run in a
# fresh process, as the real smoke test does. In this process, earlier tests
# leave windows and timers that only an event loop processes, and native
# libraries loaded here would stay for the rest of the suite.

# argv[1:] names SmokeTest methods to run, in order.
_CHECKS_SCRIPT = """
import sys

from utils.smoke_test import isolate_environment

scratch = isolate_environment()

from ui.qt_message_log import install_qt_message_handler
from utils.smoke_test import SmokeTest

# As app.main() does before the smoke test.
install_qt_message_handler()
smoke = SmokeTest(scratch)
if "check_qt" in sys.argv[1:]:
    import app

    smoke.main_window_class = app.MainWindow
for name in sys.argv[1:]:
    smoke.guarded(name, getattr(smoke, name))
sys.exit(smoke.result())
"""


def _run_checks(tmp_path, *checks):
    env = dict(os.environ, **{smoke_test.SCRATCH_DIR_ENV: str(tmp_path)})
    result = subprocess.run(
        [sys.executable, "-c", _CHECKS_SCRIPT, *checks], cwd=REPO_ROOT, env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"exit code {result.returncode}\n{output}"
    assert "smoke test passed" in output


@pytest.mark.skipif(not (_HAS_PYQT6 and _HAS_ARGOS), reason="PyQt6 or argostranslate not installed")
def test_argos(tmp_path):
    _run_checks(tmp_path, "check_argos")


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed")
def test_qt_worker_thread_and_mo_compilation(tmp_path):
    # In run_smoke_test's order: the project and its POT come first.
    _run_checks(tmp_path, "check_gettext_project", "check_qt_thread")


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed")
def test_qt_main_window(tmp_path):
    _run_checks(tmp_path, "check_qt")


@pytest.mark.skipif(not _HAS_PYQT6, reason="PyQt6 not installed")
def test_app_refuses_the_smoke_test_without_isolation():
    import app

    assert not smoke_test.is_isolated()
    assert app._smoke_test() == 1


# End to end

@pytest.mark.skipif(not (_HAS_PYQT6 and _HAS_ARGOS), reason="PyQt6 or argostranslate not installed")
def test_app_smoke_test_passes_from_outside_the_repo(tmp_path):
    """The run build_exe.py makes, against the checkout: from another directory,
    with the scratch dir given."""
    env = dict(os.environ, **{smoke_test.SCRATCH_DIR_ENV: str(tmp_path / "scratch")})
    os.makedirs(env[smoke_test.SCRATCH_DIR_ENV])
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "app.py"), "--smoke-test"], cwd=str(tmp_path),
        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "smoke test passed" in output
    assert not os.path.exists(tmp_path / "configs"), "wrote relative to the working directory"
