"""ui/qt_message_log.py: Qt's messages reach Python logging."""

import logging

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")

from ui import qt_message_log  # noqa: E402


class _Context:
    def __init__(self, category):
        self.category = category


@pytest.fixture
def records():
    """Records the module's logger emits. get_logger() turns propagation off,
    so caplog's root handler would not see them."""
    seen = []

    class _Collect(logging.Handler):
        def emit(self, record):
            seen.append(record)

    collector = _Collect(level=logging.DEBUG)
    qt_message_log.logger.addHandler(collector)
    yield seen
    qt_message_log.logger.removeHandler(collector)


@pytest.mark.parametrize("mode, level", [
    (QtCore.QtMsgType.QtDebugMsg, logging.DEBUG),
    (QtCore.QtMsgType.QtWarningMsg, logging.WARNING),
    (QtCore.QtMsgType.QtCriticalMsg, logging.ERROR),
])
def test_messages_are_logged_at_the_matching_level(records, mode, level):
    qt_message_log._handle_qt_message(mode, _Context("qt.svg"), "bad path")
    assert records[-1].levelno == level
    assert records[-1].getMessage() == "qt.svg: bad path"


def test_the_default_category_is_left_out(records):
    qt_message_log._handle_qt_message(QtCore.QtMsgType.QtWarningMsg, _Context("default"), "plain")
    assert records[-1].getMessage() == "plain"


def test_installed_once_and_routes_qt_warnings(monkeypatch):
    previous = []

    def install(handler):
        previous.append(QtCore.qInstallMessageHandler(handler))

    monkeypatch.setattr(qt_message_log, "qInstallMessageHandler", install)
    monkeypatch.setattr(qt_message_log, "_installed", False)
    try:
        qt_message_log.install_qt_message_handler()
        qt_message_log.install_qt_message_handler()
        assert len(previous) == 1
        assert qt_message_log.qt_message_reaches_logging()
    finally:
        # Hands Qt back the handler it had before the test.
        QtCore.qInstallMessageHandler(previous[0] if previous else None)
