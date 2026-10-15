import os

import pytest

# The root conftest.py points the app data dir at a temp dir. If it was not loaded
# (pytest started with another rootdir or confcutdir), the tests would write to the
# real ~/.i18n_manager, and the first config load would move the repo's user files
# there, so stop before any test module is imported.
if not os.environ.get("PY_I18N_MANAGER_DATA_DIR", "").strip():
    raise pytest.UsageError(
        "PY_I18N_MANAGER_DATA_DIR is not set: the repo root conftest.py did not run. "
        "Run pytest from the repo root (pytest.ini there makes it the rootdir)."
    )
