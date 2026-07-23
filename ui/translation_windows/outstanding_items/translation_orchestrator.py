"""Background "translate all missing" batch orchestration for the Outstanding Items window.

``TranslationWorker`` runs the actual Argos/LLM calls on a background ``QThread`` -- the whole
point being that the GUI thread keeps running its event loop throughout, so the user can keep
editing the table while a long batch is still in flight. Results are addressed by translation key
(not table row -- rows can shift under it, see ``BackgroundTranslationController`` below).
``BackgroundTranslationController`` owns the QThread/TranslationWorker lifecycle: creation, signal
wiring, cancel, the re-keyed addressing / "don't overwrite text that's already there" conflict
check, and (for the cloud-LLM PER_KEY_ALL_LOCALES case) the live "don't even bother asking if the
whole row already has text" pre-flight check. The window still owns ``is_translating``, the
translate-all buttons, and the inline progress widgets; this module is where the
addressing/conflict-safety and thread-lifecycle-safety work lives instead.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal

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

    ``queue`` holds either per-cell items ``(key, col, locale, source_text)`` (Argos, or LLM in
    :attr:`LLMTranslationMode.PER_LOCALE` mode - one request per cell), or per-key items
    ``(key, source_text, [(col, locale), ...])`` when ``mode`` is
    :attr:`LLMTranslationMode.PER_KEY_ALL_LOCALES` - one LLM request per key covering every
    missing locale for that key at once. ``total`` counts individual missing cells either way, so
    progress reporting is consistent between modes.

    Deliberately keyed by translation key rather than table row: the table can be rebuilt (row
    deletion, duplicate-combine reload) while this worker is mid-queue, so a row index captured
    when the queue was built could point at the wrong key -- or no row at all -- by the time a
    result comes back. ``BackgroundTranslationController`` resolves the *current* row for a key
    at apply-time instead (see its ``_on_worker_translation_completed``). ``col`` is kept as-is
    because it doesn't go stale the way row does: the table's column layout is fixed for the
    life of one ``load_data`` locale set and only rows shift under a running batch.
    """
    progress_updated = pyqtSignal(int, int, str)  # completed, total, current_key
    translation_completed = pyqtSignal(object, int, str, str)  # key, col, locale, translated_text
    finished = pyqtSignal()
    error = pyqtSignal(str)
    # message; emitted when the batch stops early due to a provider error that won't resolve by
    # continuing (rate limited, or forbidden e.g. the model requires a paid subscription)
    batch_stopped_error = pyqtSignal(str)

    def __init__(self, translation_service, queue, use_llm=False,
                 mode=LLMTranslationMode.PER_LOCALE, total=None, row_precheck=None):
        super().__init__()
        self.translation_service = translation_service
        self.queue = queue
        self.use_llm = use_llm
        self.mode = mode
        self._cancelled = False
        self.total = total if total is not None else len(queue)
        self.completed = 0
        # Optional callable ``(key, locale_cols) -> bool``, consulted live by
        # ``_run_multi_locale_item`` right before it would fire a PER_KEY_ALL_LOCALES cloud LLM
        # request: True means every locale that request would ask for already has text *right
        # now*, not just when the queue was built, so the request would be entirely wasted -- see
        # that method and ``BackgroundTranslationController._check_row_fully_filled`` for why this
        # has to be a callback rather than this worker reading table state itself. None (the
        # default -- e.g. a worker built directly in a test, or running in PER_LOCALE mode where
        # it's simply never consulted) means never skip.
        self.row_precheck = row_precheck

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
        """Translate one (key, locale) cell - one LLM/Argos request per missing locale."""
        key, col, locale, source_text = self.queue.pop(0)

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
                self.translation_completed.emit(key, col, locale, translated)

        except LLMBatchStoppingException:
            raise
        except Exception as e:
            logger.error(f"Translation failed for {key} to {locale}: {e}")

        self.completed += 1

    def _run_multi_locale_item(self):
        """Translate every missing locale for one key with a single LLM request."""
        key, source_text, locale_cols = self.queue.pop(0)
        locales = [locale for _, locale in locale_cols]

        self.progress_updated.emit(
            self.completed, self.total, f"{_display_key(key)} -> {', '.join(locales)}"
        )

        if self._cancelled:
            return

        if self.row_precheck and self.row_precheck(key, locale_cols):
            # Every locale this request would have asked for already has text right now --
            # typically because the user filled the rest of the row in directly, or via "Fill
            # Missing in Row", while this item was still sitting behind others in the queue.
            # Firing it anyway would just spend a cloud LLM call whose entire response is
            # guaranteed to be dropped by the per-cell staleness check once it came back.
            logger.debug(f"Skipping LLM request for {key}: every target locale already has text")
            self.completed += len(locale_cols)
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
                    self.translation_completed.emit(key, col, locale, translated)

        except LLMBatchStoppingException:
            raise
        except Exception as e:
            logger.error(f"Multi-locale translation failed for {key}: {e}")

        self.completed += len(locale_cols)


class BackgroundTranslationController(QObject):
    """Creates and wires a TranslationWorker/QThread pair for a translate-all batch.

    Owns the re-keyed addressing (resolve a result's *current* row from its key at apply-time)
    and the "don't overwrite text that's already there" conflict check, so the window's own
    ``_on_translation_completed`` stays a thin ``self.table.setItem(row, col, item)`` -- by the
    time that signal fires, this controller has already decided the write is safe.

    Thread lifecycle mirrors ``translation_quality_review_window.py``'s
    ``_launch_llm_worker``/``_cleanup_llm_thread`` (a separately proven-correct pattern -- see
    that module for the fuller rationale): ``worker.finished`` fires the instant ``run()``
    returns, *before* the QThread's own event loop has processed ``quit()`` and unwound, so
    ``isRunning()`` can still be true then. Dropping the last Python reference to an unparented
    QThread while it's still running aborts the whole process ("QThread: Destroyed while thread
    is still running"), so this only drops ``self.thread``/``self.worker`` once ``thread.finished``
    proves the thread has genuinely stopped. Deliberately does *not* also schedule its own
    ``deleteLater()`` at that point: this object may still be referenced (e.g. by whoever called
    ``start()``) after the thread finishes, and ``deleteLater()``-ing itself risked exactly that
    caller touching a since-deleted C/C++ object -- a real crash hit during testing. The window
    just drops its own reference once the batch is logically done; this object is then collected
    normally once nothing references it, same as any other Python/Qt object.
    """

    progress_updated = pyqtSignal(int, int, str)
    translation_completed = pyqtSignal(int, int, str)  # resolved row, col, translated_text
    finished = pyqtSignal()
    error = pyqtSignal(str)
    batch_stopped_error = pyqtSignal(str)
    # Internal only -- see _check_row_fully_filled. key, locale_cols, result_box (a list used as
    # an out-parameter, since a Qt signal/slot connection can't hand a return value back to the
    # emitting thread the way a normal function call would).
    _row_fully_filled_probe = pyqtSignal(object, list, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None
        self._row_for_key = None
        self._is_stale = None

    def start(self, translation_service, queue, use_llm, mode, total, row_for_key, is_stale):
        """Start the batch.

        ``row_for_key`` is a callable (typically a dict's ``.get``) resolving a translation key
        to its *current* table row, or ``None`` if the key no longer has one (deleted, or no
        longer the representative of a duplicate-combine group) -- consulted per-result in
        ``_on_worker_translation_completed``, not baked into the queue up front.

        ``is_stale(row, col)`` decides whether a result should be dropped because its target
        already has text -- checked live, against the table's *current* state, not against a log
        of past edits: the specific target cell having been filled by anything -- the user
        typing, "Fill Missing in Row with Default Translation", or an earlier result for that
        exact cell -- since the queue was built means this result should not overwrite it,
        however that happened. Checked per cell rather than per row even in
        :attr:`~utils.globals.LLMTranslationMode.PER_KEY_ALL_LOCALES` mode (one request covering
        every missing locale in a row): results for that request are still applied one locale at
        a time, so a row-level check would see the batch's own just-written earlier locale in the
        row and mistake it for a conflicting edit, dropping the rest of that same response. The
        window builds this closure in ``translate_all_missing`` since only it has table access.

        Both callables are also reused, live, for a *row*-level check: before firing a
        PER_KEY_ALL_LOCALES cloud LLM request, ``TranslationWorker`` asks
        ``_check_row_fully_filled`` (below) whether every locale that request would cover already
        has text right now -- distinct from ``is_stale``, which only decides what happens to a
        result *after* a request already went out. This is what actually avoids spending a cloud
        LLM call on a row the user has since finished filling in by hand while it sat behind
        other keys in the queue (the queue-build-time filter in ``translate_all_missing`` only
        catches this at the moment the batch starts, not while it's running).
        """
        self._row_for_key = row_for_key
        self._is_stale = is_stale
        self.thread = QThread()
        self.worker = TranslationWorker(
            translation_service,
            queue,
            use_llm=use_llm,
            mode=mode,
            total=total,
            row_precheck=self._check_row_fully_filled,
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress_updated.connect(self.progress_updated)
        self.worker.translation_completed.connect(self._on_worker_translation_completed)
        self.worker.error.connect(self.error)
        self.worker.batch_stopped_error.connect(self.batch_stopped_error)
        # BlockingQueuedConnection: _check_row_fully_filled runs on the worker's own QThread (it's
        # called directly from TranslationWorker._run_multi_locale_item, not via a normal
        # queued signal), but only the main/GUI thread may touch self.table -- which is what
        # self._is_stale, called from _on_row_fully_filled_probe below, needs to do. This makes
        # emit() block the *worker* thread until the main thread has run the slot and filled in
        # the answer; the GUI thread itself is never blocked, so the user can keep editing while
        # this happens, same as for any other result the batch applies.
        self._row_fully_filled_probe.connect(
            self._on_row_fully_filled_probe, Qt.ConnectionType.BlockingQueuedConnection
        )

        # Self-cleaning lifecycle -- see class docstring for why each gate is on the signal it's
        # on. worker.finished: tell the window the batch is logically done (UI can update now).
        # thread.finished: only once the thread has truly stopped is it safe to drop references.
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._cleanup)

        self.thread.start()

    def _check_row_fully_filled(self, key, locale_cols):
        """``row_precheck`` handed to ``TranslationWorker``: True if every locale in
        ``locale_cols`` already has text right now, so the caller (running on the worker's own
        QThread) shouldn't bother firing a cloud LLM request for it.

        Safe to call from the worker thread specifically *because* it goes through the
        ``_row_fully_filled_probe``/``BlockingQueuedConnection`` round-trip below rather than
        calling ``self._is_stale`` (and therefore touching the QTableWidget it closes over)
        directly here.
        """
        result_box = []
        self._row_fully_filled_probe.emit(key, list(locale_cols), result_box)
        return bool(result_box and result_box[0])

    def _on_row_fully_filled_probe(self, key, locale_cols, result_box):
        """Slot for ``_row_fully_filled_probe``; runs on the main thread (see the
        ``BlockingQueuedConnection`` in ``start()``), so it's safe to call ``self._is_stale``
        here. Appends the answer to ``result_box`` instead of returning it -- signals/slots don't
        carry a return value back across a cross-thread connection the way a plain call would.
        """
        row = self._row_for_key(key) if self._row_for_key else None
        if row is None or not self._is_stale:
            result_box.append(False)
            return
        result_box.append(all(self._is_stale(row, col) for col, _locale in locale_cols))

    def _on_worker_translation_completed(self, key, col, locale, translated_text):
        row = self._row_for_key(key) if self._row_for_key else None
        if row is None:
            logger.debug(f"Dropping translation for {key} ({locale}): no longer an outstanding row")
            return
        if self._is_stale and self._is_stale(row, col):
            logger.debug(f"Dropping translation for {key} ({locale}): target already has text")
            return
        self.translation_completed.emit(row, col, translated_text)

    def cancel(self):
        """Cancel the ongoing translation process."""
        if self.worker:
            self.worker.cancel()
            logger.info("Translation cancellation requested")

    def _cleanup(self) -> None:
        """Drop our references once the QThread has actually stopped running.

        See the class docstring: connected to ``thread.finished``, not ``worker.finished``.
        """
        self.thread = None
        self.worker = None
