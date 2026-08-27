# QuickMarkPDF — About

[日本語版 about_jp.md](about_jp.md)

## Version

Ver. v1.2.1

## Concept

A simple Windows desktop PDF page editor — free, no ads, no donation requests, no paid features —
just the minimal page-level editing most people actually need (split, merge,
reorder, rotate, export). As a bonus, it can also render and export Markdown
to PDF, including Mermaid diagrams and math (MathJax TeX notation).

## Display language

The GUI is Japanese only. There is no in-app language toggle.

## Development environment

- C++17 (MinGW-w64 / g++, WinLibs MCF UCRT)
- WebView2 (Microsoft Edge WebView2 Runtime)
- PDFium (page rendering/editing)
- Windows Imaging Component (JPEG encoding)
- Win32 API (`IFileDialog` / `GetOpenFileNameW` / `GetSaveFileNameW`, TaskDialog)

The frontend (HTML/CSS/JS) is framework-free. Besides PDFium, there are no
other third-party C++ libraries.

## Status

`core/native/` (C++17 + WebView2) is the shipped product.
`python/prototype/` (PySide6) is a prototype used only for evaluating behavior during
development; it is not shipped. See [`environment.md`](environment.md) for
the build, the first discarded port, and the QA process that still compares
page-editing behavior between the two.

## Third-party software

Redistributed with the GUI:

- PDFium (`pdfium.dll`)
- Microsoft WebView2 Loader (`WebView2Loader.dll`)
- Mermaid.js (MIT)
- MathJax (Apache License 2.0)

WebView2 Runtime is not bundled.

## Author

GitHub: [maktak-105](https://github.com/maktak-105)

`Copyright (c) 2026 maktak-105 (GitHub: https://github.com/maktak-105)`

## Disclaimer

QuickMarkPDF is independent software and is not affiliated with or endorsed
by Adobe, Microsoft, or any other third-party software vendor.
