# QuickMarkPDF

[日本語版 README_jp.md](README_jp.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-en.png" alt="QuickMarkPDF GUI" width="720">
</p>

A simple Windows desktop PDF editor. The Python/PySide6 version under [`python/`](python/) is the spec of record — a prior attempt at a C++/WebView2 backend was abandoned; see [`CPP_PORT_POSTMORTEM.md`](CPP_PORT_POSTMORTEM.md) for why, and [`document/environment.md`](document/environment.md) for how this project now guards against repeating that failure (an automated test program built specifically around not letting native dialogs block a test run).

**Repository structure follows the shared template** at `___appli-template` (sibling repo, alongside QuickFolderSize/QuickDiskBench in this workspace) — see [`01_フォルダ構成.md`](../___appli-template/01_フォルダ構成.md) there for the authoritative layout rules. This repo currently follows the template's "Python版（PyInstaller配布）" variant.

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

See [`document/environment.md`](document/environment.md) for full development details.

## Building the Windows application

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

The onedir package is generated under `dist/QuickMarkPDF/`. Keep `QuickMarkPDF.exe` and its `_internal` directory together.

## Testing

```powershell
python -m pip install -r requirements-dev.txt
python run_tests.py
```

Runs the full automated test program (unit, integration, appearance, and
timing checks) and writes a report to `tests/reports/summary.md`. See
[`document/environment.md`](document/environment.md#automated-tests) for the
test tiers, how the native-dialog guard works, and how to run the opt-in
real-screen tier.

## License

This project is released under the MIT License. See [`LICENSE`](LICENSE) and the distribution copies under [`dist/documents/`](dist/documents/).

## Design philosophy

- Keep page-level PDF editing direct and visible.
- Keep Markdown preview assets bundled for offline use.
- Prefer a small, dependable Windows desktop workflow over a complex document suite.

## Disclaimer

This software is provided as-is. Back up important PDFs before editing or exporting them.
