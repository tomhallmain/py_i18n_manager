"""Progress dialog for batch translation operations."""

from __future__ import annotations

import time

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QProgressBar, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from utils.translations import I18N

_ = I18N._


class ETATracker:
    """Rolling exponential-moving-average estimator for per-item translation time."""

    _ALPHA = 0.3  # EMA smoothing factor (~3-item effective window weight)

    def __init__(self) -> None:
        self._ema: float | None = None
        self._last_time: float | None = None
        self._last_completed: int = 0
        self._data_points: int = 0

    def record(self, completed: int) -> None:
        """Update the tracker whenever a progress signal arrives."""
        now = time.monotonic()
        if self._last_time is not None and completed > self._last_completed:
            elapsed = now - self._last_time
            per_item = elapsed / (completed - self._last_completed)
            self._ema = (
                per_item
                if self._ema is None
                else self._ALPHA * per_item + (1.0 - self._ALPHA) * self._ema
            )
            self._data_points += 1
        if self._last_time is None or completed > self._last_completed:
            self._last_time = now
            self._last_completed = completed

    def eta_seconds(self, remaining: int) -> float | None:
        """Estimated seconds remaining, or None if not yet estimable."""
        if remaining <= 0 or self._data_points == 0 or self._ema is None:
            return None
        return self._ema * remaining


class TranslationProgressDialog(QDialog):
    """Dialog showing translation progress with cancel option."""

    cancelled = pyqtSignal()

    def __init__(self, parent=None, title="Translation Progress", use_llm=False, mode_label: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self.use_llm = use_llm
        self.mode_label_text = mode_label
        self._eta = ETATracker()

        # Prevent closing via X button while active
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Method label
        method_text = "LLM" if self.use_llm else "Argos Translate"
        self.method_label = QLabel(
            _("Translation Method: {method}").format(method=method_text)
        )
        self.method_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.method_label)

        # Mode label (e.g. per-locale vs per-key/all-locales, and the model in use)
        if self.mode_label_text:
            self.mode_label = QLabel(self.mode_label_text)
            self.mode_label.setStyleSheet("color: gray;")
            self.mode_label.setWordWrap(True)
            layout.addWidget(self.mode_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Count label
        self.count_label = QLabel(
            _("{completed} / {total} translations completed").format(completed=0, total=0)
        )
        layout.addWidget(self.count_label)

        # ETA label
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("color: gray;")
        layout.addWidget(self.eta_label)

        # Current item label
        self.current_label = QLabel(_("Preparing..."))
        self.current_label.setWordWrap(True)
        self.current_label.setStyleSheet("color: gray;")
        layout.addWidget(self.current_label)

        # Error label - hidden until the batch stops early (e.g. rate limited); stays visible
        # so the user has to notice and manually close the dialog (see show_stopped_early_error).
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        # Cancel button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_btn = QPushButton(_("Cancel"))
        self.cancel_btn.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def update_progress(self, completed, total, current_item):
        """Update the progress display."""
        if total > 0:
            percentage = int((completed / total) * 100)
            self.progress_bar.setValue(percentage)

        self.count_label.setText(
            _("{completed} / {total} translations completed").format(
                completed=completed, total=total
            )
        )

        self._eta.record(completed)
        remaining = total - completed
        eta_secs = self._eta.eta_seconds(remaining)
        if remaining <= 0:
            self.eta_label.setText("")
        elif eta_secs is None:
            self.eta_label.setText(_("Estimating time remaining…"))
        else:
            self.eta_label.setText(
                _("~{eta} remaining").format(eta=self._format_eta(eta_secs))
            )

        if current_item:
            self.current_label.setText(_("Translating: {item}").format(item=current_item))
        elif completed >= total:
            self.current_label.setText(_("Finished"))
        elif completed > 0:
            # Stopped before finishing (cancelled, or an error - see show_stopped_early_error).
            self.current_label.setText(_("Stopped"))
        else:
            self.current_label.setText(_("Preparing..."))

    def show_stopped_early_error(self, message: str) -> None:
        """Display a persistent error explaining why the batch stopped before completing.

        The dialog is left open rather than auto-closing - on_finished() (called right after
        this, once the worker's finished signal arrives) turns Cancel into Close, so the user
        has to notice this message and dismiss the dialog themselves. The completed/total count
        already shown above this label reflects how many items finished before the stop.
        """
        self.error_label.setText(message)
        self.error_label.show()

    @staticmethod
    def _format_eta(secs: float) -> str:
        s = int(secs)
        if s < 60:
            return _("{s} sec").format(s=s)
        m, s = divmod(s, 60)
        if m < 60:
            return _("{m} min {s} sec").format(m=m, s=f"{s:02d}")
        h, m = divmod(m, 60)
        return _("{h} hr {m} min").format(h=h, m=f"{m:02d}")

    def on_cancel(self):
        """Handle cancel button click."""
        reply = QMessageBox.question(
            self,
            _("Cancel Translation"),
            _("Are you sure you want to cancel the translation process?\n\nCompleted translations will be kept."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(_("Cancelling..."))
            self.current_label.setText(_("Cancelling translation process..."))
            self.cancelled.emit()

    def on_finished(self):
        """Handle when translation is finished."""
        self.cancel_btn.setText(_("Close"))
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)
        # Re-enable close button
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowCloseButtonHint)
        self.show()  # Refresh window flags
