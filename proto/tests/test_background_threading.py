"""Regression test for a critical threading bug in MainWindow._run_in_background.

Background: Worker.finished/error are emitted from a QThread. Connecting them
directly to a plain Python closure (rather than a bound QObject method) causes
PySide6 to invoke the slot directly on the EMITTING (background) thread instead
of queuing it back to the main thread, since Qt can only auto-detect a
cross-thread connection when the receiver has known QObject thread affinity.
That bug made every background-completed callback (thumbnail refresh, QPixmap/
QImage construction, etc.) run on a background thread — a Qt threading
violation that surfaced as an app freeze followed by a crash when loading a PDF.

This test exercises the REAL open_pdfs() -> Worker -> _on_worker_finished path
(no monkeypatching of _run_in_background itself) and asserts the GUI-touching
code actually runs on the main thread.
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from src.pdf_editor.ui.main_window import MainWindow
from src.pdf_editor.ui.thumbnail_panel import ThumbnailPanel


def _make_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=300)
    doc.save(str(path))
    doc.close()


class TestBackgroundThreading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.window.pdf_manager.close_all()
        self.window.deleteLater()
        self.app.processEvents()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_open_pdfs_completion_runs_gui_code_on_main_thread(self):
        pdf_path = self.tmpdir / "diag.pdf"
        _make_pdf(pdf_path, 3)

        seen_threads = []
        is_main_qthread = []

        # Probe via the class (not the instance) so ThumbnailPanel.refresh stays
        # a genuine bound method for Qt's own purposes — only observe from here.
        orig_refresh = ThumbnailPanel.refresh

        def probed_refresh(self_panel):
            seen_threads.append(threading.current_thread())
            is_main_qthread.append(QThread.currentThread() is self.app.thread())
            result = orig_refresh(self_panel)
            self.app.quit()  # stop as soon as we've observed the completion
            return result

        ThumbnailPanel.refresh = probed_refresh
        try:
            self.window.open_pdfs([str(pdf_path)])

            # Drive the event loop until the background worker completes (or a
            # generous timeout elapses, which would indicate a hang/regression).
            QTimer.singleShot(8000, self.app.quit)
            self.app.exec()
        finally:
            ThumbnailPanel.refresh = orig_refresh

        self.assertTrue(seen_threads, "ThumbnailPanel.refresh() was never called — load did not complete")
        self.assertEqual(seen_threads[0], threading.main_thread())
        self.assertTrue(is_main_qthread[0])
        self.assertEqual(self.window.pdf_manager.get_page_count(), 3)
        self.assertEqual(self.window.thumbnail_panel.count(), 3)


if __name__ == "__main__":
    unittest.main()
