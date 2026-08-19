# Development Environment

[日本語版 environment_jp.md](environment_jp.md)

## Current Technology Stack

### Native version (post-migration)

- **Language**: C++17
- **GUI**: Microsoft WebView2 (HTML/CSS/JavaScript)
- **Backend**: PDFium (BSD-3 license, using the prebuilt DLL from `bblanchon/pdfium-binaries`)
- **Build**: CMake + Visual Studio 2022 Build Tools (WebView2 host) / MinGW (native core and tests) + Windows SDK
- **UI/C++ bridge**: WebView2 WebMessage API (JSON messages)

The WebView2 SDK is fetched from the NuGet package `Microsoft.Web.WebView2`. The SDK itself is not committed to the repository; it is extracted into `third_party/webview2/`, which is excluded via `.gitignore`.

For the PDF engine, we chose **PDFium** (BSD-3) over MuPDF (AGPL/commercial dual license), since PDFium is compatible with distributing an MIT-licensed EXE. See `plans/2026-08-19_PDFエンジン選定_v1.0.md` for the comparison. The prebuilt `pdfium.dll` extracted into `third_party/pdfium/` is copied next to each executable and loaded dynamically via `LoadLibraryW` + `GetProcAddress` (rather than statically linking the import library) because the same `pdf_backend.cpp` is built by both the MinGW and MSVC toolchains. `PdfBackend::inspect` retrieves the page count via `FPDF_LoadMemDocument64`, and `PdfBackend::save` builds a new PDF from a `WorkingDocument` (reordering, moving pages between files, rotating, and deleting) via `FPDF_ImportPagesByIndex` + `FPDFPage_SetRotation` + `FPDF_SaveAsCopy`. Encrypted sources without a correct password raise `PdfPasswordRequiredError`. `PdfBackend::render_page` rasterizes a page to top-left-origin RGBA8 pixels (`FPDFBitmap_Create` + `FPDF_RenderPageBitmap`, converting pdfium's native BGRA to RGBA) for the WebView2 UI: `host.cpp` answers a `render_page` WebMessage by base64-encoding the pixels (`CryptBinaryToStringA`) into a `page_rendered` response, and `ui/app.js` decodes them with `atob` into a `canvas` via `ImageData` for the page-list thumbnails. There is no click-to-preview pane yet; only the thumbnail strip is wired up.

`WorkingDocument` (`core/native/engine.h`) tracks undo history and a dirty flag: every mutating call (`append_page`, `reorder`, `rotate`, `erase`) snapshots the page list right before it commits (never on a call that ends up throwing, so rejected input can't pollute the history) and marks the document dirty. `undo()` pops the most recent snapshot, capped at 20 entries like the Python baseline's `push_undo_snapshot`. `clear()` is a hard reset: it is not itself undoable and drops the whole undo history and dirty flag, since a `PageRef` from before a clear is meaningless afterward. `mark_saved()` clears the dirty flag and must only be called by whatever orchestrates a successful `PdfBackend::save()` -- never from a catch block -- so a failed save correctly leaves the document dirty.

`inspect()` also returns each page's own stored rotation (`page_rotations`, via `FPDFPage_GetRotation`), since `WorkingDocument`'s rotation is an absolute value applied with `FPDFPage_SetRotation` at save/render time -- a freshly appended `PageRef` has to start from the source page's real rotation, not 0, or saving/rendering would silently un-rotate an already-rotated source page. `render_page` and the new `render_page_at_dpi` (same rendering path, sized from a DPI figure instead of an exact pixel width, for image export) both take that rotation and apply it with `FPDFPage_SetRotation` *before* querying the page's width/height, so a 90/270 rotation correctly swaps the rendered aspect ratio.

### `host.cpp` <-> `WorkingDocument` integration

`host.cpp` now holds a single `WorkingDocument` (`g_document`) for the whole session instead of just a most-recently-opened file path, plus a `source_path -> password` map so `PdfBackend::save` can reopen encrypted sources without re-prompting. The WebMessage protocol:

| From JS | Behavior |
|---|---|
| `open_pdf` | Multi-select native Open dialog (`OFN_ALLOWMULTISELECT`); each file is `inspect()`-ed and its pages `append_page`-ed onto `g_document`. An encrypted file triggers a native password prompt (see below), retried up to 3 times; a file that still fails is skipped and listed in the response's `failed_files`. Responds `pdf_opened` with `loaded_files`, `failed_files`, and a full document-state snapshot (`page_count`, `dirty`, `can_undo`, `pages`). |
| `render_page {page_index, width}` | Renders `g_document.page(page_index)` (using its own rotation) and responds `page_rendered`, unchanged from before except it now reads from `g_document` instead of a single tracked path. |
| `reorder_pages {order}}` / `rotate_page {page_index, degrees}` / `delete_pages {indices}` / `undo_edit` | Call the matching `WorkingDocument` method and respond with a `document_state` snapshot (same shape as `pdf_opened`'s, minus the load-specific fields). |
| `save_pdf` | Native Save dialog, then `PdfBackend::save(g_document, path, g_source_passwords)`; `mark_saved()` only runs after `save` returns without throwing. |
| `export_images {indices, dpi}` | Native folder picker, then `render_page_at_dpi` (default 150 DPI, matching the Python baseline) + PNG encoding via WIC (`IWICImagingFactory`/`IWICBitmapEncoder`, `GUID_ContainerFormatPng`) for each requested page (all pages if `indices` is empty), named `page_0001.png` etc. |

The password prompt uses `CredUIPromptForCredentialsW` (`wincred.h`) rather than a hand-built dialog, since a single documented API call is far less likely to have a subtle mistake that only interactive use would reveal. The folder picker for image export uses the modern `IFileOpenDialog` + `FOS_PICKFOLDERS` (COM, matching the existing `ComPtr`/WRL style already used for WebView2 itself), not the deprecated `SHBrowseForFolder`.

`ui/app.js` was updated to match: it now builds each page-list row with move-up/move-down, rotate, and delete buttons (posting `reorder_pages`/`rotate_page`/`delete_pages`) instead of a static label, and adds toolbar buttons for undo and image export. There is still no drag-and-drop reordering or click-to-preview pane -- those remain open Phase 2 items.

**Not yet interactively verified**: this round of `host.cpp`/`ui/` changes was checked with `cmake --build` (clean rebuild, zero warnings) only, not by launching the EXE -- the native multi-select dialog, password prompt, save dialog, folder picker, and the new UI buttons all still need a hands-on run to confirm they behave as intended.

### Python version during the transition (comparison baseline)

- **Language**: Python 3.12+
- **GUI framework**: PySide6 (Qt 6)
- **PDF library**: PyMuPDF (fitz)
- **Image processing helper**: Pillow
- **Packaging**: PyInstaller (or Nuitka)

## Key libraries

| Library     | Purpose                          | Approx. version |
|-------------|-----------------------------------|------------------|
| PyMuPDF     | PDF loading, editing, conversion  | 1.24+            |
| PySide6     | Desktop GUI                       | 6.7+             |
| Pillow      | Thumbnail generation, image processing | 10.0+       |
| PyInstaller | Windows EXE packaging             | 6.0+             |

## Rationale (Python version)

- **PyMuPDF** currently offers the best functionality, speed, and stability for PDF manipulation
- Makes it relatively easy to build the more complex UI needed for a thumbnail list, drag-and-drop page reordering, and preview display
- Easy to produce a single EXE of a practical size on Windows
- Python enables fast development and has a mature library ecosystem
- Qt provides enough control to achieve a "simple UI" goal

## Python version setup

```bash
# 1. Create the Python virtual environment
python -m venv .venv
.venv\Scripts\activate   # on Windows

# 2. Install the main libraries
pip install PyMuPDF PySide6 Pillow

# 3. Only needed for development (optional)
pip install PyInstaller

# 4. Launch the app
python python/main.py
```

## C++ WebView2 version setup

1. Install the "Desktop development with C++" workload and the Windows 10/11 SDK from Visual Studio 2022 Build Tools.
2. Run `powershell -ExecutionPolicy Bypass -File scripts/fetch_webview2_sdk.ps1` to extract the WebView2 SDK into `third_party/webview2/`.
3. Run `powershell -ExecutionPolicy Bypass -File scripts/fetch_pdfium.ps1` to extract the prebuilt PDFium DLL into `third_party/pdfium/`.
4. Build the x64 WebView2 host with CMake.

```powershell
cmake -G "Visual Studio 17 2022" -A x64 -S core/webview2 -B core/webview2/build
cmake --build core/webview2/build --config Release
```

The resulting executable is `core/webview2/build/Release/QuickMarkPDF_webview.exe`. It runs on Windows 10/11 with the WebView2 Runtime installed.

## Project layout

```
QuickMarkPDF/
├── core/
│   ├── native/                    # PDF-engine-agnostic C++ model
│   └── webview2/                  # WebView2 host
├── ui/                            # HTML/CSS/JavaScript shown in WebView2
├── python/
│   ├── main.py                    # Entry point
│   └── src/                       # Python sources
├── requirements.txt
├── document/
│   ├── spec.md                    # Specification
│   └── environment.md             # This file
├── resources/
│   └── icons/                     # Toolbar PNG icons (auto-generated with Pillow)
│   └── src/pdf_editor/
│       ├── pdf/
│       │   └── pdf_manager.py     # PDF load/edit/save/cache
│       └── ui/
│           ├── main_window.py     # Main window, toolbar, preview
│           └── thumbnail_panel.py # Thumbnail tree (QTreeWidget)
└── tests/
```

## UI architecture overview (Python version)

- **QMainWindow** → top toolbar + central widget
- **Central widget** → QSplitter (horizontal), split left/right
  - Left: `ThumbnailPanel` (a QTreeWidget subclass)
  - Right: QScrollArea + QLabel (preview)
- **ThumbnailPanel** custom pieces:
  - `_ThumbnailDelegate`: manages different row heights for the file header row versus page rows. Page rows are drawn with a custom `paint()` (independent of `iconSize()`)
  - The thumbnail canvas has a variable height of `(icon_w × actual image height + TEXT_H)`, so wide pages have no extra padding
  - `Qt.UserRole` = page index, `Qt.UserRole + 1` = canvas height (read by the delegate)
  - Panel width = `icon_w + 2 × indent + scrollbar_margin` (because Qt's `rootIsDecorated=True` offsets child items by 2×indent to the right)

## PDFManager's main design (Python version)

| Method | Role |
|--------|------|
| `load_pdfs` | Opens multiple PDFs and builds `all_pages` / `page_infos` |
| `reorder_pages` | Reorders pages given a list of the new order |
| `rotate_page` | Rotates a given page (with cache invalidation) |
| `get_thumbnail_pixmap` | Generates a thumbnail (scales once, uses the cache) |
| `get_preview_pixmap` | High-resolution rendering for the preview |
| `save_as` | Writes all pages out as a new PDF |
| `save_selected_pages` | Writes only the selected pages out as a new PDF |

## Thumbnail cache design (Python version)

- Key: `(id(page), max_size, page.rotation)`
- Invalidated on: rotation, closing all pages
- Reordering only rearranges references to page objects, so `id()` doesn't change and the cache stays valid

## Distribution plan

- Build a single Windows EXE with PyInstaller
- Consider migrating to Nuitka if needed

## Notes

- Windows is the top-priority target for now
- If macOS/Linux support becomes necessary later, PySide6's cross-platform nature makes that feasible
