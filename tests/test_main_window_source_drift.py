"""MainWindow tells the user when a build's startup check finds its source
checkout has changed; the check reports from a background thread."""

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from test_utils import isolated_settings_and_cache_env  # noqa: E402
from utils.translations import _  # noqa: E402


@pytest.fixture
def window():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with isolated_settings_and_cache_env(prefix=".tmp_source_drift_", base_dir=Path(__file__).parent):
        import app as app_module

        main_window = app_module.MainWindow()
        try:
            yield main_window
        finally:
            if main_window._source_drift_box is not None:
                main_window._source_drift_box.close()
            main_window.close()
            main_window.deleteLater()
            app.processEvents()


def test_drift_reported_from_a_worker_thread_shows_a_notice(window):
    worker = threading.Thread(target=window.source_drift.emit, args=("2 commits behind",))
    worker.start()
    worker.join(5)
    # The emit is queued to the GUI thread; deliver it.
    deadline = time.monotonic() + 5
    while window._source_drift_box is None and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)

    box = window._source_drift_box
    assert box is not None
    assert box.text() == _("This build differs from its source checkout. Details are in the log.")
    assert not box.isModal()
