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

    def _create_md(self, directory: str) -> Path:
        path = Path(directory) / "note.md"
        path.write_text("# Hello\n", encoding="utf-8")
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

    def test_opening_markdown_with_unsaved_pdf_changes_asks_for_confirmation(self):
        """Regression: opening a Markdown file used to silently discard an
        unsaved PDF editing session (pdf_manager.close_all() with no check).
        """
        if self.window.markdown_view is None:
            self.skipTest("QtWebEngine not available in this environment")

        self.window._mark_dirty()
        asked = []
        self.window._confirm_discard_pdf_changes = lambda question: asked.append(question) or False

        with tempfile.TemporaryDirectory() as directory:
            self.window._load_markdown_document(self._create_md(directory))

        self.assertEqual(len(asked), 1)
        # Declined discard: Markdown must not have loaded, PDF state untouched.
        self.assertIsNone(self.window.current_markdown_document)
        self.assertTrue(self.window._is_dirty)

    def test_opening_markdown_proceeds_when_discard_confirmed(self):
        if self.window.markdown_view is None:
            self.skipTest("QtWebEngine not available in this environment")

        self.window._mark_dirty()
        self.window._confirm_discard_pdf_changes = lambda question: True

        with tempfile.TemporaryDirectory() as directory:
            self.window._load_markdown_document(self._create_md(directory))

        self.assertIsNotNone(self.window.current_markdown_document)

    def test_confirm_discard_skips_dialog_when_not_dirty(self):
        self.assertFalse(self.window._is_dirty)
        self.assertTrue(self.window._confirm_discard_pdf_changes("question?"))


if __name__ == "__main__":
    unittest.main()
