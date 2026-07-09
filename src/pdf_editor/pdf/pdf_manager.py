"""
PDF Manager - Core PDF handling using PyMuPDF (fitz)
Responsible for loading, reordering, rotating, and rendering pages.
"""
from __future__ import annotations
import logging
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
            logger.error("Failed to open %s: %s", self.path, e)
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
        self._thumb_cache: dict = {}  # (page_id, max_size, rotation) → fitz.Pixmap

    def load_pdfs(self, paths: List[Path]) -> int:
        """Load one or more PDF files. Returns number of successfully loaded files."""
        loaded_count = 0
        for path in paths:
            resolved_path = path.resolve()
            doc = PDFDocument(resolved_path)
            if doc.open():
                start_index = len(self.all_pages)
                self.documents.append(doc)
                self.all_pages.extend(doc.pages)

                for i, page in enumerate(doc.pages):
                    self.page_infos.append(PageInfo(
                        page_number=start_index + i,
                        source_doc_path=resolved_path,
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
        pid = id(page)
        self._thumb_cache = {k: v for k, v in self._thumb_cache.items() if k[0] != pid}
        page.set_rotation((page.rotation + degrees) % 360)

    def get_thumbnail_pixmap(self, page_index: int, max_size: int = 200) -> Optional[fitz.Pixmap]:
        """Generate a thumbnail pixmap for the given page (cached)."""
        if not 0 <= page_index < len(self.all_pages):
            return None
        page = self.all_pages[page_index]
        cache_key = (id(page), max_size, page.rotation)

        if cache_key in self._thumb_cache:
            return self._thumb_cache[cache_key]

        # Compute the exact scale factor in one shot — no double render
        page_max = max(page.rect.width, page.rect.height)
        factor = max_size / page_max if page_max > max_size else 1.0
        pix = page.get_pixmap(matrix=fitz.Matrix(factor, factor))

        self._thumb_cache[cache_key] = pix
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
        self._thumb_cache.clear()

    # =====================
    # Header & Footer
    # =====================

    @staticmethod
    def _text_x(text: str, page_width: float, align: str, font_size: int, margin: float) -> float:
        """Return the x coordinate for text given alignment."""
        tw = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
        if align == "left":
            return margin
        if align == "right":
            return page_width - tw - margin
        return (page_width - tw) / 2  # center

    def add_header_footer(
        self,
        header_enabled: bool = False,
        header_text: str = "",
        header_align: str = "center",
        footer_page_num: bool = False,
        footer_page_num_align: str = "center",
        footer_text_enabled: bool = False,
        footer_text: str = "",
        footer_text_align: str = "center",
        font_size: int = 10,
        margin: int = 25,
    ):
        """Insert header and/or footer text directly onto each page.
        Footer page-number and footer text are rendered on separate lines to avoid overlap.

        Always starts from a clean (no previously-inserted header/footer) state, so calling
        this repeatedly with different settings never stacks old text under new text.
        """
        total = self.get_page_count()
        if total == 0:
            return

        # Wipe any previously-inserted header/footer text before applying the new settings,
        # so re-applying with different text/alignment never draws on top of the old text.
        self._reload_pages_from_disk()

        h_text = header_text.strip() if header_enabled else ""
        f_num = footer_page_num
        f_text = footer_text.strip() if footer_text_enabled else ""

        if not h_text and not f_num and not f_text:
            return

        self._thumb_cache.clear()

        line_gap = font_size + 3  # vertical distance between footer lines

        for i, page in enumerate(self.all_pages):
            rect = page.rect

            if h_text:
                x = self._text_x(h_text, rect.width, header_align, font_size, margin)
                page.insert_text((x, margin + font_size), h_text,
                                 fontname="helv", fontsize=font_size, color=(0.15, 0.15, 0.15))

            # Build footer lines bottom-up: page-number is always the lowest line
            # so it never overlaps with the custom text line above it.
            footer_lines = []  # each item: (text, align)
            if f_num:
                footer_lines.append((f"- {i + 1} / {total} -", footer_page_num_align))
            if f_text:
                footer_lines.append((f_text, footer_text_align))

            for row, (line_text, align) in enumerate(footer_lines):
                x = self._text_x(line_text, rect.width, align, font_size, margin)
                y = rect.height - margin - row * line_gap
                page.insert_text((x, y), line_text,
                                 fontname="helv", fontsize=font_size, color=(0.15, 0.15, 0.15))

    def remove_header_footer(self):
        """Reload all pages from disk to erase inserted text, then re-apply stored rotations."""
        self._reload_pages_from_disk()

    def _reload_pages_from_disk(self):
        """Reload all pages from their source documents, discarding any inserted
        header/footer text, but re-applying rotations the user had set.

        Shared by `remove_header_footer` (explicit removal) and `add_header_footer`
        (implicit reset before re-applying, so repeated calls never stack text).
        """
        if not self.documents:
            return

        # Save accumulated rotations before wiping page objects
        rotations = [page.rotation for page in self.all_pages]

        # Re-open each source document from disk (fresh, no inserted text)
        for doc in self.documents:
            doc.close()
            doc.open()

        # Rebuild all_pages in the current page_infos order
        doc_by_path = {doc.path: doc for doc in self.documents}
        self.all_pages = []
        for info in self.page_infos:
            src = doc_by_path.get(info.source_doc_path)
            if src and 0 <= info.original_page_index < len(src.pages):
                self.all_pages.append(src.pages[info.original_page_index])

        # Re-apply rotations that the user had set
        for page, rot in zip(self.all_pages, rotations):
            if rot != page.rotation:
                page.set_rotation(rot)

        self._thumb_cache.clear()

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
            logger.error("Save failed: %s", e)
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
            logger.error("Split failed: %s", e)
            return False

    # =====================
    # Image Export (PNG/JPG)
    # =====================

    def export_pages_to_images(
        self,
        indices: Optional[List[int]] = None,
        output_dir: Path = Path("."),
        fmt: str = "png",
        dpi: int = 150,
        jpeg_quality: int = 90,
        prefix: str = "page",
        clip: Optional[fitz.Rect] = None,
    ) -> Tuple[int, int, List[str]]:
        """Export pages (all or specified indices in order) to image files.

        Uses current page state (rotation + any header/footer already applied).
        PNG is lossless; JPEG uses the provided quality (1-100).
        File names are zero-padded sequential based on export order: {prefix}_0001.png etc.
        Existing files are auto-renamed to avoid overwrite.

        Returns: (success_count, attempted_count, error_messages)
        """
        if indices is None:
            indices = list(range(len(self.all_pages)))
        if not indices or not self.all_pages:
            return 0, 0, []

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        ext = "png" if fmt.lower() == "png" else "jpg"
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        success = 0
        errors: List[str] = []

        for seq, page_idx in enumerate(indices, start=1):
            if not (0 <= page_idx < len(self.all_pages)):
                errors.append(f"無効なページインデックス: {page_idx}")
                continue
            page = self.all_pages[page_idx]
            try:
                pix = page.get_pixmap(matrix=mat, alpha=False, clip=clip)

                # Name by export sequence (not original index) so output is naturally ordered
                base = f"{prefix}_{seq:04d}" if prefix and prefix.strip() else f"{seq:04d}"
                out_path = output_dir / f"{base}.{ext}"

                # De-dupe if target exists
                if out_path.exists():
                    k = 1
                    while out_path.exists():
                        out_path = output_dir / f"{base}_{k}.{ext}"
                        k += 1

                if ext == "png":
                    pix.save(str(out_path))
                else:
                    # JPEG bytes with quality
                    jpg_data = pix.tobytes("jpg", jpg_quality=jpeg_quality)
                    out_path.write_bytes(jpg_data)

                success += 1
            except Exception as e:
                errors.append(f"p.{page_idx + 1}: {e}")

        return success, len(indices), errors

    def get_source_dir_for_pages(self, indices: list[int]) -> Path:
        """Return the directory of the original file for the first page in indices.
        Falls back to current working directory if unknown.
        """
        if not indices or not self.page_infos:
            return Path.cwd()
        idx = indices[0]
        if 0 <= idx < len(self.page_infos):
            return self.page_infos[idx].source_doc_path.parent
        return Path.cwd()

    def suggest_export_basename(self, indices: list[int], for_images: bool = False) -> str:
        """Suggest a sensible base name (no extension) for exported file(s) based on source docs."""
        if not indices or not self.page_infos:
            return "selected"
        infos = []
        for i in indices:
            if 0 <= i < len(self.page_infos):
                infos.append(self.page_infos[i])
        if not infos:
            return "selected"
        unique_src = {inf.source_doc_path for inf in infos}
        if len(unique_src) == 1:
            stem = list(unique_src)[0].stem
            if len(infos) == 1:
                orig_p = infos[0].original_page_index + 1
                return f"{stem}_p{orig_p:03d}"
            return f"{stem}_selected"
        return "selected_pages"

    def close_document(self, path: Path) -> bool:
        """Close a specific source PDF file and remove all its pages from the current view.

        Returns True if the document was found and closed.
        """
        # Normalize for reliable matching (load_pdfs stores resolved paths)
        path = path.resolve()
        target_str = str(path)

        doc_to_remove = None
        for doc in self.documents:
            if doc.path == path or str(doc.path) == target_str:
                doc_to_remove = doc
                break

        if not doc_to_remove:
            return False

        # Keep only pages that do not belong to this document
        remaining_pages: list[fitz.Page] = []
        remaining_infos: list[PageInfo] = []
        for page, info in zip(self.all_pages, self.page_infos):
            if str(info.source_doc_path) != target_str:
                remaining_pages.append(page)
                remaining_infos.append(info)

        # Close the document
        doc_to_remove.close()
        self.documents.remove(doc_to_remove)

        self.all_pages = remaining_pages
        self.page_infos = remaining_infos

        # Renumber page indices
        for i, info in enumerate(self.page_infos):
            info.page_number = i

        self._thumb_cache.clear()
        return True
