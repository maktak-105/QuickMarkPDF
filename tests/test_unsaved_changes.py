"""Regression tests for unsaved-change tracking in the main window."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtWidgets import QApplication

from src.pdf_editor.ui.main_window import MainWindow


class TestUnsavedChanges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window._run_in_background = (
            lambda operation, on_success, **_kwargs: on_success(operation())
        )

    def tearDown(self):
        self.window.pdf_manager.close_all()
        self.window.deleteLater()
        self.app.processEvents()

    def _create_pdf(self, directory: str) -> Path:
        path = Path(directory) / "view-only.pdf"
        document = fitz.open()
        document.new_page()
        document.save(path)
        document.close()
        return path

    def test_opening_pdf_does_not_mark_document_dirty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.window.open_pdfs([self._create_pdf(directory)])
            self.assertFalse(self.window._is_dirty)
            self.window.pdf_manager.close_all()

    def test_opening_another_pdf_does_not_clear_existing_edits(self):
        self.window._mark_dirty()

        with tempfile.TemporaryDirectory() as directory:
            self.window.open_pdfs([self._create_pdf(directory)])
            self.assertTrue(self.window._is_dirty)
            self.window.pdf_manager.close_all()


if __name__ == "__main__":
    unittest.main()
