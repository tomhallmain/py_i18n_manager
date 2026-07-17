"""Background "translate all missing" batch orchestration for the Outstanding Items window.

``TranslationWorker`` is moved here unchanged. ``BackgroundTranslationController`` is a thin
extraction of the QThread/TranslationWorker lifecycle management that previously lived directly
on ``OutstandingItemsWindow`` (thread/worker creation, signal wiring, cancel, cleanup) -- the
window still owns ``is_translating``, the translate-all buttons, and the progress dialog; this
only owns the worker thread pair and forwards its signals. Pure extraction: same signal flow,
same behavior, so this module is where the addressing/conflict-safety work for background LLM
updates (see docs/background-llm-outstanding-items-spec.md) will eventually land.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from lib.llm import LLMBatchStoppingException
from utils.globals import LLMTranslationMode
from utils.logging_setup import get_logger

logger = get_logger(__name__)


def _display_key(key, max_len=40):
    """Human-readable form of a translation key for progress labels."""
    text = key if isinstance(key, str) else key[1] if isinstance(key, tuple) else str(key)
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def _context_for_key(key, source_text):
    """Only include the key as context when it differs from the source text itself."""
    key_str = key if isinstance(key, str) else key[1] if isinstance(key, tuple) else str(key)
    return f"Translation key: {key_str}" if key_str != source_text else None


class TranslationWorker(QObject):
    """Worker for running translation tasks in a separate thread.

    ``queue`` holds either per-cell items ``(row, col, key, locale, source_text)`` (Argos, or LLM
    in :attr:`LLMTranslationMode.PER_LOCALE` mode - one request per cell), or per-key items
    ``(row, key, source_text, [(col, locale), ...])`` when ``mode`` is
    :attr:`LLMTranslationMode.PER_KEY_ALL_LOCALES` - one LLM request per key covering every
    missing locale for that key at once. ``total`` counts individual missing cells either way, so
    progress reporting is consistent between modes.
    """
    progress_updated = pyqtSignal(int, int, str)  # completed, total, current_key
    translation_completed = pyqtSignal(int, int, str)  # row, col, translated_text
    finished = pyqtSignal()
    error = pyqtSignal(str)
    # message; emitted when the batch stops early due to a provider error that won't resolve by
    # continuing (rate limited, or forbidden e.g. the model requires a paid subscription)
    batch_stopped_error = pyqtSignal(str)

    def __init__(self, translation_service, queue, use_llm=False,
                 mode=LLMTranslationMode.PER_LOCALE, total=None):
        super().__init__()
        self.translation_service = translation_service
        self.queue = queue
        self.use_llm = use_llm
        self.mode = mode
        self._cancelled = False
        self.total = total if total is not None else len(queue)
        self.completed = 0

    def cancel(self):
        """Cancel the translation process."""
        self._cancelled = True
        # Also cancel any ongoing LLM generation (both single- and multi-locale clients)
        if self.use_llm and hasattr(self.translation_service, 'llm'):
            self.translation_service.llm.cancel_generation()
        if self.use_llm and hasattr(self.translation_service, 'llm_multi'):
            self.translation_service.llm_multi.cancel_generation()

    def run(self):
        """Process the translation queue."""
        try:
            is_multi_locale = self.use_llm and self.mode == LLMTranslationMode.PER_KEY_ALL_LOCALES
            while self.queue and not self._cancelled:
                try:
                    if is_multi_locale:
                        self._run_multi_locale_item()
                    else:
                        self._run_single_locale_item()
                except LLMBatchStoppingException as e:
                    # Stop the batch rather than hammering a blocked endpoint through the rest of
                    # the queue. Items already applied via translation_completed are kept.
                    logger.warning(f"Stopping translation batch: {e}")
                    self.batch_stopped_error.emit(str(e))
                    break

            self.progress_updated.emit(self.completed, self.total, "")

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def _run_single_locale_item(self):
        """Translate one (row, col) cell - one LLM/Argos request per missing locale."""
        row, col, key, locale, source_text = self.queue.pop(0)

        self.progress_updated.emit(self.completed, self.total, f"{_display_key(key)} -> {locale}")

        if self._cancelled:
            return

        context = _context_for_key(key, source_text)

        try:
            translated = self.translation_service.translate(
                text=source_text,
                target_locale=locale,
                context=context,
                use_llm=self.use_llm
            )

            if translated and not self._cancelled:
                self.translation_completed.emit(row, col, translated)

        except LLMBatchStoppingException:
            raise
        except Exception as e:
            logger.error(f"Translation failed for {key} to {locale}: {e}")

        self.completed += 1

    def _run_multi_locale_item(self):
        """Translate every missing locale for one key with a single LLM request."""
        row, key, source_text, locale_cols = self.queue.pop(0)
        locales = [locale for _, locale in locale_cols]

        self.progress_updated.emit(
            self.completed, self.total, f"{_display_key(key)} -> {', '.join(locales)}"
        )

        if self._cancelled:
            return

        context = _context_for_key(key, source_text)

        try:
            translations = self.translation_service.translate_with_llm_multi_locale(
                text=source_text,
                target_locales=locales,
                context=context,
            )
            for col, locale in locale_cols:
                translated = translations.get(locale, "")
                if translated and not self._cancelled:
                    self.translation_completed.emit(row, col, translated)

        except LLMBatchStoppingException:
            raise
        except Exception as e:
            logger.error(f"Multi-locale translation failed for {key}: {e}")

        self.completed += len(locale_cols)


class BackgroundTranslationController(QObject):
    """Creates and wires a TranslationWorker/QThread pair for a translate-all batch.

    Thin extraction of what previously lived directly on OutstandingItemsWindow: the window
    still owns ``is_translating``/button state and the progress dialog; this only owns the
    QThread/TranslationWorker pair and forwards its signals unchanged.
    """

    progress_updated = pyqtSignal(int, int, str)
    translation_completed = pyqtSignal(int, int, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    batch_stopped_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None

    def start(self, translation_service, queue, use_llm, mode, total):
        self.thread = QThread()
        self.worker = TranslationWorker(
            translation_service,
            queue,
            use_llm=use_llm,
            mode=mode,
            total=total,
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress_updated.connect(self.progress_updated)
        self.worker.translation_completed.connect(self.translation_completed)
        self.worker.finished.connect(self.finished)
        self.worker.error.connect(self.error)
        self.worker.batch_stopped_error.connect(self.batch_stopped_error)

        self.thread.start()

    def cancel(self):
        """Cancel the ongoing translation process."""
        if self.worker:
            self.worker.cancel()
            logger.info("Translation cancellation requested")

    def cleanup(self):
        """Quit and wait for the worker thread, then drop references.

        Call after ``finished`` has been handled -- mirrors the thread teardown that used to run
        inline in ``OutstandingItemsWindow._on_translation_finished``.
        """
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
        self.worker = None
