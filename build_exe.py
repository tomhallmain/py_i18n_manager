"""
Build the i18n Translation Manager with Nuitka: ``python build_exe.py``.

Nuitka compiles the code to C, then to a single native executable that embeds
the Python runtime. Needs a C compiler: Xcode Command Line Tools on macOS; on
Windows, Visual Studio Build Tools, or Nuitka downloads MinGW itself. Nuitka
does not cross-compile, so run this on each target OS. Run it with Python
3.11: the build venv and the executable use the interpreter running this
script.

Builds inside a dedicated ``.venv-build`` at the repo root, populated from
requirements-build.txt, so packages from the active conda env or venv aren't
bundled. ``--current-env`` builds with the running interpreter instead; it
must already have requirements-build.txt installed.

Builds dist/I18nManager (``.exe`` on Windows) from app.py. At its first start
it unpacks its runtime to ``~/.i18n_manager/unpacked/i18n-manager-<build id>``;
later starts of the same build reuse that folder. It is then smoke-tested with
``--smoke-test`` in a scratch environment (utils/smoke_test.py). Other args are
forwarded to Nuitka, e.g. ``--show-scons`` or ``--jobs=4``.

Before compressing the onefile payload, the last step of the compile, the
build waits for enough free memory (the memory-wait plugin, from app-release
when installed), since a failed allocation there loses the whole compile.
``--min-free-memory=<GiB>`` sets the amount instead of the estimate; 0 turns
the wait off. Each step is timed, and the log goes to
``build/logs/build_exe-<build id>.log`` as well (Nuitka's own output only to
the console).

The executable's version information comes from the VERSION file at the repo
root, which is also bundled, with the build id (build time) in its
description. On Windows, assets/icon.svg becomes its icon. Each build writes
``build/nuitka/build_info.json`` (version, build id, Python and key package
versions, and this checkout's path, commit, the commit's tree and a
fingerprint of its uncommitted changes), bundled so the app logs it at
startup, and ``build/nuitka/build-requirements.lock.txt``, the build venv's
``pip freeze``. ``--lock=<file>`` installs the build venv from such a file
instead of requirements-build.txt, to repeat a known good build; packages
already in the venv but absent from the file stay installed, so delete
.venv-build first for an exact copy. app-release publishes the executable in
dist/ as a GitHub release.
"""
import contextlib
import glob
import json
import logging
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import venv

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(REPO_ROOT, ".venv-build")
BUILD_DIR = os.path.join(REPO_ROOT, "build", "nuitka")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
# utils.app_paths.default_app_data_dir() (~/.i18n_manager), spelled for Nuitka.
APP_DATA_SPEC = "{HOME}/.i18n_manager"
TARGET_PYTHON = (3, 11)
VERSION_FILE = "VERSION"
VERSION_MODULE = os.path.join("utils", "version.py")
SMOKE_TEST_MODULE = os.path.join("utils", "smoke_test.py")
BUILD_INFO_PATH = os.path.join(BUILD_DIR, "build_info.json")
LOCK_PATH = os.path.join(BUILD_DIR, "build-requirements.lock.txt")
LOG_DIR = os.path.join(REPO_ROOT, "build", "logs")
# Set by app-release, which ships the memory-wait plugin, when it runs this script.
MEMORY_WAIT_PLUGIN_ENV = "NUITKA_MEMORY_WAIT_PLUGIN"
# Read by the memory-wait plugin.
MIN_FREE_MEMORY_ENV = "BUILD_MIN_FREE_MEMORY_GB"
# Versions the build output and build_info.json record.
RECORDED_DISTRIBUTIONS = (
    "Nuitka", "PyQt6", "PyQt6-Qt6", "polib", "Babel", "PyYAML", "ruamel.yaml", "argostranslate",
    "ctranslate2", "sentencepiece", "stanza", "torch", "psutil",
)
ICON_SVG = os.path.join("assets", "icon.svg")
ICON_ICO = os.path.join(BUILD_DIR, "i18n_manager_icon.ico")

# Shipped files, at the same relative paths utils/app_paths.resource_path()
# resolves them under.
DATA_FILES = (VERSION_FILE, os.path.join("configs", "default_config.json"), ICON_SVG)
LOCALE_DIR = "locale"
# Packages that read data files of their own at runtime: Babel its locale data
# (the POT header date is formatted with it).
PACKAGE_DATA = ("babel",)
# Prints {"python": ..., "packages": {name: version}} for the names in argv.
_VERSIONS_PROBE = (
    "import json, sys\n"
    "from importlib.metadata import PackageNotFoundError, version\n"
    "def get(name):\n"
    "    try:\n"
    "        return version(name)\n"
    "    except PackageNotFoundError:\n"
    "        return None\n"
    "print(json.dumps({'python': sys.version.split()[0],\n"
    "                  'packages': {n: get(n) for n in sys.argv[1:]}}))\n"
)
# Renders ICON_SVG (argv[1]) to a 256px .ico (argv[2]) with the build venv's Qt;
# QIcon renders the SVG at the requested size.
_ICON_SCRIPT = (
    "import sys\n"
    "from PyQt6.QtGui import QGuiApplication, QIcon\n"
    "app = QGuiApplication(sys.argv[:1])\n"
    "image = QIcon(sys.argv[1]).pixmap(256, 256).toImage()\n"
    "if image.isNull():\n"
    "    sys.exit(f'Cannot render {sys.argv[1]}')\n"
    "sys.exit(0 if image.save(sys.argv[2], 'ICO') else 1)\n"
)

logger = logging.getLogger("build_exe")


class _LevelPrefix(logging.Filter):
    def filter(self, record):
        record.level_prefix = "" if record.levelno == logging.INFO else f"{record.levelname}: "
        return True


def _setup_logging(build_id: str) -> str:
    """Log to the console and to a file for this build; returns the file's path."""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"build_exe-{build_id}.log")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("[%(asctime)s] %(level_prefix)s%(message)s", "%H:%M:%S"))
    log_file = logging.FileHandler(path, encoding="utf-8")
    log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for handler in (console, log_file):
        handler.addFilter(_LevelPrefix())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


@contextlib.contextmanager
def _timed(step: str):
    """Log how long *step* took, or after how long it failed."""
    started = time.monotonic()
    logger.info(f"{step}...")
    try:
        yield
    except BaseException:
        logger.error(f"{step} failed after {_duration(time.monotonic() - started)}")
        raise
    logger.info(f"{step} done in {_duration(time.monotonic() - started)}")


def _check_python(version_info=sys.version_info) -> None:
    if tuple(version_info[:2]) != TARGET_PYTHON:
        wanted = ".".join(map(str, TARGET_PYTHON))
        sys.exit(f"Run build_exe.py with Python {wanted}: the build venv and the executable use the "
                 f"interpreter running it, and this is {version_info[0]}.{version_info[1]}.")


def _venv_python(venv_dir: str) -> str:
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _exe_name(base: str) -> str:
    return f"{base}.exe" if sys.platform == "win32" else base


def _ensure_build_venv(requirements=None) -> str:
    """The build venv's interpreter, after installing *requirements*
    (requirements-build.txt by default, or a lock file)."""
    python = _venv_python(VENV_DIR)
    if not os.path.exists(python):
        logger.info(f"Creating build venv at {VENV_DIR}")
        venv.create(VENV_DIR, with_pip=True)
    requirements = requirements or os.path.join(REPO_ROOT, "requirements-build.txt")
    subprocess.run([python, "-m", "pip", "install", "-q", "-r", requirements], check=True)
    return python


def _write_lock_file(python: str) -> None:
    freeze = subprocess.run([python, "-m", "pip", "freeze"], capture_output=True, text=True, check=True)
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(freeze.stdout)
    logger.info(f"Build environment recorded in {LOCK_PATH}")


def _version_module() -> dict:
    """utils/version.py's globals, loaded without importing the app."""
    return runpy.run_path(os.path.join(REPO_ROOT, VERSION_MODULE))


def _app_version() -> str:
    with open(os.path.join(REPO_ROOT, VERSION_FILE), "r", encoding="utf-8") as f:
        version = f.read().strip()
    if not re.fullmatch(r"\d+(\.\d+){0,3}", version):
        sys.exit(f"{VERSION_FILE} holds {version!r}; it must be up to four dot-separated numbers.")
    return version


def _environment_versions(python: str) -> dict:
    probe = subprocess.run(
        [python, "-c", _VERSIONS_PROBE, *RECORDED_DISTRIBUTIONS], capture_output=True, text=True, check=True,
    )
    return json.loads(probe.stdout.strip().splitlines()[-1])


def _write_build_info(version: str, build_id: str, environment: dict) -> None:
    """build_info.json, bundled at the resource root (utils/version.py reads it)."""
    info = {
        "version": version,
        "build_id": build_id,
        "python": environment["python"],
        "packages": {name: v for name, v in environment["packages"].items() if v},
        # Anyone with the executable can read this path; app-release warns of it.
        # The startup source drift check finds the checkout by it.
        "source": {"repo": REPO_ROOT, **_version_module()["source_state"](REPO_ROOT)},
    }
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(BUILD_INFO_PATH, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    logger.info("Building " + ", ".join(
        [f"i18n Translation Manager {version}", f"build {build_id}",
         f"from {info['source']['commit'][:10] or 'unknown commit'}"
         + (" with uncommitted changes" if info["source"]["changes"] else ""),
         f"Python {info['python']}"]
        + [f"{name} {v}" for name, v in sorted(info["packages"].items())]
    ))


def _locale_files() -> list:
    """The compiled catalogs, as repo-relative paths. The .po/.pot sources
    beside them are not shipped."""
    pattern = os.path.join(REPO_ROOT, LOCALE_DIR, "*", "LC_MESSAGES", "*.mo")
    return sorted(os.path.relpath(path, REPO_ROOT) for path in glob.glob(pattern))


def _write_windows_icon(python: str) -> None:
    """Render ICON_SVG to the .ico Nuitka needs, with the build venv's Qt."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([python, "-c", _ICON_SCRIPT, os.path.join(REPO_ROOT, ICON_SVG), ICON_ICO],
                   env=env, check=True)


def _memory_wait_plugin():
    """The memory-wait plugin's path: from app-release's variable, else from an
    installed app-release, else None (the build does not wait)."""
    path = os.environ.get(MEMORY_WAIT_PLUGIN_ENV)
    tool = None if path else shutil.which("app-release")
    if tool:
        try:
            result = subprocess.run([tool, "--memory-wait-plugin"], capture_output=True, text=True,
                                    stdin=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"Cannot ask {tool} for the memory-wait plugin: {e}")
        else:
            if result.returncode == 0:
                path = result.stdout.strip()
    if path and os.path.isfile(path):
        logger.info(f"Memory-wait plugin: {path}")
        return path
    logger.warning("No memory-wait plugin: the onefile step will not wait for free memory. "
                   "Install app-release, or build through it.")
    return None


def _common_args(exe_name: str, unpack_prefix: str, version: str, build_id: str,
                 memory_wait_plugin=None) -> list:
    args = [
        "--onefile",
        # The exe unpacks its runtime to this folder. A fixed path (no
        # {PID}/{TIME}) makes Nuitka keep it between runs, so only the first
        # run pays the unpacking cost; the build id gives each build its own
        # folder, so a rebuilt exe never reuses a previous build's files.
        # Nothing the app writes goes under unpacked/.
        f"--onefile-tempdir-spec={APP_DATA_SPEC}/unpacked/{unpack_prefix}-{build_id}",
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={exe_name}",
        # Lets Nuitka fetch build helpers (e.g. MinGW on Windows) without prompting.
        "--assume-yes-for-downloads",
        # Version information; Windows shows it in the executable's properties
        # and crash reports. The file version takes numbers only, so the build
        # id goes in the description.
        "--product-name=i18n Translation Manager",
        f"--product-version={version}",
        f"--file-version={version}",
        f"--file-description=i18n Translation Manager, build {build_id}",
        f"--include-data-files={BUILD_INFO_PATH}=build_info.json",
        *([f"--user-plugin={memory_wait_plugin}"] if memory_wait_plugin else []),
    ]
    args += [f"--include-data-files={f}={f}" for f in DATA_FILES]
    args += [f"--include-data-files={f}={f}" for f in _locale_files()]
    args += [f"--include-package-data={package}" for package in PACKAGE_DATA]
    if sys.platform == "win32":
        args.append(f"--windows-icon-from-ico={ICON_ICO}")
    return args


def _gui_args() -> list:
    args = ["--enable-plugin=pyqt6"]
    if sys.platform == "win32":
        # No console window when started from Explorer; when started from a
        # terminal, output (e.g. the smoke test's) goes to that terminal.
        args.append("--windows-console-mode=attach")
    return args


def _argos_args(packages: dict) -> list:
    """Arguments for Argos Translate's dependency tree, as installed in the
    build venv (*packages*: distribution name to version, None if absent)."""
    args = []
    if packages.get("torch"):
        # TorchScript reads function source, which a compiled build lacks.
        args += ["--module-parameter=torch-disable-jit=yes", "--include-distribution-metadata=torch"]
    return args


def _nuitka_env(min_free_memory=None) -> dict:
    env = dict(os.environ)
    if min_free_memory is not None:
        env[MIN_FREE_MEMORY_ENV] = min_free_memory
    return env


def _min_free_memory(value):
    """``--min-free-memory``'s value, checked, or None when not given."""
    if value is None:
        return None
    try:
        if float(value) >= 0:
            return value
    except ValueError:
        pass
    sys.exit(f"--min-free-memory={value}: give a number of GiB, or 0 to not wait for memory.")


def _copy_to_dist(exe_name: str) -> str:
    exe_path = os.path.join(DIST_DIR, exe_name)
    if os.path.isdir(exe_path):
        # Left by a folder build; on macOS/Linux it has the executable's name.
        logger.info(f"Removing the folder build at {exe_path}")
        shutil.rmtree(exe_path)
    os.makedirs(DIST_DIR, exist_ok=True)
    shutil.copy2(os.path.join(BUILD_DIR, exe_name), exe_path)
    return exe_path


def _pop_option(args: list, name: str):
    """Remove ``name=value`` from *args* and return the value, or None."""
    for arg in list(args):
        if arg.startswith(name + "="):
            args.remove(arg)
            return arg.split("=", 1)[1]
    return None


def _smoke_test_env(scratch: str) -> dict:
    """The environment for a smoke test with all app data in *scratch*: the one
    the executable sets up for itself (utils/smoke_test.py), also set here so
    the scratch directory is the one this script removes afterwards."""
    env = dict(os.environ)
    env.update(runpy.run_path(os.path.join(REPO_ROOT, SMOKE_TEST_MODULE))["smoke_test_environment"](scratch))
    return env


def _smoke_test(exe_path: str) -> None:
    # Run from outside the repo so a passing test can't depend on the checkout,
    # with all app data in a scratch directory so the user's is untouched. On
    # Windows Nuitka resolves {HOME} without the HOME set here, so the exe
    # unpacks to the real ~/.i18n_manager/unpacked/, which a later start of
    # this build reuses.
    command = [exe_path, "--smoke-test"]
    with tempfile.TemporaryDirectory(prefix="i18n-manager-smoke-", ignore_cleanup_errors=True) as scratch:
        result = subprocess.run(command, cwd=os.path.expanduser("~"), env=_smoke_test_env(scratch))
    if result.returncode != 0:
        sys.exit(f"Smoke test failed: `{' '.join(command)}` exited {result.returncode}.")


# exe base name, entry script, unpack folder prefix, target-specific args
TARGETS = (
    ("I18nManager", "app.py", "i18n-manager", _gui_args),
)


def main() -> None:
    _check_python()
    args = sys.argv[1:]
    lock = _pop_option(args, "--lock")
    min_free_memory = _min_free_memory(_pop_option(args, "--min-free-memory"))
    version = _app_version()
    build_id = time.strftime("%Y%m%d-%H%M%S")
    logger.info(f"Log: {_setup_logging(build_id)}")

    if "--current-env" in args:
        args.remove("--current-env")
        if lock:
            sys.exit("--lock installs into the build venv; it cannot be combined with --current-env.")
        python = sys.executable
    else:
        if lock:
            lock = os.path.abspath(lock)
            if not os.path.isfile(lock):
                sys.exit(f"--lock: {lock} not found.")
        with _timed("Installing the build venv"):
            python = _ensure_build_venv(requirements=lock)

    _write_lock_file(python)
    environment = _environment_versions(python)
    _write_build_info(version, build_id, environment)
    if sys.platform == "win32":
        _write_windows_icon(python)
    extra_args = _argos_args(environment["packages"])
    memory_wait_plugin = _memory_wait_plugin()

    for base_name, entry, unpack_prefix, target_args in TARGETS:
        exe_name = _exe_name(base_name)
        nuitka_args = [
            *_common_args(exe_name, unpack_prefix, version, build_id, memory_wait_plugin),
            *target_args(), *extra_args, *args, os.path.join(REPO_ROOT, entry),
        ]
        with _timed(f"Compiling {base_name} with Nuitka"):
            result = subprocess.run([python, "-m", "nuitka", *nuitka_args], cwd=REPO_ROOT,
                                    env=_nuitka_env(min_free_memory))
            if result.returncode != 0:
                sys.exit(f"Nuitka exited {result.returncode} compiling {base_name}; its output is above.")
        exe_path = _copy_to_dist(exe_name)
        with _timed(f"Smoke-testing {exe_name}"):
            _smoke_test(exe_path)
        logger.info(f"Built {exe_path}")


if __name__ == "__main__":
    started = time.monotonic()
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            if isinstance(e.code, str):
                logger.error(e.code)
            logger.error(f"Build failed after {_duration(time.monotonic() - started)}")
            sys.exit(1)
        raise
    except KeyboardInterrupt:
        logger.error(f"Build stopped after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    except BaseException:
        logger.exception(f"Build failed after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    logger.info(f"Build finished in {_duration(time.monotonic() - started)}")
