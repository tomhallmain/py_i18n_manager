"""Helpers and Nuitka arguments of build_exe.py, loaded by file path; nothing
is installed or compiled."""

import importlib.util
import os
import sys

import pytest

from utils import app_paths, smoke_test

_BUILD_EXE = app_paths.resource_path("build_exe.py")

BUILD_ID = "20261015-120000"


@pytest.fixture(scope="module")
def build_exe():
    spec = importlib.util.spec_from_file_location("build_exe_under_test", _BUILD_EXE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(build_exe):
    return build_exe._common_args("I18nManager.exe", "i18n-manager", "1.2.3", BUILD_ID)


def test_common_args(build_exe):
    args = _args(build_exe)
    assert "--onefile" in args and "--standalone" not in args
    assert "--output-filename=I18nManager.exe" in args
    assert "--product-name=i18n Translation Manager" in args
    assert "--product-version=1.2.3" in args
    assert "--file-version=1.2.3" in args
    assert any(BUILD_ID in a for a in args if a.startswith("--file-description="))
    assert f"--include-data-files={build_exe.BUILD_INFO_PATH}=build_info.json" in args
    assert "--include-package-data=babel" in args


def test_bundled_files_are_where_resource_path_looks(build_exe):
    args = _args(build_exe)
    for relative in build_exe.DATA_FILES:
        assert f"--include-data-files={relative}={relative}" in args
        assert os.path.isfile(app_paths.resource_path(relative)), relative
    for parts in (("VERSION",), ("configs", "default_config.json"), ("assets", "icon.svg")):
        assert os.path.join(*parts) in build_exe.DATA_FILES


def test_build_unpacks_to_its_own_folder_in_the_app_data_dir(build_exe):
    spec = build_exe._pop_option(_args(build_exe), "--onefile-tempdir-spec")
    assert spec == f"{{HOME}}/.i18n_manager/unpacked/i18n-manager-{BUILD_ID}"


def test_unpack_spec_matches_the_app_data_dir(build_exe, monkeypatch):
    monkeypatch.delenv(app_paths.DATA_DIR_ENV, raising=False)
    expected = build_exe.APP_DATA_SPEC.replace("{HOME}", os.path.expanduser("~"))
    assert os.path.normpath(expected) == os.path.normpath(app_paths.default_app_data_dir())


def test_locale_ships_compiled_catalogs_only(build_exe):
    files = build_exe._locale_files()
    assert files
    assert all(f.endswith(".mo") for f in files)
    args = _args(build_exe)
    for f in files:
        assert f"--include-data-files={f}={f}" in args
    assert not any(a.endswith((".po", ".pot")) for a in args)


def test_locale_files_are_where_translations_look(build_exe):
    from utils.translations import I18N

    for f in build_exe._locale_files():
        assert os.path.isfile(os.path.join(os.path.dirname(I18N.localedir), f))


def test_entry_scripts_exist(build_exe):
    for _base, entry, _prefix, _target_args in build_exe.TARGETS:
        assert os.path.isfile(os.path.join(build_exe.REPO_ROOT, entry))


def test_gui_target_uses_the_pyqt6_plugin(build_exe):
    args = build_exe._gui_args()
    assert "--enable-plugin=pyqt6" in args
    assert not any("pyside6" in a.lower() for a in args)


def test_windows_icon(build_exe):
    # Only Windows executables carry an icon; sys.platform is left alone here.
    has_icon = f"--windows-icon-from-ico={build_exe.ICON_ICO}" in _args(build_exe)
    assert has_icon == (sys.platform == "win32")


@pytest.mark.parametrize("packages, expected", [
    ({"torch": "2.4.0"}, ["--module-parameter=torch-disable-jit=yes", "--include-distribution-metadata=torch"]),
    ({"torch": None}, []),
    ({}, []),
])
def test_argos_args_follow_the_installed_packages(build_exe, packages, expected):
    assert build_exe._argos_args(packages) == expected


@pytest.mark.parametrize("version_info, ok", [((3, 11, 11), True), ((3, 12, 1), False), ((3, 10, 4), False)])
def test_python_version_check(build_exe, version_info, ok):
    if ok:
        build_exe._check_python(version_info)
    else:
        with pytest.raises(SystemExit):
            build_exe._check_python(version_info)


def test_app_version_is_numeric(build_exe):
    assert build_exe._app_version().replace(".", "").isdigit()


def test_bad_version_stops_the_build(build_exe, monkeypatch, tmp_path):
    (tmp_path / build_exe.VERSION_FILE).write_text("1.0-beta\n", encoding="utf-8")
    monkeypatch.setattr(build_exe, "REPO_ROOT", str(tmp_path))
    with pytest.raises(SystemExit):
        build_exe._app_version()


def test_version_module_loads_without_the_app(build_exe):
    module = build_exe._version_module()
    assert callable(module["source_state"])
    assert module["VERSION_FILE"] == build_exe.VERSION_FILE
    assert module["BUILD_INFO_FILE"] == os.path.basename(build_exe.BUILD_INFO_PATH)


def test_smoke_test_env_is_the_apps_own(build_exe, monkeypatch, tmp_path):
    monkeypatch.setenv("PY_I18N_MANAGER_CONFIG_DIR", "/real/configs")
    env = build_exe._smoke_test_env(str(tmp_path))
    expected = smoke_test.smoke_test_environment(str(tmp_path))
    for name, value in expected.items():
        assert env[name] == value, name


def test_copy_to_dist_replaces_a_folder_build(build_exe, monkeypatch, tmp_path):
    build_dir, dist_dir = tmp_path / "build", tmp_path / "dist"
    build_dir.mkdir()
    (build_dir / "I18nManager").write_bytes(b"exe")
    (dist_dir / "I18nManager").mkdir(parents=True)
    monkeypatch.setattr(build_exe, "BUILD_DIR", str(build_dir))
    monkeypatch.setattr(build_exe, "DIST_DIR", str(dist_dir))
    path = build_exe._copy_to_dist("I18nManager")
    assert os.path.isfile(path)


def test_memory_wait_plugin_is_passed_when_found(build_exe):
    args = build_exe._common_args("I18nManager.exe", "i18n-manager", "1.2.3", BUILD_ID, "/plugins/wait.py")
    assert build_exe._pop_option(args, "--user-plugin") == "/plugins/wait.py"
    assert build_exe._pop_option(_args(build_exe), "--user-plugin") is None


class TestMemoryWait:
    @staticmethod
    def _no_tool(build_exe, monkeypatch, tools=None):
        """No variable, *tools* ({command: path}) as what shutil.which finds."""
        monkeypatch.delenv(build_exe.MEMORY_WAIT_PLUGIN_ENV, raising=False)
        monkeypatch.setattr(build_exe.shutil, "which", lambda name: (tools or {}).get(name))

    def test_the_variable_names_the_plugin(self, build_exe, monkeypatch, tmp_path):
        plugin = tmp_path / "nuitka_memory_wait.py"
        plugin.write_text("", encoding="utf-8")
        self._no_tool(build_exe, monkeypatch)
        monkeypatch.setenv(build_exe.MEMORY_WAIT_PLUGIN_ENV, str(plugin))
        assert build_exe._memory_wait_plugin() == str(plugin)

    def test_an_installed_tool_names_the_plugin(self, build_exe, monkeypatch, tmp_path):
        import subprocess

        plugin = tmp_path / "nuitka_memory_wait.py"
        plugin.write_text("", encoding="utf-8")
        self._no_tool(build_exe, monkeypatch, tools={"app-release": "/bin/app-release"})
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=f"{plugin}\n", stderr="")

        monkeypatch.setattr(build_exe.subprocess, "run", fake_run)
        assert build_exe._memory_wait_plugin() == str(plugin)
        assert calls == [["/bin/app-release", "--memory-wait-plugin"]]

    def test_no_plugin_anywhere_builds_without_it(self, build_exe, monkeypatch, caplog):
        self._no_tool(build_exe, monkeypatch)
        with caplog.at_level("WARNING", logger="build_exe"):
            assert build_exe._memory_wait_plugin() is None
        assert any("app-release" in message for message in caplog.messages)


def test_min_free_memory_reaches_nuitka(build_exe, monkeypatch):
    monkeypatch.delenv(build_exe.MIN_FREE_MEMORY_ENV, raising=False)
    assert build_exe._nuitka_env("12")[build_exe.MIN_FREE_MEMORY_ENV] == "12"
    assert build_exe.MIN_FREE_MEMORY_ENV not in build_exe._nuitka_env(None)


@pytest.mark.parametrize("value", ["0", "12", "2.5"])
def test_min_free_memory_accepts_gib(build_exe, value):
    assert build_exe._min_free_memory(value) == value


@pytest.mark.parametrize("value", ["-1", "lots", ""])
def test_min_free_memory_refuses_other_values(build_exe, value):
    with pytest.raises(SystemExit):
        build_exe._min_free_memory(value)


def test_min_free_memory_variable_is_the_one_the_plugin_reads(build_exe):
    # app-release's tests pin the plugin's side of this name.
    assert build_exe.MIN_FREE_MEMORY_ENV == "BUILD_MIN_FREE_MEMORY_GB"


@pytest.mark.parametrize("seconds, text", [
    (0, "0s"), (59.6, "1m 00s"), (125, "2m 05s"), (2 * 3600 + 5, "2h 00m 05s"),
])
def test_duration(build_exe, seconds, text):
    assert build_exe._duration(seconds) == text


def test_timed_logs_the_duration_of_a_step(build_exe, caplog):
    with caplog.at_level("INFO", logger="build_exe"):
        with build_exe._timed("Compiling"):
            pass
    assert caplog.messages[0] == "Compiling..."
    assert caplog.messages[-1].startswith("Compiling done in ")


def test_timed_logs_a_failed_step(build_exe, caplog):
    with caplog.at_level("INFO", logger="build_exe"):
        with pytest.raises(SystemExit):
            with build_exe._timed("Compiling"):
                raise SystemExit("broken")
    assert caplog.messages[-1].startswith("Compiling failed after ")


def test_build_requirements_include_the_app_and_nuitka():
    with open(app_paths.resource_path("requirements-build.txt"), "r", encoding="utf-8") as f:
        lines = [line.split("#")[0].strip() for line in f]
    assert "-r requirements.txt" in lines
    assert "nuitka==4.2.2" in lines
    assert "PyQt6==6.11.0" in lines
    assert "PyQt6-Qt6==6.11.2" in lines


def test_runtime_requirements_leave_out_test_tools():
    with open(app_paths.resource_path("requirements.txt"), "r", encoding="utf-8") as f:
        names = [line.split("#")[0].strip().split(">")[0].split("=")[0].lower() for line in f]
    assert "pytest" not in names
