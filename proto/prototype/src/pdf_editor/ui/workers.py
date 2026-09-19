"""
Background workers for long-running PDF operations.
Uses QThread + QObject pattern for reliable signal delivery.
"""
import logging
from typing import Callable, Any

from PySide6.QtCore import QObject, Signal, QThread

logger = logging.getLogger(__name__)


class Worker(QObject):
    """Generic worker that runs a callable in a separate thread.

    Signals:
        finished(result): emitted with the return value of the callable on success.
        error(message): emitted with error message on failure.
        progress(message): optional progress updates (caller decides).
    """
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, func: Callable[[], Any], parent: QObject | None = None):
        super().__init__(parent)
        self._func = func
        self._thread: QThread | None = None

    def run_in_thread(self, thread: QThread | None = None):
        """Move self to a thread and start execution."""
        if thread is None:
            thread = QThread()
        self._thread = thread
        self.moveToThread(thread)

        thread.started.connect(self._do_work)
        self.finished.connect(thread.quit)
        self.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        thread.start()

    def _do_work(self):
        try:
            result = self._func()
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("Worker failed")
            self.error.emit(str(exc))
