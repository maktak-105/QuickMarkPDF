# QuickMarkPDF — About

[日本語版 about_jp.md](about_jp.md)

## Version

Ver. v1.1.0

## Concept

A simple Windows desktop PDF page editor with no ads and no donation nagging —
just the minimal page-level editing most people actually need (split, merge,
reorder, rotate, export). As a bonus, it can also render and export Markdown
to PDF, including Mermaid diagrams and math (MathJax TeX notation).

## Development environment

- C++17 (MinGW-w64 / g++, WinLibs MCF UCRT)
- WebView2 (Microsoft Edge WebView2 Runtime)
- PDFium (page rendering/editing), Windows Imaging Component (JPEG encoding)

No third-party C++ library dependencies beyond PDFium. The frontend
(HTML/CSS/JS) is framework-free.

## Status

`python/` (PySide6) is a prototype used for evaluating behavior during
development; it is not shipped. `core/native/` (C++17 + WebView2) is the
shipped product. See [`environment.md`](environment.md) for the full
history and the QA process that measures parity between the two.

## Author

GitHub: [maktak-105](https://github.com/maktak-105)

## Disclaimer

QuickMarkPDF is independent software and is not affiliated with or endorsed
by Adobe, Microsoft, or any other third-party software vendor.
