"""lib/argos_translate.py starts without a working argostranslate: the import
fails with ImportError when it is not installed, and with other errors when
one of its native libraries cannot load. Run in a subprocess, so the broken
import never reaches this test process."""

import os
import subprocess
import sys

import pytest

pytest.importorskip("PyQt6.QtCore")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# argv[1] names the exception the import of argostranslate raises.
_SCRIPT = """
import sys

ERRORS = {"ModuleNotFoundError": ModuleNotFoundError, "OSError": OSError}


class _BrokenArgos:
    def find_spec(self, name, path=None, target=None):
        if name == "argostranslate" or name.startswith("argostranslate."):
            raise ERRORS[sys.argv[1]]("simulated: argostranslate cannot load")
        return None


sys.modules.pop("argostranslate", None)
sys.meta_path.insert(0, _BrokenArgos())

from lib import argos_translate

assert isinstance(argos_translate.ARGOS_IMPORT_ERROR, ERRORS[sys.argv[1]])
argos = argos_translate.ArgosTranslate()
assert argos.is_usable is False
assert argos.translate("Hello", "de") == ""
assert argos.get_installed_packages() == []
print("argos guard ok")
"""


@pytest.mark.parametrize("error", ["ModuleNotFoundError", "OSError"])
def test_app_module_loads_and_argos_is_unusable(error):
    # The environment, with the root conftest.py's data dir, is inherited.
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, error], cwd=REPO_ROOT,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "argos guard ok" in result.stdout
