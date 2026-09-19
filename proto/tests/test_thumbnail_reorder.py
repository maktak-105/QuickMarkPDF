"""Regression tests for drag & drop page reordering in ThumbnailPanel.

These exercise the reorder *computation* directly (`_compute_new_order`)
rather than simulating real QDropEvent objects, since constructing a
faithful QDropEvent is brittle. Covers the actual bugs that were reported:
dragging within one file worked once but couldn't be reverted, dragging
across files didn't affect the saved page order, and (after the panel was
rewritten from a per-file grouped tree to a flat per-page-tagged list) that
a page's filename tag always follows the page itself regardless of where
it's dragged.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.pdf_editor.pdf.pdf_manager import PDFManager
from src.pdf_editor.ui.thumbnail_panel import ThumbnailPanel


def _make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=300)
    doc.save(str(path))
    doc.close()


class TestThumbnailReorder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.mgr = PDFManager()
        self.panel = ThumbnailPanel()
        self.panel.set_pdf_manager(self.mgr)

    def tearDown(self):
        self.mgr.close_all()
        self.panel.deleteLater()
        self.app.processEvents()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _drag_and_apply(self, dragged_indices, target_row):
        """Simulate one full drag: compute the new order, apply it via
        pdf_manager.reorder_pages, and refresh the list — mirroring what
        MainWindow._on_page_reordered does in response to the real signal.
        """
        new_order = self.panel._compute_new_order(dragged_indices, target_row)
        self.mgr.reorder_pages(new_order)
        self.panel.refresh()
        return new_order

    def test_same_file_swap_can_be_reverted(self):
        """Regression: dragging page 1<->2 within one file used to work once
        but not revert — because the old code read back Qt's native post-drop
        tree instead of computing the order itself.
        """
        pdf = self.tmpdir / "a.pdf"
        _make_pdf(pdf, 3)
        self.mgr.load_pdfs([pdf])
        self.panel.refresh()

        original = [info.original_page_index for info in self.mgr.page_infos]
        self.assertEqual(original, [0, 1, 2])

        # Drag page 0 to just after page 1 (row 2) → expect [1, 0, 2].
        self._drag_and_apply(dragged_indices=[0], target_row=2)
        swapped = [info.original_page_index for info in self.mgr.page_infos]
        self.assertEqual(swapped, [1, 0, 2])

        # Now drag the page currently at flat index 0 (originally page 2) to
        # just after the page at flat index 1 (originally page 1) → should
        # restore the original order, proving the swap is revertible.
        self._drag_and_apply(dragged_indices=[0], target_row=2)
        reverted = [info.original_page_index for info in self.mgr.page_infos]
        self.assertEqual(reverted, original)

    def test_drag_across_files_changes_flat_save_order(self):
        """Dragging a page from file A to a position inside file B's pages
        must be reflected in the flat page order (what gets saved).
        """
        pdf_a = self.tmpdir / "a.pdf"
        pdf_b = self.tmpdir / "b.pdf"
        _make_pdf(pdf_a, 2)
        _make_pdf(pdf_b, 2)
        self.mgr.load_pdfs([pdf_a, pdf_b])
        self.panel.refresh()

        # Flat order is [A0, A1, B0, B1] (source file, original page index).
        sources_before = [
            (info.source_doc_path.name, info.original_page_index) for info in self.mgr.page_infos
        ]
        self.assertEqual(sources_before, [("a.pdf", 0), ("a.pdf", 1), ("b.pdf", 0), ("b.pdf", 1)])

        # Drag A's first page (flat index 0) to the very end (row 4).
        self._drag_and_apply(dragged_indices=[0], target_row=4)

        sources_after = [
            (info.source_doc_path.name, info.original_page_index) for info in self.mgr.page_infos
        ]
        # A0 must now be the last page in the flat (save) order.
        self.assertEqual(sources_after[-1], ("a.pdf", 0))
        self.assertEqual(len(sources_after), 4)

    def test_tag_follows_page_wherever_it_is_dragged(self):
        """Regression (post-rewrite): each page's filename tag is baked from
        its own immutable `source_doc_path`, not a group it's currently
        displayed under, so it must stay correct no matter where the page
        ends up in the flat list — there is no more "snapping back" to a
        group, because there is no group.
        """
        pdf_a = self.tmpdir / "a.pdf"
        pdf_b = self.tmpdir / "b.pdf"
        _make_pdf(pdf_a, 2)
        _make_pdf(pdf_b, 2)
        self.mgr.load_pdfs([pdf_a, pdf_b])
        self.panel.refresh()

        # Drag A's first page (flat index 0) into the middle of B's pages (row 3).
        self._drag_and_apply(dragged_indices=[0], target_row=3)

        # It must still report "a.pdf" as its source — nothing re-tags it.
        moved_page_idx = self.panel.item(2).data(Qt.UserRole)
        self.assertEqual(self.mgr.page_infos[moved_page_idx].source_doc_path.name, "a.pdf")

        # Closing "b.pdf" must NOT remove the page that only passed through
        # that area of the list — it's still tagged/sourced from a.pdf.
        self.mgr.close_document(pdf_b)
        remaining = sorted(info.source_doc_path.name for info in self.mgr.page_infos)
        self.assertEqual(remaining, ["a.pdf", "a.pdf"])

    def test_multi_page_drag_preserves_relative_order(self):
        pdf = self.tmpdir / "a.pdf"
        _make_pdf(pdf, 4)
        self.mgr.load_pdfs([pdf])
        self.panel.refresh()

        # Drag pages [0, 2] (original relative order 0 before 2) to the end.
        self._drag_and_apply(dragged_indices=[0, 2], target_row=4)
        result = [info.original_page_index for info in self.mgr.page_infos]
        self.assertEqual(result, [1, 3, 0, 2])


if __name__ == "__main__":
    unittest.main()
