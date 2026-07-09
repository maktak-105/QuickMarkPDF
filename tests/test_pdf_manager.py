"""
Basic tests for PDFManager with emphasis on preserving Header/Footer behavior.
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
        loaded = mgr.load_pdfs([self.pdf1, self.pdf2])
        self.assertEqual(loaded, 2)
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


class TestHeaderFooterBehavior(unittest.TestCase):
    """These tests exist to protect the current (destructive) HF specification."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.src = self.tmpdir / "source.pdf"
        _make_minimal_pdf(self.src, 2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_header_footer_bakes_text(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.src])

        mgr.add_header_footer(
            header_enabled=True,
            header_text="CONFIDENTIAL",
            footer_page_num=True,
        )

        # After add, the page should contain the text when rendered
        pix = mgr.get_preview_pixmap(0, zoom=1.0)
        self.assertIsNotNone(pix)

        # Save and re-open to verify text is persisted in the PDF content
        out = self.tmpdir / "with_hf.pdf"
        self.assertTrue(mgr.save_as(out))

        doc2 = fitz.open(str(out))
        page0 = doc2[0]
        text = page0.get_text()
        self.assertIn("CONFIDENTIAL", text)
        self.assertIn("1 / 2", text)
        doc2.close()

    def test_remove_header_footer_restores_original_content(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.src])

        # Apply HF
        mgr.add_header_footer(header_enabled=True, header_text="DRAFT")

        # Remove should bring back original content (by reloading from disk + re-applying rotations)
        mgr.remove_header_footer()

        out = self.tmpdir / "after_remove.pdf"
        self.assertTrue(mgr.save_as(out))

        doc2 = fitz.open(str(out))
        text = doc2[0].get_text()
        self.assertNotIn("DRAFT", text)
        doc2.close()

    def test_remove_preserves_rotation(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.src])

        mgr.rotate_page(0, 180)
        mgr.add_header_footer(header_enabled=True, header_text="ROT+HF")
        mgr.remove_header_footer()

        # After remove, rotation should still be 180
        self.assertEqual(mgr.all_pages[0].rotation, 180)

    def test_add_header_footer_renders_japanese_at_consistent_size(self):
        """Full-width (Japanese) and half-width characters must render at the same
        glyph height. Using fontname="helv" (Latin-only) collapses unsupported
        Japanese glyphs to tiny placeholder dots instead of raising an error, so
        this must be checked via actual rendered glyph bounding boxes, not just
        text-extraction presence.
        """
        mgr = PDFManager()
        mgr.load_pdfs([self.src])

        mgr.add_header_footer(header_enabled=True, header_text="ABC完了123")

        out = self.tmpdir / "with_japanese_hf.pdf"
        self.assertTrue(mgr.save_as(out))

        doc2 = fitz.open(str(out))
        raw = doc2[0].get_text("rawdict")
        heights = {}
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    for ch in span["chars"]:
                        heights[ch["c"]] = ch["bbox"][3] - ch["bbox"][1]
        doc2.close()

        self.assertIn("A", heights)
        self.assertIn("完", heights)
        # Japanese glyph height must be close to the half-width glyph height
        # (previously it collapsed to a tiny placeholder, i.e. a small fraction of it).
        self.assertGreater(heights["完"], heights["A"] * 0.5)

    def test_add_header_footer_can_be_reapplied_without_stacking(self):
        """Re-applying HF with different settings must not leave the old text baked in."""
        mgr = PDFManager()
        mgr.load_pdfs([self.src])

        mgr.add_header_footer(header_enabled=True, header_text="DRAFT", footer_page_num=True)
        mgr.add_header_footer(header_enabled=True, header_text="FINAL", footer_page_num=True)

        out = self.tmpdir / "reapplied_hf.pdf"
        self.assertTrue(mgr.save_as(out))

        doc2 = fitz.open(str(out))
        page0_text = doc2[0].get_text()
        self.assertIn("FINAL", page0_text)
        self.assertNotIn("DRAFT", page0_text)
        # Page-number footer must appear exactly once, not duplicated across both applies.
        self.assertEqual(page0_text.count("1 / 2"), 1)
        doc2.close()

    def test_export_images_with_clip(self):
        mgr = PDFManager()
        mgr.load_pdfs([self.src])

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


if __name__ == "__main__":
    unittest.main()
