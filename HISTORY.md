# QuickMarkPDF Changelog

[日本語版 HISTORY_jp.md](HISTORY_jp.md)

This file records the major changes in each public version.

## Versioning rules

- First digit (for example, `1.0.0` to `2.0.0`): new features
- Second digit (for example, `1.0.0` to `1.1.0`): bug fixes
- Third digit (for example, `1.1.0` to `1.1.1`): other changes, such as documentation updates

## v1.2.1 (2026-08-27)

### Features

- The thumbnail panel now switches pages with the Up/Down arrow keys when it has focus, instead of just scrolling the panel.

### Performance

- Sped up opening PDFs (and the file-association double-click launch, which goes through the same code path) by caching the currently-open PDFium document per source file, instead of re-reading and re-parsing the whole file from disk on every single page thumbnail/preview render.

### Documentation

- Brought the About dialog in line with the Quick app series specification: app name, a cyan version line, a divider, bracketed "[Development environment]" / "[Author]" sections, the author's circular badge image, and a cyan glow border on the card.
- Documented the new Up/Down shortcut in the in-app Help dialog and in `document/spec.md` / `spec_jp.md`.

## v1.1.0 (2026-08-21)

### Bug fixes

- Fixed the right-click context menu rendering outside the window when opened near the bottom/right edge (e.g. the last page of a long thumbnail list) — it now clamps to stay fully visible.
- Fixed Markdown-to-PDF export: heading text (h1-h6) rendered near-invisible (light gray on white) in the exported PDF because the dark-theme heading color wasn't overridden by the print stylesheet.
- Fixed Markdown-to-PDF export producing only 1 page regardless of document length: `html`/`body`'s `height:100%; overflow:hidden` (needed for the app's own chrome) was clipping print output to a single viewport-height page. The print stylesheet now lets content grow to its natural height. Verified with a 40-section test document exporting to 14 pages.

### Documentation

- Unified README, `document/`, distribution readme, HISTORY, and LICENSE to the Quick app template: C++/WebView2 is the shipped product, Python is an evaluation prototype, UI is Japanese-only, and third-party redistributions (PDFium, WebView2 Loader, Mermaid, MathJax) are listed.
- Stated in user-facing docs that the app is free, with no ads, no donation requests, and no paid features.

## v1.0.0 (2026-08-21)

### Native (C++/WebView2) — now the shipped product

- Completed the second C++/WebView2 port to feature parity with the Python prototype: page split, PNG/JPEG image export with crop, keyboard shortcuts, right-click menu, Markdown preview mode (with Mermaid diagrams and MathJax math), Markdown-to-PDF export, and a PDF+Markdown mixed-selection guard.
- `python/` (PySide6) is now a development-time evaluation prototype only; it is not distributed.

### Design

- Switched to the Modern Dark / Glassmorphism theme shared with QuickDiskBench/QuickFolderSize.
- New application icon.
- Added an in-app Help menu (usage guide and keyboard shortcuts) and an About dialog.

### Documentation

- Rewrote README.md / README_jp.md to reflect the native version as the shipped product.
- Added `document/spec.md`, `spec_jp.md`, `about.md`, `about_jp.md`.
- Rewrote `dist/documents/readme.txt` / `readme_jp.txt` to cover the native distribution and full usage, including how Save behaves with multiple files open (merges them into one new PDF).

## Unreleased (2026-08-18)

### GUI

- Refreshed the PDF editing core and UI.
- Added page tagging, thumbnail reordering, Markdown preview, and background processing improvements.

### Documentation

- Adopted the Quick app shared document and distribution structure.

