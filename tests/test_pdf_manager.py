"""
Basic tests for PDFManager.
Run with:
    python -m unittest tests.test_pdf_manager
"""
import unittest
from pathlib import Path
import tempfile
import os

import fitz

from src.pdf_editor.pdf.pdf_manager import PDFManager


def _make_minimal_pdf(path: Path, pages: int = 2) -> None:
    """Create a tiny multi-page PDF for testing."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=200, height=300)
        page.insert_text((20, 40), f"Page {i+1}")
    doc.save(str(path))
    doc.close()


def _make_encrypted_pdf(path: Path, password: str) -> None:
    """Create a tiny password-protected PDF for testing."""
    doc = fitz.open()
    doc.new_page(width=200, height=300)
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    doc.close()


class TestPDFManagerBasic(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.pdf1 = self.tmpdir / "doc1.pdf"
        self.pdf2 = self.tmpdir / "doc2.pdf"
        _make_minimal_pdf(self.pdf1, 3)
        _make_minimal_pdf(self.pdf2, 2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_and_count(self):
        mgr = PDFManager()
        result = mgr.load_pdfs([self.pdf1, self.pdf2])
        self.assertEqual(result.loaded_count, 2)
        self.assertEqual(result.password_required, [])
        self.assertEqual(result.duplicate_files, [])
        self.assertEqual(mgr.get_page_count(), 5)

    def test_loading_an_already_open_file_again_is_skipped(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        self.assertEqual(mgr.get_page_count(), 3)

        result = mgr.load_pdfs([self.pdf1, self.pdf2])
        self.assertEqual(result.loaded_count, 1)  # only doc2.pdf actually loaded
        self.assertEqual(result.duplicate_files, [self.pdf1.resolve()])
        self.assertEqual(mgr.get_page_count(), 5)  # doc1's 3 pages weren't duplicated

    def test_selecting_the_same_file_twice_in_one_call_is_deduped(self):
        mgr = PDFManager()
        result = mgr.load_pdfs([self.pdf1, self.pdf1, self.pdf2])
        self.assertEqual(result.loaded_count, 2)
        self.assertEqual(result.duplicate_files, [self.pdf1.resolve()])
        self.assertEqual(mgr.get_page_count(), 5)  # doc1 loaded once (3) + doc2 (2)

    def test_loading_a_second_file_does_not_invalidate_first_files_pages(self):
        """Regression: PyMuPDF's insert_pdf() invalidates every previously
        fetched Page wrapper object for the target document (not just ones
        related to the newly inserted content). Loading files in two separate
        calls (or even within the same call's loop) used to leave the first
        batch's `all_pages` entries pointing at dead wrappers, crashing with
        "AssertionError: page is None" as soon as e.g. rotation was read.
        """
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        first_batch_pages = list(mgr.all_pages)
        mgr.rotate_page(0, 90)

        mgr.load_pdfs([self.pdf2])  # second, separate load call

        # Pages from the very first load must still be usable and correct.
        self.assertEqual(mgr.all_pages[0].rotation, 90)
        for page in mgr.all_pages[:3]:
            page.rotation  # must not raise "page is None"
        self.assertEqual(mgr.get_page_count(), 5)

    def test_reorder_and_save(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        # Reverse order
        mgr.reorder_pages([2, 1, 0])
        out = self.tmpdir / "reordered.pdf"
        ok = mgr.save_as(out)
        self.assertTrue(ok)
        self.assertTrue(out.exists())

    def test_rotate_and_save(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        mgr.rotate_page(0, 90)
        out = self.tmpdir / "rotated.pdf"
        ok = mgr.save_as(out)
        self.assertTrue(ok)

    def test_delete_pages(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])  # 3 pages
        mgr.delete_pages([1])
        self.assertEqual(mgr.get_page_count(), 2)
        # Remaining page_infos must be renumbered contiguously
        self.assertEqual([info.page_number for info in mgr.page_infos], [0, 1])
        # The original page 3 (original_page_index=2) should now be at flat index 1
        self.assertEqual(mgr.page_infos[1].original_page_index, 2)

    def test_delete_pages_multiple_and_out_of_range(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])  # 3 pages
        mgr.delete_pages([0, 2, 99])  # 99 is out of range and should be ignored
        self.assertEqual(mgr.get_page_count(), 1)
        self.assertEqual(mgr.page_infos[0].original_page_index, 1)

    def test_can_overwrite_source_only_with_single_file(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        self.assertTrue(mgr.can_overwrite_source())

        mgr.load_pdfs([self.pdf2])
        self.assertFalse(mgr.can_overwrite_source())
        mgr.close_all()

    def test_overwrite_source_replaces_file_and_reloads(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        mgr.rotate_page(0, 90)

        ok = mgr.overwrite_source()
        self.assertTrue(ok)
        self.assertEqual(mgr.get_page_count(), 3)
        self.assertEqual(mgr.all_pages[0].rotation, 90)

        # No leftover temp files in the directory
        leftovers = [p for p in self.tmpdir.iterdir() if ".tmp_" in p.name]
        self.assertEqual(leftovers, [])

        # Re-open from disk independently to confirm the change was actually persisted
        mgr.close_all()
        doc2 = fitz.open(str(self.pdf1))
        self.assertEqual(doc2[0].rotation, 90)
        doc2.close()

    def test_export_images_with_clip(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])

        # Define crop rect (100x100 points)
        clip_rect = fitz.Rect(10, 10, 110, 110)
        out_dir = self.tmpdir / "exported_images"

        success_cnt, attempted_cnt, errors = mgr.export_pages_to_images(
            indices=[0],
            output_dir=out_dir,
            fmt="png",
            dpi=72,  # at 72 DPI, 1 point = 1 pixel
            prefix="test_clip",
            clip=clip_rect
        )

        self.assertEqual(success_cnt, 1)
        self.assertEqual(attempted_cnt, 1)
        self.assertEqual(len(errors), 0)

        img_path = out_dir / "test_clip_0001.png"
        self.assertTrue(img_path.exists())

        # Verify image dimensions using Pillow
        from PIL import Image
        with Image.open(img_path) as img:
            self.assertEqual(img.size, (100, 100))


class TestPasswordProtectedPdf(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.locked = self.tmpdir / "locked.pdf"
        _make_encrypted_pdf(self.locked, "secret123")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_without_password_reports_password_required(self):
        mgr = PDFManager()
        result = mgr.load_pdfs([self.locked])
        self.assertEqual(result.loaded_count, 0)
        self.assertEqual(result.password_required, [self.locked.resolve()])
        self.assertEqual(mgr.get_page_count(), 0)

    def test_load_with_wrong_password_reports_password_required(self):
        mgr = PDFManager()
        result = mgr.load_pdfs([self.locked], passwords={self.locked: "wrong"})
        self.assertEqual(result.loaded_count, 0)
        self.assertEqual(result.password_required, [self.locked.resolve()])

    def test_load_with_correct_password_succeeds(self):
        mgr = PDFManager()
        result = mgr.load_pdfs([self.locked], passwords={self.locked: "secret123"})
        self.assertEqual(result.loaded_count, 1)
        self.assertEqual(result.password_required, [])
        self.assertEqual(mgr.get_page_count(), 1)
        mgr.close_all()


class TestUndo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.pdf1 = self.tmpdir / "doc1.pdf"
        self.pdf2 = self.tmpdir / "doc2.pdf"
        _make_minimal_pdf(self.pdf1, 3)
        _make_minimal_pdf(self.pdf2, 2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_undo_available_initially(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        self.assertFalse(mgr.can_undo())
        self.assertFalse(mgr.undo())

    def test_undo_reorder(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        original = [info.original_page_index for info in mgr.page_infos]

        mgr.reorder_pages([2, 1, 0])
        self.assertNotEqual([info.original_page_index for info in mgr.page_infos], original)

        self.assertTrue(mgr.undo())
        self.assertEqual([info.original_page_index for info in mgr.page_infos], original)
        self.assertFalse(mgr.can_undo())

    def test_undo_rotate_restores_actual_rotation(self):
        """Regression: naively restoring the page list doesn't undo rotation,
        because fitz.Page objects are mutated in place by set_rotation().
        """
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])

        mgr.rotate_pages([0, 1], 90)
        self.assertEqual([p.rotation for p in mgr.all_pages], [90, 90, 0])

        self.assertTrue(mgr.undo())
        self.assertEqual([p.rotation for p in mgr.all_pages], [0, 0, 0])

    def test_multi_page_rotate_is_a_single_undo_step(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])

        mgr.rotate_pages([0, 1, 2], 90)
        mgr.undo()
        self.assertEqual([p.rotation for p in mgr.all_pages], [0, 0, 0])
        self.assertFalse(mgr.can_undo())

    def test_undo_delete_pages(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])

        mgr.delete_pages([1])
        self.assertEqual(mgr.get_page_count(), 2)

        self.assertTrue(mgr.undo())
        self.assertEqual(mgr.get_page_count(), 3)
        self.assertEqual([info.original_page_index for info in mgr.page_infos], [0, 1, 2])

    def test_undo_file_close_restores_in_memory_edits(self):
        """Since all pages live in one long-lived working_doc, undoing a file
        close is now a plain state-snapshot restore — unlike the old "reopen
        from disk" implementation, in-memory-only edits (e.g. rotation) made
        before the close are preserved, not lost.
        """
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1, self.pdf2])
        self.assertEqual(mgr.get_page_count(), 5)

        mgr.rotate_page(0, 90)  # unsaved edit on a page belonging to pdf1
        mgr.close_document(self.pdf1.resolve())
        self.assertEqual(mgr.get_page_count(), 2)

        self.assertTrue(mgr.undo())
        self.assertEqual(mgr.get_page_count(), 5)
        self.assertEqual(mgr.all_pages[0].rotation, 90)
        mgr.close_all()

    def test_undo_stack_capped(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])

        for _ in range(mgr._UNDO_CAP + 5):
            mgr.rotate_pages([0], 90)

        undo_count = 0
        while mgr.undo():
            undo_count += 1
        self.assertEqual(undo_count, mgr._UNDO_CAP)

    def test_close_all_clears_undo_history(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.pdf1])
        mgr.rotate_pages([0], 90)
        self.assertTrue(mgr.can_undo())

        mgr.close_all()
        self.assertFalse(mgr.can_undo())


if __name__ == "__main__":
    unittest.main()
