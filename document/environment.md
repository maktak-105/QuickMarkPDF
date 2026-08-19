# Development Environment

[日本語版 environment_jp.md](environment_jp.md)

## Current Technology Stack

### Native version (post-migration)

- **Language**: C++17
- **GUI**: Microsoft WebView2 (HTML/CSS/JavaScript)
- **Backend**: PDFium (BSD-3 license, using the prebuilt DLL from `bblanchon/pdfium-binaries`)
- **Build**: MinGW-w64 g++ (direct compilation via `build_native.py`, no CMake, no MSVC) + Windows SDK headers from the WebView2 SDK / MinGW itself
- **UI/C++ bridge**: WebView2 WebMessage API (JSON messages)

This follows the shared workspace template at `___appli-template` (see the note at the top of the repo's `README.md`): a single `core/native/` holds all native code including the WebView2 host (`webview_main.cpp`), dev UI source lives in `templates/`+`static/` and gets bundled into one self-contained `index.html` by `bundle_html.py`, and `build_native.py`/`build.bat` produce a flat `dist/binary/` folder -- no CMake build tree, no separate `core/webview2/`.

**No MSVC/WRL**: `webview_main.cpp` does not use `Microsoft::WRL::Callback`/`ComPtr` (`<wrl.h>`/`<wrl/event.h>`) -- confirmed that `<wrl/event.h>` isn't even present in this MinGW-w64 distribution's headers, so it isn't just a style choice. The three WebView2 completion/event handlers (`EnvCompletedHandler`, `ControllerCompletedHandler`, `WebMessageReceivedHandler`) are hand-rolled `IUnknown` implementations wrapping a `std::function`, matching the pattern already proven in this workspace's `QuickFolderSize/core/native/webview_main.cpp`. `CreateCoreWebView2EnvironmentWithOptions` is resolved from `WebView2Loader.dll` at runtime via `LoadLibraryW`/`GetProcAddress` (a `CreateEnvFn` function-pointer typedef) rather than by linking `WebView2Loader.dll.lib`, for the same reason `pdfium.dll` is loaded dynamically rather than statically linked (see below) -- sidesteps any question of whether a Microsoft-format import library links cleanly under MinGW's `ld`. `IFileOpenDialog`/`IShellItem`/the WIC interfaces use a small hand-rolled `ComPtr<T>` (`std::unique_ptr<T, ComDeleter<T>>`, standard library only) instead of WRL's, so early returns can't leak a COM reference.

For the PDF engine, we chose **PDFium** (BSD-3) over MuPDF (AGPL/commercial dual license), since PDFium is compatible with distributing an MIT-licensed EXE. See `plans/2026-08-19_PDFエンジン選定_v1.0.md` for the comparison. The prebuilt `pdfium.dll` extracted into `third_party/pdfium/` is copied next to each executable and loaded dynamically via `LoadLibraryW` + `GetProcAddress` (rather than statically linking the import library) -- originally to keep `pdf_backend.cpp` portable across a MinGW native core and an MSVC WebView2 host; now that both are MinGW, that specific reason no longer applies, but dynamic loading still works and there's no reason to change it. `PdfBackend::inspect` retrieves the page count via `FPDF_LoadMemDocument64`, and `PdfBackend::save` builds a new PDF from a `WorkingDocument` (reordering, moving pages between files, rotating, and deleting) via `FPDF_ImportPagesByIndex` + `FPDFPage_SetRotation` + `FPDF_SaveAsCopy`. Encrypted sources without a correct password raise `PdfPasswordRequiredError`. `PdfBackend::render_page` rasterizes a page to top-left-origin RGBA8 pixels (`FPDFBitmap_Create` + `FPDF_RenderPageBitmap`, converting pdfium's native BGRA to RGBA) for the WebView2 UI: `webview_main.cpp` answers a `render_page` WebMessage by base64-encoding the pixels (`CryptBinaryToStringA`) into a `page_rendered` response, and `static/js/app.js` decodes them with `atob` into a `canvas` via `ImageData` for the page-list thumbnails. There is no click-to-preview pane yet; only the thumbnail strip is wired up.

`WorkingDocument` (`core/native/engine.h`) tracks undo history and a dirty flag: every mutating call (`append_page`, `reorder`, `rotate`, `erase`) snapshots the page list right before it commits (never on a call that ends up throwing, so rejected input can't pollute the history) and marks the document dirty. `undo()` pops the most recent snapshot, capped at 20 entries like the Python baseline's `push_undo_snapshot`. `clear()` is a hard reset: it is not itself undoable and drops the whole undo history and dirty flag, since a `PageRef` from before a clear is meaningless afterward. `mark_saved()` clears the dirty flag and must only be called by whatever orchestrates a successful `PdfBackend::save()` -- never from a catch block -- so a failed save correctly leaves the document dirty.

`inspect()` also returns each page's own stored rotation (`page_rotations`, via `FPDFPage_GetRotation`), since `WorkingDocument`'s rotation is an absolute value applied with `FPDFPage_SetRotation` at save/render time -- a freshly appended `PageRef` has to start from the source page's real rotation, not 0, or saving/rendering would silently un-rotate an already-rotated source page. `render_page` and the new `render_page_at_dpi` (same rendering path, sized from a DPI figure instead of an exact pixel width, for image export) both take that rotation and apply it with `FPDFPage_SetRotation` *before* querying the page's width/height, so a 90/270 rotation correctly swaps the rendered aspect ratio.

### `webview_main.cpp` <-> `WorkingDocument` integration

`webview_main.cpp` (`core/native/`, formerly `core/webview2/host.cpp`) holds a single `WorkingDocument` (`g_document`) for the whole session instead of just a most-recently-opened file path, plus a `source_path -> password` map so `PdfBackend::save` can reopen encrypted sources without re-prompting. The WebMessage protocol:

| From JS | Behavior |
|---|---|
| `open_pdf` | Multi-select native Open dialog (`OFN_ALLOWMULTISELECT`); each file is `inspect()`-ed and its pages `append_page`-ed onto `g_document`. An encrypted file triggers a native password prompt (see below), retried up to 3 times; a file that still fails is skipped and listed in the response's `failed_files`. Responds `pdf_opened` with `loaded_files`, `failed_files`, and a full document-state snapshot (`page_count`, `dirty`, `can_undo`, `pages`). |
| `render_page {page_index, width}` | Renders `g_document.page(page_index)` (using its own rotation) and responds `page_rendered`, unchanged from before except it now reads from `g_document` instead of a single tracked path. |
| `reorder_pages {order}}` / `rotate_page {page_index, degrees}` / `delete_pages {indices}` / `undo_edit` | Call the matching `WorkingDocument` method and respond with a `document_state` snapshot (same shape as `pdf_opened`'s, minus the load-specific fields). |
| `save_pdf` | Native Save dialog, then `PdfBackend::save(g_document, path, g_source_passwords)`; `mark_saved()` only runs after `save` returns without throwing. |
| `export_images {indices, dpi}` | Native folder picker, then `render_page_at_dpi` (default 150 DPI, matching the Python baseline) + PNG encoding via WIC (`IWICImagingFactory`/`IWICBitmapEncoder`, `GUID_ContainerFormatPng`) for each requested page (all pages if `indices` is empty), named `page_0001.png` etc. |

The password prompt uses `CredUIPromptForCredentialsW` (`wincred.h`) rather than a hand-built dialog, since a single documented API call is far less likely to have a subtle mistake that only interactive use would reveal. The folder picker for image export uses the modern `IFileOpenDialog` + `FOS_PICKFOLDERS` (COM, via the hand-rolled `ComPtr<T>` described above), not the deprecated `SHBrowseForFolder`.

`static/js/app.js` was updated to match: it now builds each page-list row with move-up/move-down, rotate, and delete buttons (posting `reorder_pages`/`rotate_page`/`delete_pages`) instead of a static label, and adds toolbar buttons for undo and image export. There is still no drag-and-drop reordering or click-to-preview pane -- those remain open Phase 2 items.

**Not yet interactively verified**: this code was checked with `build_native.py` (clean build, no warnings observed) and `engine_tests.cpp`'s full suite passing when compiled the same way, not by launching the EXE -- the native multi-select dialog, password prompt, save dialog, folder picker, and the new UI buttons all still need a hands-on run to confirm they behave as intended.

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

1. Install a MinGW-w64 g++ toolchain (this repo has been built against the WinLibs UCRT build, found automatically by `build_native.py`; MSVC/Visual Studio is not required for this project).
2. Run `powershell -ExecutionPolicy Bypass -File scripts/fetch_webview2_sdk.ps1` to extract the WebView2 SDK into `third_party/webview2/`.
3. Run `powershell -ExecutionPolicy Bypass -File scripts/fetch_pdfium.ps1` to extract the prebuilt PDFium DLL into `third_party/pdfium/`.
4. Build:

```powershell
python build_native.py
# or: build.bat
```

This bundles `templates/index.html` + `static/css/style.css` + `static/js/app.js` into a self-contained `dist/binary/index.html` (via `bundle_html.py`), compiles `dist/binary/QuickMarkPDF.exe` (GUI) and `dist/binary/QuickMarkPDF_cli.exe` (CLI demo of the PDF-engine-agnostic page model), copies `pdfium.dll` and `WebView2Loader.dll` next to them, and finally compiles and runs `core/native/engine_tests.cpp` as a build-time regression check (pass `--skip-tests` to skip that step). `dist/binary/` ends up as a flat, ready-to-run folder -- everything needed to launch `QuickMarkPDF.exe` is right there, matching the flat-ZIP distribution convention in `___appli-template/01_フォルダ構成.md`. It runs on Windows 10/11 with the WebView2 Runtime installed.

## Project layout

```
QuickMarkPDF/
├── core/
│   └── native/                    # All native C++: engine, PdfBackend, WebView2 host, CLI, tests, icon/resource
├── templates/
│   └── index.html                 # Dev-mode HTML (references static/ via relative paths)
├── static/
│   ├── css/style.css              # Dev-mode CSS
│   └── js/app.js                  # Dev-mode JS (framework-free)
├── build_native.py                # Builds dist/binary/ via direct g++ invocation (no CMake)
├── bundle_html.py                 # Inlines templates/static into dist/binary/index.html
├── build.bat                      # Thin wrapper around build_native.py
├── dist/
│   └── binary/                    # Build output (gitignored except .gitkeep) -- QuickMarkPDF.exe, _cli.exe, DLLs, index.html
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
