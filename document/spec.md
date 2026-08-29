# QuickMarkPDF Specification

## 1. Overview

- **Name**: QuickMarkPDF
- **Purpose**: A simple PDF page editor — free, no ads, no donation requests, no paid features (split, merge, reorder, rotate, export to image/PDF). As a bonus, it also exports Markdown (with Mermaid diagrams and math) to PDF.
- **Target OS**: Windows 10 / 11 (64-bit)
- **Implementation**: C++17 (MinGW-w64) + WebView2 + HTML/CSS/vanilla JS
- **Distribution**: GitHub Releases ZIP (flat layout; Release not published yet)
- **UI language**: Japanese / English (toggle button at the right end of the menu bar; persisted to `localStorage` and the registry)
- **Version**: v3.0.0

`core/native/` (C++17 + WebView2) is the shipped product. `python/prototype/` (PySide6)
is a prototype used only for evaluating behavior during development; it is
not shipped.

## 2. Architecture

```text
[HTML/CSS/JS (WebView2)]  <-WebMessage(JSON)->  [webview_main.cpp]  <-direct call->  [engine.cpp (PdfManager)]
```

- `engine.cpp` (`PdfManager`): handles PDF loading, rotation, deletion, reordering, undo, saving, page splitting, image export, and text extraction. GUI-independent, shared by the CLI build and automated tests.
- `pdf_backend.cpp`: PDFium wrapper for page rendering/editing.
- `image_io.cpp`: a hand-written PNG encoder plus JPEG encoding via the Windows Imaging Component.
- `webview_main.cpp`: creates the Win32 window, initializes WebView2, relays JSON messages, and drives file dialogs (`IFileDialog`/`GetOpenFileNameW`/`GetSaveFileNameW`).
- Frontend: framework-free. `bundle_html.py` bundles it into a single self-contained `index.html`, injecting the Mermaid/MathJax `<script>` tags and MathJax config at bundle time.

## 3. Screen layout

| Area | Content |
| --- | --- |
| Menu bar | "Settings" (preferences), "Help" (usage guide, about) |
| Main toolbar | Open / Split PDF / Export images / Rotate right 90° / Rotate left 90° / 180° / Save |
| Thumbnail-size toolbar | Small / Medium / Large thumbnail size toggle |
| Thumbnail panel (left) | Page list with a filename tag and page numbers (post-edit position vs. original in-file index) |
| Preview (right) | Enlarged view of the selected page. Wheel zooms or scrolls (mode set in preferences), right-drag pans or zooms. By default, left-drag selects text to copy; right-click (a click, not a drag) opens a menu to switch left-drag to crop-area selection instead (reverts to text-selection whenever a page is (re)opened) |
| Markdown workspace | Shown instead of the PDF workspace when a `.md` file is open |
| Status bar | The result/progress of the most recent action |

## 4. Feature list

| # | Feature | Description |
| --- | --- | --- |
| 1 | Open PDF | Loads and concatenates multiple PDFs at once. Password-protected files get up to 3 retries. Duplicate files are detected and skipped. |
| 2 | Open Markdown | Opens `.md`/`.markdown` and switches to Markdown preview mode. Mixing PDF and Markdown in one selection is rejected with a warning. |
| 3 | Page selection | Click (single) / Ctrl+click (multi) / Shift+click (range). |
| 4 | Reorder | Drag-and-drop thumbnails, including across multiple open files. |
| 5 | Rotate | Right 90° / left 90° / 180°, multi-select capable, also available from the right-click menu. |
| 6 | Delete | Removes the selected pages. |
| 7 | Undo | Reverts the most recent edit (rotate/delete/reorder) one step. |
| 8 | Split PDF | Saves only the selected pages as a new PDF (does not affect the source file or its undo history). |
| 9 | Export images | PNG/JPEG, DPI (72/150/300/custom), JPEG quality, scope (all/selected pages), and an optional crop area. |
| 10 | Save | If only one file is open, you can choose to overwrite it or save as a new file. **If multiple files are open at once, overwriting is not possible; Save always opens a "Save As" dialog and merges every open file's pages into one new PDF** (original files are left unmodified). Determined by `PdfManager::can_overwrite_source()` (whether every page shares the same `source_path`). |
| 11 | Thumbnail size | Small (80px) / Medium (120px) / Large (200px). |
| 12 | Preview interaction | Wheel zooms (default) or scrolls; right-drag pans or zooms (mode set in preferences). |
| 13 | Crop area selection | Left-drag on the preview to define the crop region used by image export. |
| 14 | Unsaved-change confirmation | Confirms before an action that would discard unsaved edits. |
| 15 | Right-click menu | Rotate right/left/180°, split PDF, export image, delete page, close this file. Right-clicking either the thumbnail panel or the preview shows the same items (the preview also adds "Switch to crop-area selection" / "Switch back to text selection"). |
| 16 | Keyboard shortcuts | Ctrl+O / Delete / Ctrl+Z / Ctrl+S (see section 7). |
| 17 | Markdown preview | Headings, bold/italic, inline code, code blocks, blockquotes, lists, links, images, horizontal rules, GFM tables. |
| 18 | Mermaid diagrams | ` ```mermaid ` fenced blocks are rendered with Mermaid.js. |
| 19 | Math | `$...$` (inline) / `$$...$$` (display) notation is rendered with MathJax. |
| 20 | Markdown-to-PDF export | Uses `ICoreWebView2_7::PrintToPdf` on the Markdown preview (UI chrome is excluded via `@media print`). |
| 21 | Preferences | Toggles the preview mouse-wheel mode (zoom/scroll), persisted to `localStorage`. |
| 22 | Text selection & copy | Overlays a transparent text layer on the preview, built from line-level bounding boxes pdfium's text-extraction API returns, enabling standard browser drag-selection and Ctrl+C copy. Enabled by default. MathJax equations (baked into the PDF as vector paths with no text objects) and scanned-image PDFs (no text layer to begin with) have no selectable text for that content. |
| 23 | UI language toggle | "日本語"/"English" buttons at the right end of the menu bar switch the whole UI (toolbar, menus, modals, status messages, native dialogs). The JS side persists to `localStorage`, the C++ side to the registry, independently, kept in sync via the `set_language` message. |
| 24 | Extract text | Right-click menu opens a dialog to pick all pages / a typed page range ("1,3,5-8") / the page currently shown in the preview, then saves the extracted text as a .txt file via a "Save As" dialog. Text is read top-left to bottom-right (line-level runs from `PdfBackend::get_text_layout` are grouped into rows and re-joined left-to-right); bullet/numbered-list markers are preserved where the source PDF exposes them as real text objects. |

## 5. WebMessage protocol

### JS -> native

| type | parameters | description |
| --- | --- | --- |
| `open_pdf` | none | Opens the file picker and loads PDF/Markdown |
| `get_state` | none | Re-fetches the current document state |
| `render_page` | `page_index`, `width` | Renders a page at the given width, returned via `page_rendered` |
| `get_text_layout` | `page_index` | Gets the page's selectable text (line boxes + strings), returned via `text_layout` |
| `reorder_pages` | `order` | Applies a new page order |
| `rotate_pages` | `indices`, `degrees` | Rotates the given pages |
| `delete_pages` | `indices` | Deletes the given pages |
| `undo_edit` | none | Reverts the most recent edit |
| `close_document` | `path` | Closes the given file |
| `export_images` | `indices`, `dpi`, `fmt`, `jpeg_quality`, `output_dir`, `prefix`, optional `crop` | Exports pages as images |
| `get_export_defaults` | `indices` | Gets defaults for the export dialog |
| `browse_export_folder` | none | Opens a folder picker for the export destination |
| `save_pdf` | none | Overwrite-saves (or "save as" when not possible) |
| `split_pdf` | `indices` | Saves the selected pages as a new PDF |
| `extract_text` | `indices` | Extracts the given pages' text and opens a save dialog for a .txt file |
| `save_markdown_pdf` | optional `output_path` | Exports the Markdown preview to PDF. Omitted `output_path` opens a save dialog; tests may pass a path to skip the dialog |
| `set_language` | `lang` (`"ja"` / `"en"`) | Switches the UI language. Updates the C++ side's `g_language` and persists it to the registry |

### native -> JS

| type | parameters | description |
| --- | --- | --- |
| `pdf_opened` | `loaded_files`, `failed_files` | Result of loading PDFs |
| `markdown_opened` | `path`, `content` | Markdown file loaded, body content sent |
| `page_rendered` | `page_index`, image data | Rendered page image |
| `text_layout` | `page_index`, `page_width_pt`, `page_height_pt`, `runs` (each with `x0`/`y0`/`x1`/`y1`/`text`) | Text-layer data for the page; `runs` are top-left-origin line boxes in PDF points |
| `document_state` | page list, selection state, etc. | Re-sent after each operation |
| `backend_status` | `message` | Backend connection status |
| `export_defaults` | `output_dir`, etc. | Defaults for the export dialog |
| `folder_picked` | `path` | Result of the folder picker |
| `status` | message string | Short message for the status bar |

## 6. Processing flow

1. At startup, PDF/Markdown paths passed as command-line arguments are opened automatically.
2. A user action (button/shortcut/right-click) sends a WebMessage -> `webview_main.cpp` calls into `PdfManager` -> the result is sent back via `document_state` etc. -> `app.js` updates the DOM.
3. Image export and PDF splitting involve file I/O, so the result count is shown in the status bar once complete.

## 7. Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Ctrl+O` | Open a file |
| `Delete` | Delete selected pages |
| `Ctrl+Z` | Undo |
| `Ctrl+S` | Overwrite save |
| `ArrowUp` / `ArrowDown` (thumbnail panel focused) | Select the previous/next page |

## 8. Output format notes

- **Split PDF**: a new PDF containing only the selected pages, in their original order.
- **PNG export**: written with a hand-written PNG encoder — lossless, uncompressed-equivalent.
- **JPEG export**: encoded via the Windows Imaging Component; quality 60-100 is configurable.
- **Markdown-to-PDF**: A4-equivalent output via WebView2's `PrintToPdf`; UI chrome (toolbar etc.) is excluded via `@media print`.

## 9. Performance

### Parallelization

Page rendering and export are currently synchronous. Parallel rendering of
a large page count is not implemented.

### Preview dynamic resolution

The preview first shows a fast 900px-wide render (`PREVIEW_RENDER_WIDTH`)
right after page selection, then re-requests `render_page` once zoom
activity has been idle for 250ms, sized to the actual on-screen pixel count
(natural width x zoom x `devicePixelRatio`, capped at 4000px) and swaps in
the higher-resolution image (`app.js`'s `scheduleHighResPreviewRerender`).
This debounce avoids re-rendering on every wheel/drag event. The text
layer's boxes stay in PDF-point coordinates throughout, so a resolution
swap only needs to recompute `#text-layer`'s `transform: scale` -- no
re-fetch of the text layout is needed.

### Caching

`PdfBackend` keeps up to 4 recently-used source documents open (keyed by
path + password) instead of re-reading the file and re-parsing its xref
table on every `render_page`/`inspect` call. `PdfBackend::save()` evicts the
cache entry for its output path right after a successful write, so an
overwrite-save is always reflected in the next render.

## 10. Planned work

- Support nested lists in Markdown.
- Parallel page rendering / export for large page counts.
- A product-grade CLI (`QuickMarkPDF_cli.exe` is a page-model demo today).
- Publish a GitHub Release (v3.0.0 is not tagged yet; v1.1.0 has been published).
