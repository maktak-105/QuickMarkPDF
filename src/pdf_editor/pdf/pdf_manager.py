"""
PDF Manager - Core PDF handling using PyMuPDF (fitz)
Responsible for loading, reordering, rotating, and rendering pages.
"""
from __future__ import annotations
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class PageInfo:
    """Lightweight info about a single page for the UI."""
    page_number: int          # 0-based index in all_pages
    source_doc_path: Path
    original_page_index: int  # index inside its original document


class PDFDocument:
    """Wrapper for one PDF file."""

    def __init__(self, path: Path):
        self.path = path
        self.doc: Optional[fitz.Document] = None
        self.pages: List[fitz.Page] = []

    def open(self) -> bool:
        try:
            self.doc = fitz.open(str(self.path))
            self.pages = [self.doc[i] for i in range(len(self.doc))]
            return True
        except Exception as e:
            print(f"[PDF] Failed to open {self.path}: {e}")
            return False

    def close(self):
        if self.doc:
            self.doc.close()
        self.doc = None
        self.pages.clear()


class PDFManager:
    """Main controller for all PDF pages across multiple documents."""

    def __init__(self):
        self.documents: List[PDFDocument] = []
        self.all_pages: List[fitz.Page] = []
        self.page_infos: List[PageInfo] = []

    def load_pdfs(self, paths: List[Path]) -> int:
        """Load one or more PDF files. Returns number of successfully loaded files."""
        loaded_count = 0
        for path in paths:
            doc = PDFDocument(path)
            if doc.open():
                start_index = len(self.all_pages)
                self.documents.append(doc)
                self.all_pages.extend(doc.pages)

                for i, page in enumerate(doc.pages):
                    self.page_infos.append(PageInfo(
                        page_number=start_index + i,
                        source_doc_path=path,
                        original_page_index=i
                    ))
                loaded_count += 1
        return loaded_count

    def get_page_count(self) -> int:
        return len(self.all_pages)

    def reorder_pages(self, new_order: List[int]):
        """Reorder pages according to new_order (list of old indices)."""
        if len(new_order) != len(self.all_pages):
            raise ValueError("new_order length must match page count")

        self.all_pages = [self.all_pages[i] for i in new_order]
        self.page_infos = [self.page_infos[i] for i in new_order]

        # Update page_number
        for idx, info in enumerate(self.page_infos):
            info.page_number = idx

    def rotate_page(self, page_index: int, degrees: int):
        """Rotate a single page (90, 180, 270, or -90 etc.)."""
        if not 0 <= page_index < len(self.all_pages):
            return
        page = self.all_pages[page_index]
        page.set_rotation((page.rotation + degrees) % 360)

    def get_thumbnail_pixmap(self, page_index: int, max_size: int = 200) -> Optional[fitz.Pixmap]:
        """Generate a thumbnail pixmap for the given page."""
        if not 0 <= page_index < len(self.all_pages):
            return None
        page = self.all_pages[page_index]
        mat = fitz.Matrix(0.5, 0.5)  # lower res for thumbnail
        pix = page.get_pixmap(matrix=mat)
        # Scale down if needed
        if max(pix.width, pix.height) > max_size:
            factor = max_size / max(pix.width, pix.height)
            mat = fitz.Matrix(factor, factor)
            pix = page.get_pixmap(matrix=mat)
        return pix

    def get_preview_pixmap(self, page_index: int, zoom: float = 1.5) -> Optional[fitz.Pixmap]:
        """Generate higher quality pixmap for preview."""
        if not 0 <= page_index < len(self.all_pages):
            return None
        page = self.all_pages[page_index]
        mat = fitz.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=mat)

    def close_all(self):
        for doc in self.documents:
            doc.close()
        self.documents.clear()
        self.all_pages.clear()
        self.page_infos.clear()

    # =====================
    # Header & Footer
    # =====================
    def add_header_footer(
        self,
        header_text: str = "",
        show_page_number: bool = True,
        font_size: int = 11,
        margin_bottom: int = 30,
        margin_top: int = 25,
    ):
        """
        Add header (title) and footer (page number) to all pages.
        Text is inserted directly onto the page objects.
        """
        total_pages = self.get_page_count()
        if total_pages == 0:
            return

        for i, page in enumerate(self.all_pages):
            page_number = i + 1
            rect = page.rect

            # --- Header (Title) ---
            if header_text:
                text = header_text
                text_width = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
                x = (rect.width - text_width) / 2
                y = margin_top + font_size   # baseline adjustment
                page.insert_text(
                    (x, y),
                    text,
                    fontname="helv",
                    fontsize=font_size,
                    color=(0.15, 0.15, 0.15)
                )

            # --- Footer (Page Number) ---
            if show_page_number:
                text = f"- {page_number} / {total_pages} -"
                text_width = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
                x = (rect.width - text_width) / 2
                y = rect.height - margin_bottom
                page.insert_text(
                    (x, y),
                    text,
                    fontname="helv",
                    fontsize=font_size,
                    color=(0.15, 0.15, 0.15)
                )

    # =====================
    # Save / Export
    # =====================
    def save_as(self, output_path: Path) -> bool:
        """
        Save the current state (all pages with modifications) as a new PDF.
        This effectively merges + applies all edits (rotation, header/footer, reordering).
        """
        if not self.all_pages:
            return False

        try:
            # Create a new document and insert all current pages
            new_doc = fitz.open()

            for page in self.all_pages:
                # Insert the page (with its current rotation and any text we added)
                new_doc.insert_pdf(page.parent, from_page=page.number, to_page=page.number)

            new_doc.save(str(output_path))
            new_doc.close()
            return True
        except Exception as e:
            print(f"[Save] Failed: {e}")
            return False

    def save_selected_pages(self, indices: list[int], output_path: Path) -> bool:
        """Save only the specified pages (by current flat index) to a new PDF, in the given order."""
        if not indices or not self.all_pages:
            return False

        try:
            new_doc = fitz.open()
            for idx in indices:
                if 0 <= idx < len(self.all_pages):
                    page = self.all_pages[idx]
                    new_doc.insert_pdf(page.parent, from_page=page.number, to_page=page.number)

            if len(new_doc) == 0:
                new_doc.close()
                return False

            new_doc.save(str(output_path))
            new_doc.close()
            return True
        except Exception as e:
            print(f"[Split] Failed: {e}")
            return False
