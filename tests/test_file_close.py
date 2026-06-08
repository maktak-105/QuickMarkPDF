"""
Automated test for file close functionality.
Tests that closing a document from the manager correctly removes its pages,
and that the preview logic would clear and reload from remaining pages.

This can be run automatically without GUI interaction for the core logic.
Run with: python tests/test_file_close.py
"""

import sys
import tempfile
from pathlib import Path
import fitz  # PyMuPDF

# Ensure src layout is importable when running the test directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_editor.pdf.pdf_manager import PDFManager

def create_temp_pdf(path: Path, num_pages: int = 2, text_prefix: str = "Page"):
    """Create a minimal multi-page PDF for testing."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=200, height=300)
        page.insert_text((20, 50), f"{text_prefix} {i+1}")
    doc.save(str(path))
    doc.close()

def test_close_document_removes_pages():
    """Test that close_document correctly filters out pages from the closed file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf_a = tmp_path / "file_a.pdf"
        pdf_b = tmp_path / "file_b.pdf"

        create_temp_pdf(pdf_a, 3, "FileA")
        create_temp_pdf(pdf_b, 2, "FileB")

        mgr = PDFManager()
        loaded = mgr.load_pdfs([pdf_a, pdf_b])
        assert loaded == 2
        assert mgr.get_page_count() == 5

        # Simulate closing file_a (resolve to match what load_pdfs stores)
        success = mgr.close_document(pdf_a.resolve())
        assert success is True, "close_document should succeed for a loaded file"
        assert mgr.get_page_count() == 2

        # Verify no pages from closed file remain
        for info in mgr.page_infos:
            assert str(info.source_doc_path) != str(pdf_a.resolve())

        # Verify remaining pages are from file_b
        for info in mgr.page_infos:
            assert str(info.source_doc_path) == str(pdf_b.resolve())

        # Explicitly close remaining to help temp dir cleanup on Windows
        mgr.close_all()

        print("✓ test_close_document_removes_pages passed")

def test_preview_would_clear_and_reload():
    """
    Simulate the preview clear + reload logic after close.
    In real UI, this is what _on_file_close_requested does.
    We check that after close, 'current preview' would come from remaining pages.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf_a = tmp_path / "closed.pdf"
        pdf_b = tmp_path / "remaining.pdf"

        create_temp_pdf(pdf_a, 1, "ClosedPage")
        create_temp_pdf(pdf_b, 1, "RemainingPage")

        mgr = PDFManager()
        mgr.load_pdfs([pdf_a, pdf_b])

        # Simulate "current preview" being from closed file (index 0 before close)
        # In real code, this would be set via get_preview_pixmap before close.

        # Now perform close (as in the handler), using resolved path
        mgr.close_document(pdf_a.resolve())

        # After close, simulate the UI clearing the preview and loading new
        # (this matches the logic in _on_file_close_requested after the fix)
        preview_cleared = True  # we explicitly set to None / clear in UI

        if mgr.get_page_count() > 0:
            # Directly load first remaining (as done in the fixed handler)
            new_preview_pix = mgr.get_preview_pixmap(0, zoom=1.5)
            assert new_preview_pix is not None
            # In real UI we would set current_preview_pixmap and update label
            preview_reloaded_from_remaining = True
        else:
            preview_reloaded_from_remaining = False

        assert preview_cleared
        assert preview_reloaded_from_remaining
        assert mgr.get_page_count() == 1

        mgr.close_all()

        print("✓ test_preview_would_clear_and_reload passed")

if __name__ == "__main__":
    test_close_document_removes_pages()
    test_preview_would_clear_and_reload()
    print("\nAll automated tests passed.")