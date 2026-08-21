# QuickMarkPDF
[日本語版 README_jp.md](README_jp.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-en.png" alt="QuickMarkPDF GUI" width="720">
</p>

A simple Windows desktop PDF page editor — no ads, no donation nagging, just the split / merge / reorder / rotate / export you actually need. As a bonus, it also renders and exports Markdown to PDF, with Mermaid diagrams and math (MathJax) support.

**`core/native/` (C++17 + WebView2) is the shipped product.** `python/` (PySide6) is a prototype kept for evaluating behavior during development; it is not distributed. See [`document/about.md`](document/about.md) and [`document/environment.md`](document/environment.md) for the full status and history.

## Features

- Open, combine, split, reorder, and rotate PDF pages
- Drag-and-drop page reordering, including moving pages between files
- Export selected/all pages to PDF (split) or PNG/JPEG (with DPI, quality, and crop options)
- Undo and unsaved-change protection
- Markdown preview with Mermaid diagrams and math, exportable to PDF

## Using the binary release

No GitHub Release has been published yet — build from source for now (see below). Once a release is tagged, the ZIP will contain:

- `QuickMarkPDF.exe` - GUI version
- `QuickMarkPDF_cli.exe` - lightweight non-GUI demo binary (not the shipped app)
- `pdfium.dll` - PDF rendering/editing engine
- `WebView2Loader.dll` - WebView2 loader
- `index.html` - bundled GUI (includes Mermaid/MathJax)
- `readme.txt` / `readme_jp.txt` - distribution documentation
- `history.txt` / `history_jp.txt` - change log
- `LICENSE.txt` / `LICENSE_jp.txt` - MIT License files

Run `QuickMarkPDF.exe` for the GUI. If WebView2 Runtime is unavailable, install Microsoft Edge WebView2 Runtime (Evergreen). It is normally included with Windows 11, but may require installation on older Windows 10 systems, LTSC, Server, or managed devices.

## Running from source

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python python/main.py
```

The Python version above is the evaluation prototype, not the shipped app — see "Building the native version" below for the real thing. Full development details: [`document/environment.md`](document/environment.md).

## Building the native version

The native build uses the MinGW-w64 C++ toolchain, validated with WinLibs (MCF threads, UCRT runtime):

```powershell
winget install --id BrechtSanders.WinLibs.MCF.UCRT --exact --source winget
```

`build_native.py` automatically searches the standard WinGet package location and also looks for `windres.exe` next to the detected compiler, so adding MinGW to `PATH` is not required for the project build.

The WebView2 SDK and PDFium are fetched into `third_party/` (gitignored):

```powershell
powershell -File scripts\fetch_webview2_sdk.ps1
powershell -File scripts\fetch_pdfium.ps1
python build_native.py
```

Output: `dist/binary/QuickMarkPDF.exe` (plus `pdfium.dll`, `WebView2Loader.dll`, and the bundled `index.html`).

## License

This project is provided under the MIT License. See [`dist/documents/LICENSE.txt`](dist/documents/LICENSE.txt) for the English original and [`dist/documents/LICENSE_jp.txt`](dist/documents/LICENSE_jp.txt) for the Japanese reference translation.

## Disclaimer

This software is provided as-is. The author assumes no responsibility for data loss, system failures, or hardware damage. Always back up important PDFs before editing or exporting them.

## Design Philosophy

Most PDF tools online are either ad-funded viewers that push a paid tier, or full document suites with far more surface area than a quick "cut a few pages out and rotate this one" task needs. QuickMarkPDF exists to be the small, dependable tool for that instead:

- **Page editing that stays direct and visible**: select pages, drag to reorder, rotate, cut out — no hidden project files, no multi-step wizards for a two-click task.
- **No ads, no donation prompts, no telemetry**: it does what it says and gets out of the way.
- **Markdown-to-PDF as a bonus, not the point**: bundling Mermaid/MathJax support means notes with diagrams and formulas convert cleanly, without needing a second tool.
