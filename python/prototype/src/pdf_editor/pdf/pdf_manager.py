"""
PDF Manager - Core PDF handling using PyMuPDF (fitz)
Responsible for loading, reordering, rotating, and rendering pages.

Architecture: every loaded page is copied into a single in-memory "working
document" (`self.working_doc`) as soon as it's loaded, and the source file is
closed immediately afterward — no source file is ever held open. This means
saving, including overwriting a file that one of the pages originally came
from, never runs into a Windows file lock, because nothing has that path open.
"""
from __future__ import annotations
import logging
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, field, replace

logger = logging.getLogger(__name__)


@dataclass
class PageInfo:
    """Lightweight info about a single page for the UI."""
    page_number: int          # 0-based index in all_pages
    source_doc_path: Path      # origin file — never changes after load; also the page's tag/label
    original_page_index: int  # index inside its original document


@dataclass
class LoadResult:
    """Outcome of `PDFManager.load_pdfs`."""
    loaded_count: int
    password_required: List[Path]  # files that are encrypted and need a (correct) password
    duplicate_files: List[Path] = field(default_factory=list)  # already-loaded files that were skipped


@dataclass
class _UndoEntry:
    """One entry on the undo stack: a lightweight snapshot of `all_pages` /
    `page_infos` to restore verbatim.

    This is safe for every undoable action (reorder, rotate, delete, and
    closing a file) because all pages live in the single `working_doc`, which
    stays open for the entire session — a page's `fitz.Page` object reference
    never goes stale, even after it's been removed from `all_pages`.
    """
    label: str = ""
    all_pages: List[fitz.Page] = field(default_factory=list)
    page_infos: List[PageInfo] = field(default_factory=list)
    # Rotation is a mutable property on the (shared) fitz.Page objects, so simply
    # restoring `all_pages` doesn't undo a rotation — the same, already-mutated
    # objects would still be referenced. Record each page's rotation at snapshot
    # time (aligned with `all_pages`) and re-apply it explicitly on undo.
    rotations: List[int] = field(default_factory=list)


class PDFManager:
    """Main controller for all currently-loaded PDF pages.

    All pages live in `self.working_doc`, a single `fitz.Document` that is
    never itself associated with a file on disk. Source files passed to
    `load_pdfs` are opened only transiently — just long enough to copy their
    pages in via `insert_pdf` — and are closed immediately afterward.
    """

    _UNDO_CAP = 20

    def __init__(self):
        self.working_doc: fitz.Document = fitz.open()
        self.all_pages: List[fitz.Page] = []
        self.page_infos: List[PageInfo] = []
        self._thumb_cache: dict = {}  # (page_id, max_size, rotation) → fitz.Pixmap
        self._undo_stack: List[_UndoEntry] = []

    # =====================
    # Undo
    # =====================

    def push_undo_snapshot(self, label: str = ""):
        """Save a lightweight snapshot of the current page arrangement for undo.

        Cheap: only copies the list/dataclass structure and each page's current
        rotation, not PDF content (the underlying `fitz.Page` objects are shared
        references, all backed by the same long-lived `working_doc`).
        """
        entry = _UndoEntry(
            label=label,
            all_pages=list(self.all_pages),
            page_infos=[replace(info) for info in self.page_infos],
            rotations=[page.rotation for page in self.all_pages],
        )
        self._undo_stack.append(entry)
        if len(self._undo_stack) > self._UNDO_CAP:
            self._undo_stack.pop(0)

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def clear_undo_history(self):
        self._undo_stack.clear()

    def undo(self) -> bool:
        """Undo the most recent undoable action. Returns True if something was undone."""
        if not self._undo_stack:
            return False
        entry = self._undo_stack.pop()
        for page, rot in zip(entry.all_pages, entry.rotations):
            if page.rotation != rot:
                page.set_rotation(rot)
        self.all_pages = entry.all_pages
        self.page_infos = entry.page_infos
        self._thumb_cache.clear()
        return True

    # =====================
    # Loading
    # =====================

    def load_pdfs(self, paths: List[Path], passwords: Optional[dict] = None) -> LoadResult:
        """Load one or more PDF files.

        Each source file is opened, its pages are copied into `working_doc`
        via `insert_pdf`, and the source is closed immediately — it is never
        held open past this call.

        IMPORTANT PyMuPDF quirk: `insert_pdf` invalidates every previously
        fetched `fitz.Page` *wrapper object* for the target document — not just
        ones related to the new content, ALL of them (a page's `.number` stays
        valid and is safe to keep, but the Python `Page` object itself becomes
        unusable — "page is None" — as soon as anything else is inserted into
        the same document). So after inserting, every page we still care about
        is refetched from `working_doc` by its (stable) page number.

        `passwords` optionally maps a path (as given, or resolved) to a password
        to try for encrypted files. Files that turn out to need a password that
        wasn't supplied (or was wrong) are reported in `LoadResult.password_required`
        instead of being loaded, so the caller can prompt and retry.

        A file already present among the currently-loaded pages (by resolved
        path) — or repeated within this same `paths` list — is skipped and
        reported in `LoadResult.duplicate_files` instead of being loaded again.
        """
        passwords = passwords or {}
        loaded_count = 0
        password_required: List[Path] = []
        duplicate_files: List[Path] = []
        any_inserted = False
        # Page numbers (stable across appends) of pages we need to keep after
        # any insert_pdf call below invalidates their current wrapper objects.
        keep_numbers = [page.number for page in self.all_pages]
        already_loaded = {info.source_doc_path for info in self.page_infos}

        for path in paths:
            resolved_path = path.resolve()
            if resolved_path in already_loaded:
                duplicate_files.append(resolved_path)
                continue
            already_loaded.add(resolved_path)

            pw = passwords.get(path, passwords.get(resolved_path))
            src: Optional[fitz.Document] = None
            try:
                src = fitz.open(str(resolved_path))
                if src.needs_pass:
                    if not pw or not src.authenticate(pw):
                        password_required.append(resolved_path)
                        src.close()
                        continue

                all_pages_start = len(self.page_infos)      # position within all_pages (for PageInfo)
                new_pages_start = len(self.working_doc)      # actual insertion point in working_doc
                n = len(src)

                self.working_doc.insert_pdf(src)
                src.close()
                src = None
                any_inserted = True

                for i in range(n):
                    self.page_infos.append(PageInfo(
                        page_number=all_pages_start + i,
                        source_doc_path=resolved_path,
                        original_page_index=i,
                    ))
                keep_numbers.extend(range(new_pages_start, new_pages_start + n))
                loaded_count += 1
            except Exception as e:
                logger.error("Failed to open %s: %s", resolved_path, e)
                if src is not None:
                    src.close()

        if any_inserted:
            self.all_pages = [self.working_doc[n] for n in keep_numbers]
            self._thumb_cache.clear()
            # Any undo snapshot taken before this call holds now-invalid Page
            # wrapper objects (see note above) — they can't be safely restored.
            self._undo_stack.clear()

        return LoadResult(
            loaded_count=loaded_count,
            password_required=password_required,
            duplicate_files=duplicate_files,
        )

    def get_page_count(self) -> int:
        return len(self.all_pages)

    def reorder_pages(self, new_order: List[int]):
        """Reorder pages according to new_order (list of old indices)."""
        if len(new_order) != len(self.all_pages):
            raise ValueError("new_order length must match page count")

        self.push_undo_snapshot("並び替え")

        self.all_pages = [self.all_pages[i] for i in new_order]
        self.page_infos = [self.page_infos[i] for i in new_order]

        # Update page_number
        for idx, info in enumerate(self.page_infos):
            info.page_number = idx

    def rotate_page(self, page_index: int, degrees: int):
        """Rotate a single page (90, 180, 270, or -90 etc.).

        Low-level primitive with no undo snapshot of its own — callers that
        rotate multiple pages as one user action should use `rotate_pages`
        instead, so the whole batch becomes a single undo step.
        """
        if not 0 <= page_index < len(self.all_pages):
            return
        page = self.all_pages[page_index]
        pid = id(page)
        self._thumb_cache = {k: v for k, v in self._thumb_cache.items() if k[0] != pid}
        page.set_rotation((page.rotation + degrees) % 360)

    def rotate_pages(self, indices: list[int], degrees: int):
        """Rotate multiple pages by the same amount, as a single undo step."""
        valid = [i for i in indices if 0 <= i < len(self.all_pages)]
        if not valid:
            return
        self.push_undo_snapshot(f"{degrees}度回転")
        for idx in valid:
            self.rotate_page(idx, degrees)

    def delete_pages(self, indices: list[int], label: str = "ページ削除"):
        """Remove the given pages (by current flat index) from the working set.

        This only removes them from the Python-level `all_pages`/`page_infos`
        lists; the underlying `working_doc` keeps their content (harmlessly
        orphaned — never rendered, exported, or saved, since every output path
        rebuilds its content from `all_pages`). This deliberately avoids
        physically deleting pages from `working_doc`, which would make PyMuPDF
        renumber and could invalidate other pages' already-fetched `fitz.Page`
        objects.
        """
        if not indices:
            return
        indices_set = {i for i in indices if 0 <= i < len(self.all_pages)}
        if not indices_set:
            return

        self.push_undo_snapshot(label)

        removed_pids = {id(self.all_pages[i]) for i in indices_set}
        self._thumb_cache = {k: v for k, v in self._thumb_cache.items() if k[0] not in removed_pids}

        self.all_pages = [p for i, p in enumerate(self.all_pages) if i not in indices_set]
        self.page_infos = [info for i, info in enumerate(self.page_infos) if i not in indices_set]

        for idx, info in enumerate(self.page_infos):
            info.page_number = idx

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
        self.working_doc.close()
        self.working_doc = fitz.open()
        self.all_pages.clear()
        self.page_infos.clear()
        self._thumb_cache.clear()
        # Any undo snapshot taken before this point references fitz.Page objects
        # whose parent document is now closed — they'd be unusable if restored.
        self._undo_stack.clear()

    # =====================
    # Save / Export
    # =====================
    def save_as(self, output_path: Path) -> bool:
        """
        Save the current state (all pages with modifications) as a new PDF.
        This effectively merges + applies all edits (rotation, reordering).
        """
        if not self.all_pages:
            return False

        try:
            # Create a new document and insert all current pages
            new_doc = fitz.open()

            for page in self.all_pages:
                # Insert the page (with its current rotation)
                new_doc.insert_pdf(page.parent, from_page=page.number, to_page=page.number)

            new_doc.save(str(output_path))
            new_doc.close()
            return True
        except Exception as e:
            logger.error("Save failed: %s", e)
            return False

    def can_overwrite_source(self) -> bool:
        """Whether "overwrite" saving is unambiguous: every currently-loaded
        page originally came from exactly one source file.

        With multiple source files loaded, there's no single "original file" to
        overwrite (the combined output isn't any one of them), so overwrite is
        only offered for the single-file case.
        """
        sources = {info.source_doc_path for info in self.page_infos}
        return len(sources) == 1

    def overwrite_source(self) -> bool:
        """Overwrite the single source file all currently-loaded pages came from.

        Safe by construction: no source file is ever held open past `load_pdfs`
        (see class docstring), so this is just a plain `save_as` to that path —
        no temp-file/lock workaround needed.
        """
        if not self.can_overwrite_source():
            return False
        target_path = self.page_infos[0].source_doc_path
        return self.save_as(target_path)

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
        """Close a specific source PDF file: remove all pages that came from it.

        Returns True if any pages from this source were found and removed.
        This is just `delete_pages` for that source's pages, so it participates
        in the normal undo stack like any other edit — undoing it restores the
        pages exactly (including any in-memory rotation), since `working_doc`
        was never closed.
        """
        path = path.resolve()
        target_str = str(path)
        indices = [i for i, info in enumerate(self.page_infos) if str(info.source_doc_path) == target_str]
        if not indices:
            return False
        self.delete_pages(indices, label=f"{path.name}を閉じる")
        return True
