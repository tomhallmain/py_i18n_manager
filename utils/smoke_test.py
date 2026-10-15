"""``app.py --smoke-test``: checks that a built executable works, without a window.

``isolate_environment()`` runs before any other app import, because the
loggers, the config singleton and the cache resolve their paths from the
environment as modules load. It points every per-user location at a scratch
directory, so the run touches none of the user's settings, config, cache,
logs or Argos models. Imports nothing from the app at load time:
build_exe.py runs this file on its own to build the same environment.
"""

#: Set to keep the scratch directory at a known place (build_exe.py does).
SCRATCH_DIR_ENV = "PY_I18N_MANAGER_SMOKE_DIR"

#: The string the scratch gettext project marks for translation, and its German.
PROBE_MSGID = "Smoke test greeting"
PROBE_MSGSTR_DE = "Gruß aus dem Rauchtest"


def smoke_test_environment(scratch: str) -> dict:
    """Every variable the run sets, all pointing into *scratch*. Assigned over
    the inherited values, so a variable exported in the developer's shell
    cannot reach the real locations."""
    import os

    home = os.path.join(scratch, "home")
    data = os.path.join(scratch, "app_data")
    return {
        "HOME": home,
        "USERPROFILE": home,
        "APPDATA": os.path.join(scratch, "appdata"),
        "LOCALAPPDATA": os.path.join(scratch, "localappdata"),
        "XDG_DATA_HOME": os.path.join(scratch, "xdg_data"),
        "XDG_CONFIG_HOME": os.path.join(scratch, "xdg_config"),
        "XDG_CACHE_HOME": os.path.join(scratch, "xdg_cache"),
        "PY_I18N_MANAGER_DATA_DIR": data,
        "PY_I18N_MANAGER_SETTINGS_PATH": os.path.join(data, "settings.json"),
        "PY_I18N_MANAGER_APP_INFO_CACHE_PATH": os.path.join(data, "app_info_cache.json"),
        "PY_I18N_MANAGER_CONFIG_DIR": os.path.join(data, "configs"),
        "ARGOS_PACKAGES_DIR": os.path.join(scratch, "argos_packages"),
        "QT_QPA_PLATFORM": "offscreen",
        SCRATCH_DIR_ENV: scratch,
    }


def isolate_environment() -> str:
    """Apply smoke_test_environment() to this process; returns the scratch
    directory. SCRATCH_DIR_ENV names it, otherwise a new temp directory is used."""
    import os
    import tempfile

    scratch = os.environ.get(SCRATCH_DIR_ENV) or tempfile.mkdtemp(prefix="i18n-manager-smoke-")
    os.environ.update(smoke_test_environment(scratch))
    return scratch


def is_isolated() -> bool:
    """Whether this process runs in the environment isolate_environment() sets."""
    import os

    scratch = os.environ.get(SCRATCH_DIR_ENV)
    return bool(scratch) and all(
        os.environ.get(name) == value for name, value in smoke_test_environment(scratch).items())


class SmokeTest:
    """The checks, each logged on one line and run under guarded(), so one
    failure still lets the others report."""

    def __init__(self, scratch: str, main_window_class=None):
        from utils.logging_setup import get_logger

        self.scratch = scratch
        # app.MainWindow, passed in by app.main(): in a build app.py is the
        # compiled __main__ module, which `import app` would not find.
        self.main_window_class = main_window_class
        self.failures = []
        self._app = None
        self.logger = get_logger("smoke_test")

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.logger.info(f"smoke test: {name}: {'ok' if ok else 'FAILED'} {detail}".rstrip())
        if not ok:
            self.failures.append(name)

    def guarded(self, name: str, func) -> None:
        """Run the check *func*; anything it raises, SystemExit included (a
        bundled package without metadata exits the process on a version
        probe), fails *name* with its full traceback."""
        import traceback

        try:
            func()
        except BaseException:
            self.logger.error(f"smoke test: {name}: FAILED\n{traceback.format_exc()}")
            self.failures.append(name)

    def result(self) -> int:
        """Exit code: 0 if every check passed."""
        if self.failures:
            self.logger.error(f"smoke test failed: {', '.join(self.failures)}")
            return 1
        self.logger.info("smoke test passed")
        return 0

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def check_bundled_files(self) -> None:
        import glob
        import os

        from utils.app_paths import IS_BUILD, resource_path
        from utils.translations import I18N
        from utils.version import VERSION_FILE, app_version, build_info

        catalogs = glob.glob(os.path.join(I18N.localedir, "*", "LC_MESSAGES", "base.mo"))
        self.check("locale", bool(catalogs), f"{len(catalogs)} catalog(s) in {I18N.localedir}")
        self.check("VERSION", os.path.isfile(resource_path(VERSION_FILE)), app_version())
        if IS_BUILD:
            recorded = build_info().get("version")
            self.check("build info", recorded == app_version(), f"records version {recorded}")
        else:
            self.logger.info("smoke test: build info: not checked in a source checkout")

    def check_default_config(self) -> None:
        from utils.config import ConfigManager

        config = ConfigManager()
        self.check("default config", config.default_config_path.is_file()
                   and bool(config.get("translation.llm_prompt_template")), str(config.default_config_path))

    def check_user_data(self) -> None:
        """Config, settings and cache saved to the scratch data dir and read back."""
        import os

        from utils.app_info_cache import AppInfoCache
        from utils.app_paths import app_data_dir
        from utils.config import ConfigManager
        from utils.settings_manager import SettingsManager

        data_dir = app_data_dir()
        if not os.path.abspath(data_dir).startswith(os.path.abspath(self.scratch) + os.sep):
            raise RuntimeError(f"Refusing to write outside the scratch directory: {data_dir}")

        ConfigManager().set("smoke_test.value", "round trip")
        self.check("user config", ConfigManager().get("smoke_test.value") == "round trip",
                   str(ConfigManager().user_config_path))

        # A project setting, not the last project: the main window (check_qt)
        # would open that and start a status task.
        project = os.path.join(self.scratch, "settings_project")
        saved = SettingsManager().save_project_setting(project, "smoke_test", "round trip")
        self.check("settings", saved and SettingsManager().get_project_setting(project, "smoke_test")
                   == "round trip", str(SettingsManager().settings_file))

        cache = AppInfoCache()
        cache.set("smoke_test", "round trip")
        cache.store()
        self.check("app info cache", AppInfoCache().get("smoke_test") == "round trip", AppInfoCache.JSON_LOC)

    def _gettext_project(self) -> str:
        """A scratch Python project: one source file marking PROBE_MSGID, and
        en and de catalogs, de with its translation."""
        import os

        project = os.path.join(self.scratch, "gettext_project")
        with_po = {
            "en": "",
            "de": f'\nmsgid "{PROBE_MSGID}"\nmsgstr "{PROBE_MSGSTR_DE}"\n',
        }
        for locale, entries in with_po.items():
            folder = os.path.join(project, "locale", locale, "LC_MESSAGES")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "base.po"), "w", encoding="utf-8") as f:
                f.write(f'msgid ""\nmsgstr ""\n"Language: {locale}\\n"\n'
                        f'"Content-Type: text/plain; charset=UTF-8\\n"\n{entries}')
        with open(os.path.join(project, "main.py"), "w", encoding="utf-8") as f:
            f.write(f'from gettext import gettext as _\n\nprint(_("{PROBE_MSGID}"))\n')
        return project

    def check_gettext_project(self) -> None:
        """Detection and POT generation: Babel's Python extractor, and its
        locale data (it dates the POT header)."""
        import os

        from i18n.i18n_manager import I18NManager
        from utils.globals import ProjectType
        from utils.project_detector import ProjectDetector

        project = self._gettext_project()
        detected = ProjectDetector.detect_project_type(project)
        self.check("project detection", detected == ProjectType.PYTHON, str(detected))

        # As the main window's base file action does: manage_translations()
        # needs an existing POT, and this project has none yet.
        manager = I18NManager(project)
        generated = manager.generate_pot_file()
        pot = os.path.join(project, "locale", "base.pot")
        text = ""
        if os.path.isfile(pot):
            with open(pot, "r", encoding="utf-8") as f:
                text = f.read()
        self.check("POT generation (Babel)", generated and f'msgid "{PROBE_MSGID}"' in text,
                   manager.get_last_generate_base_error() or "")

    def check_qt_thread(self) -> None:
        """A status check on a TranslationWorker (a QThread), its result
        delivered back here through a queued signal, as the main window gets
        every task's result; then MO compilation, read back with gettext.
        Nuitka's PyQt6 plugin warns that Qt threading may not work."""
        import gettext
        import os

        from PyQt6.QtCore import QEventLoop, QTimer

        from i18n.translation_manager_results import TranslationAction
        from workers.translation_worker import TranslationWorker

        self._qt_app()
        project = os.path.join(self.scratch, "gettext_project")
        if not os.path.isdir(project):
            project = self._gettext_project()
        results = []
        loop = QEventLoop()

        def finished(result):
            results.append(result)
            loop.quit()

        worker = TranslationWorker(project, TranslationAction.CHECK_STATUS)
        worker.finished.connect(finished)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(30000)
        worker.start()
        loop.exec()
        timeout.stop()
        stopped = worker.wait(5000)
        result = results[0] if results else None
        msgids = {key.msgid for key in (worker.manager.translations if worker.manager else {})}
        self.check("Qt worker thread",
                   stopped and result is not None and result.action_successful and PROBE_MSGID in msgids,
                   "no result within 30s" if result is None else (result.error_message or ""))

        mo_result = worker.manager.manage_translations(TranslationAction.WRITE_MO_FILES)
        catalog = gettext.translation("base", os.path.join(project, "locale"), languages=["de"], fallback=True)
        self.check("MO compilation (polib)",
                   mo_result.action_successful and catalog.gettext(PROBE_MSGID) == PROBE_MSGSTR_DE,
                   mo_result.error_message or "")

    def check_yaml(self) -> None:
        """A Rails locale file read with PyYAML and round-tripped with ruamel.yaml."""
        import io

        import yaml

        from i18n.ruby.yaml_parser_utils import ruby_roundtrip_yaml

        source = 'en:\n  # kept\n  greeting: "Hello"\n  nested:\n    key: value\n'
        loaded = yaml.safe_load(source)
        self.check("PyYAML", loaded == {"en": {"greeting": "Hello", "nested": {"key": "value"}}})
        ryaml = ruby_roundtrip_yaml()
        data = ryaml.load(source)
        data["en"]["added"] = "new"
        out = io.StringIO()
        ryaml.dump(data, out)
        written = out.getvalue()
        self.check("ruamel.yaml round trip", "# kept" in written and 'greeting: "Hello"' in written
                   and "added: new" in written)

    def check_argos(self) -> None:
        """argostranslate and the native libraries it translates with load,
        with the models dir in scratch. No model is downloaded."""
        import importlib

        from lib.argos_translate import ARGOS_IMPORT_ERROR, ArgosTranslate

        if ARGOS_IMPORT_ERROR is not None:
            self.check("Argos Translate", False,
                       f"import failed: {type(ARGOS_IMPORT_ERROR).__name__}: {ARGOS_IMPORT_ERROR}")
            return
        for module in ("ctranslate2", "sentencepiece"):
            importlib.import_module(module)
        argos = ArgosTranslate()
        self.check("Argos Translate", argos.is_usable, str(getattr(argos, "models_dir", "")))

    def check_process_list(self) -> None:
        """The old-build cleanup removes nothing off Windows, and relies on the
        rename alone on Windows, when it cannot list running processes. The
        cleanup runs only in a build, so a checkout only logs the result."""
        import importlib.util

        from utils.app_paths import IS_BUILD
        from utils.unpack_cleanup import _running_executables

        executables = _running_executables()
        if executables is not None:
            detail = f"{len(executables)} executable(s)"
        elif importlib.util.find_spec("psutil") is None:
            detail = "psutil is not installed"
        else:
            detail = "psutil could not list them (see the warning above)"
        if IS_BUILD:
            self.check("process list", executables is not None, detail)
        else:
            self.logger.info(f"smoke test: process list: not required in a source checkout ({detail})")

    def check_fault_log(self) -> None:
        import os

        from utils.crash_log import enable_fault_log

        path = enable_fault_log()
        self.check("fault log", os.path.isfile(path), path)

    def _qt_app(self):
        """The QApplication, created on first use and kept for the rest of the
        run: PyQt destroys one nothing references, and an event loop without
        it never delivers a worker thread's signal."""
        from PyQt6.QtWidgets import QApplication

        if self._app is None:
            self._app = QApplication.instance() or QApplication([])
        return self._app

    def check_qt(self) -> None:
        """A QApplication, Qt's messages reaching the log, the SVG icon, and
        the main window created and closed (offscreen)."""
        from PyQt6.QtGui import QIcon

        from ui.app_style import AppStyle
        from ui.qt_message_log import qt_message_reaches_logging
        from utils.app_paths import resource_path

        app = self._qt_app()
        self.check("Qt messages logged", qt_message_reaches_logging())
        icon = QIcon(resource_path("assets", "icon.svg"))
        self.check("SVG icon", not icon.pixmap(32, 32).isNull())
        AppStyle.sync_theme_from_application(app)
        if self.main_window_class is None:
            self.logger.info("smoke test: main window: not checked (no window class given)")
            return
        window = self.main_window_class()
        window.close()
        window.deleteLater()
        self.check("main window", True)


def run_smoke_test(scratch: str, main_window_class=None) -> int:
    """Run every check; returns the exit code."""
    smoke = SmokeTest(scratch, main_window_class)
    smoke.logger.info(f"smoke test: scratch directory {scratch}")
    smoke.guarded("bundled files", smoke.check_bundled_files)
    smoke.guarded("default config", smoke.check_default_config)
    smoke.guarded("user data", smoke.check_user_data)
    smoke.guarded("gettext project", smoke.check_gettext_project)
    smoke.guarded("Qt worker thread", smoke.check_qt_thread)
    smoke.guarded("YAML", smoke.check_yaml)
    smoke.guarded("Argos Translate", smoke.check_argos)
    smoke.guarded("process list", smoke.check_process_list)
    smoke.guarded("fault log", smoke.check_fault_log)
    smoke.guarded("Qt", smoke.check_qt)
    return smoke.result()
