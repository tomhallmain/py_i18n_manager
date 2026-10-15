import atexit
import os
import shutil
import sys
import tempfile

# Ensure the project root is on sys.path so test imports like `from i18n...` work
# regardless of which directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(__file__))

# Keep every test run out of the real app data dir (~/.i18n_manager): settings,
# user config, cache and LLM review output all default to it. Set here, at import,
# because utils.config and utils.app_info_cache resolve their paths when first
# imported, before any fixture runs; set rather than setdefault, so a value exported
# in the developer's shell cannot point the tests at real data; the per-file
# overrides are cleared for the same reason (tests set them through
# tests/test_utils.isolated_settings_and_cache_env). A set override also keeps
# utils/legacy_user_files.py from moving the repo's files.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="py_i18n_manager_test_data_")
os.environ["PY_I18N_MANAGER_DATA_DIR"] = _TEST_DATA_DIR
for _name in ("PY_I18N_MANAGER_SETTINGS_PATH", "PY_I18N_MANAGER_APP_INFO_CACHE_PATH",
              "PY_I18N_MANAGER_CONFIG_DIR"):
    os.environ.pop(_name, None)
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)
