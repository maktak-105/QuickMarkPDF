# QuickMarkPDF

[日本語版 README_jp.md](README_jp.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-en.png" alt="QuickMarkPDF GUI" width="720">
</p>

A simple Windows desktop PDF editor built with Python and PySide6.

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
