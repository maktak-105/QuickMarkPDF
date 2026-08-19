# QuickMarkPDF

[日本語版 README_jp.md](README_jp.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-en.png" alt="QuickMarkPDF GUI" width="720">
</p>

A simple Windows desktop PDF editor migrating to a C++ backend with a WebView2 UI. The Python/PySide6 version remains available as the behavior reference during migration.

**Repository structure follows the shared template** at `___appli-template` (sibling repo, alongside QuickFolderSize/QuickDiskBench in this workspace) — see [`01_フォルダ構成.md`](../___appli-template/01_フォルダ構成.md) there for the authoritative layout rules (`core/native/` holds all native code including the WebView2 host, `templates/`+`static/` are the dev UI source bundled by `bundle_html.py`, `dist/binary/` is the gitignored build output, `build_native.py`+`build.bat` build it). This project is mid-migration toward that layout; anything still deviating from it (e.g. a leftover CMake build) is a known gap, not the intended target.

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

## Native C++/WebView2 development

Install a MinGW-w64 g++ toolchain (no MSVC/Visual Studio needed), then follow [`document/environment.md`](document/environment.md) to fetch the WebView2 SDK and PDFium binaries into `third_party/`. Build with:

```powershell
python build_native.py
# or: build.bat
```

This bundles `templates/`+`static/` into a self-contained `dist/binary/index.html`, builds `dist/binary/QuickMarkPDF.exe` and `QuickMarkPDF_cli.exe`, copies the required DLLs, and compiles+runs `core/native/engine_tests.cpp` as a build-time check. `dist/binary/` ends up flat and ready to run. See [`plans/2026-08-18_C++移植_v1.0.md`](plans/2026-08-18_C++移植_v1.0.md) for the migration plan.

## License

This project is released under the MIT License. See [`LICENSE`](LICENSE) and the distribution copies under [`dist/documents/`](dist/documents/).

## Design philosophy

- Keep page-level PDF editing direct and visible.
- Keep Markdown preview assets bundled for offline use.
- Prefer a small, dependable Windows desktop workflow over a complex document suite.

## Disclaimer

This software is provided as-is. Back up important PDFs before editing or exporting them.
