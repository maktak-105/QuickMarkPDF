# QuickMarkPDF

[日本語版 README_jp.md](README_jp.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-en.png" alt="QuickMarkPDF GUI" width="720">
</p>

A simple Windows desktop PDF editor migrating to a C++ backend with a WebView2 UI. The Python/PySide6 version remains available as the behavior reference during migration.

## Features

- Open, combine, split, reorder, and rotate PDF pages
- Drag and drop page reordering, including moving pages between files
- Markdown preview with Mermaid diagrams and mathematical formulas
- Export selected pages to PDF or PNG/JPG
- Undo and unsaved-change protection

## Running from source

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python python/main.py
```

See [`document/environment.md`](document/environment.md) and [`document/spec.md`](document/spec.md) for development details.

## Building the Windows application

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

The onedir package is generated under `dist/QuickMarkPDF/`. Keep `QuickMarkPDF.exe` and its `_internal` directory together.

## Native WebView2 development

Install Visual Studio 2022 Build Tools with the C++ workload, then obtain the WebView2 SDK according to [`document/environment.md`](document/environment.md). Build the current WebView2 host with:

```powershell
cmake -G "Visual Studio 17 2022" -A x64 -S core/webview2 -B core/webview2/build
cmake --build core/webview2/build --config Release
```

The executable is `core/webview2/build/Release/QuickMarkPDF_webview.exe`. The current host loads the HTML UI, opens a PDF through the native file picker, inspects its page count, and reflects the page list through the C++ ↔ JavaScript bridge. Full PDF engine operations are still being connected incrementally.

## C++ development

The native C++17 core is under `core/native/` and can be built with CMake and MinGW:

```powershell
cmake -G "MinGW Makefiles" -S core/native -B core/native/build
cmake --build core/native/build --config Release
.\core\native\build\QuickMarkPDF_cli.exe demo
ctest --test-dir core/native/build --output-on-failure
```

The current CLI validates the PDF-engine-independent page model. PDF I/O and the GUI will be migrated incrementally. See [`plans/2026-08-18_C++移植_v1.0.md`](plans/2026-08-18_C++移植_v1.0.md) for the migration plan.

## License

This project is released under the MIT License. See [`LICENSE`](LICENSE) and the distribution copies under [`dist/documents/`](dist/documents/).

## Design philosophy

- Keep page-level PDF editing direct and visible.
- Keep Markdown preview assets bundled for offline use.
- Prefer a small, dependable Windows desktop workflow over a complex document suite.

## Disclaimer

This software is provided as-is. Back up important PDFs before editing or exporting them.
