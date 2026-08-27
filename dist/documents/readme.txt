QuickMarkPDF - Simple PDF page editor
Distribution package  v1.2.1

Free. No ads, no donation requests, no paid features.

GitHub
------
https://github.com/maktak-105/QuickMarkPDF

Binary release
--------------
GitHub Actions builds `QuickMarkPDF-binary.zip` when a `v*` tag is pushed.
The ZIP is not stored in the repository. Download it from:
https://github.com/maktak-105/QuickMarkPDF/releases
and extract it. All distribution files are placed in the same folder
without subfolders (except `vendor/`, which must stay next to index.html).

Requirements
------------
- Windows 10 / 11 (64-bit)
- Microsoft Edge WebView2 Runtime

About WebView2 Runtime
----------------------
Windows 11 normally includes WebView2 Runtime as part of the operating system.
Many Windows 10 systems also have it installed, but it may be missing on older systems,
LTSC, Windows Server, or managed corporate devices.
If the Runtime is missing, install Microsoft Edge WebView2 Runtime (Evergreen) from Microsoft.
`WebView2Loader.dll` is only the loader connecting the application to the Runtime;
it is not the Runtime itself.

Usage (quick start)
-------------------
1. Extract the distribution ZIP into any folder.
2. Keep `QuickMarkPDF.exe`, `pdfium.dll`, `WebView2Loader.dll`, `index.html`,
   and the `vendor` folder together.
3. Run `QuickMarkPDF.exe`.
4. Click "Open" to load one or more PDF files, or a single Markdown (.md) file.
5. Select pages in the left thumbnail panel, then use the toolbar or the
   right-click menu to edit them. Drag thumbnails to reorder pages.
6. Use the "Help" menu at the top for an in-app usage guide and keyboard
   shortcuts, and "Settings" for preview wheel-mode preferences.

The GUI is Japanese only. There is no language toggle.

Opening files
-------------
- "Open" accepts PDF files and Markdown (.md/.markdown) files, but not a mix
  of both in one selection -- doing so shows a warning and nothing is opened.
- Selecting multiple PDFs at once loads and concatenates them into a single
  page list; each thumbnail shows a small filename tag so you can tell pages
  from different source files apart.
- Selecting multiple Markdown files opens only the first one and shows a
  warning that the rest were skipped (only one Markdown document can be
  previewed at a time).
- A password-protected PDF prompts for its password, with up to 3 retries.
  A duplicate of an already-open file is detected and skipped rather than
  loaded twice.

Editing pages
-------------
- Select pages by clicking (single), Ctrl+click (add to selection), or
  Shift+click (range).
- Drag a thumbnail to reorder pages, including moving a page from one open
  file into another file's position in the list.
- Rotate the selected pages right 90 / left 90 / 180 degrees, or delete
  them, from the toolbar or the right-click menu.
- "Undo" (toolbar or Ctrl+Z) reverts the most recent rotate/delete/reorder
  by one step.
- Thumbnail size (small/medium/large) is a separate toolbar row below the
  main toolbar.

Saving: what "Save" does with multiple open files
--------------------------------------------------
"Save" (Ctrl+S) behaves differently depending on how many files are open:
- If only ONE PDF is open, you can choose to overwrite it in place or save
  it as a new file.
- If MULTIPLE PDF files are open at once, overwriting is not possible
  (there is no single source file to write back to), so Save always opens
  a "Save As" dialog. The pages from every open file are merged into one
  new PDF, in the order shown in the thumbnail panel. None of the original
  source files are modified.
This is also how you merge PDFs: open several files together, reorder
pages as needed, then Save to write them out as a single combined PDF.

Split PDF and image export
---------------------------
- "Split PDF" saves only the currently selected pages as a brand-new PDF
  file. The file you started from, and its undo history, are unaffected.
- "Export images" writes the selected (or all) pages out as PNG or JPEG.
  You can set the DPI (72/150/300/custom), JPEG quality, and optionally
  restrict the output to a cropped area -- drag on the preview (left mouse
  button) to define that crop area before opening the export dialog.

Right-click menu
-----------------
Right-clicking a page thumbnail (auto-selecting it if it wasn't already
selected) opens a menu with: rotate right 90, rotate left 90, rotate 180,
split PDF, export image, delete page, and close this file.

Keyboard shortcuts
-------------------
- Ctrl+O   Open a file
- Delete   Delete the selected pages
- Ctrl+Z   Undo
- Ctrl+S   Save
- Up/Down  With the thumbnail panel focused, select the previous/next page

Markdown mode (bonus feature)
------------------------------
Opening a .md file switches the whole window from PDF editing to a
Markdown preview (the PDF toolbar buttons are disabled while in this mode).
Supported: headings, bold/italic, inline code, fenced code blocks,
blockquotes, lists, links, images, horizontal rules, and GFM tables.
Two extras are bundled and work offline, no internet connection needed:
- Mermaid diagrams: fence a block with ```mermaid and it renders as a
  diagram (flowcharts, sequence diagrams, etc. -- whatever Mermaid.js
  supports).
- Math: inline `$...$` and display `$$...$$` LaTeX-style notation is
  rendered with MathJax.
Press "Save" (or Ctrl+S) in Markdown mode to export the current preview,
diagrams and math included, to a PDF file via a save dialog.

Preferences
-----------
The "Settings" menu's preferences dialog controls how the mouse wheel
behaves over the PDF preview: the default "zoom" mode zooms with the wheel
and pans with a right-drag; the alternate "scroll" mode scrolls vertically
with the wheel and zooms with a right-drag instead. The choice is
remembered between runs.

`QuickMarkPDF_cli.exe` is a lightweight, non-GUI demo binary used to
exercise the underlying page-editing engine (`--help` / `demo`). It is not
a product command-line interface.

Distribution files
------------------
- `QuickMarkPDF.exe` - WebView2 GUI version
- `QuickMarkPDF_cli.exe` - non-GUI demo/verification binary
- `pdfium.dll` - PDF rendering/editing engine
- `WebView2Loader.dll` - WebView2 loader
- `index.html` - GUI content
- `vendor/` - Mermaid.js and MathJax used by Markdown preview
- `readme.txt` - this file
- `readme_jp.txt` - Japanese distribution documentation
- `history.txt` - change log
- `history_jp.txt` - change log (Japanese)
- `LICENSE.txt` - MIT License (original)
- `LICENSE_jp.txt` - MIT License (Japanese reference translation)

SHA-256
-------
Published with the GitHub Release that contains this ZIP.

License
-------
The source code of this software is provided under the MIT License.
Copyright (c) 2026 maktak-105 (GitHub: https://github.com/maktak-105)
See the bundled `LICENSE.txt` for the original text or `LICENSE_jp.txt`
for the Japanese reference translation.

Third-party software
--------------------
The GUI redistributes PDFium (pdfium.dll), Microsoft WebView2 Loader
(WebView2Loader.dll), Mermaid.js (MIT), and MathJax (Apache License 2.0).
WebView2 Runtime is not bundled; install it separately if missing.
License texts for bundled copies live with the project source
(third_party/ and resources/vendor/).

Disclaimer
----------
This software is provided as-is. The author assumes no responsibility for the use of this
software, its results, data loss, system failures, hardware damage, or any other damages.
Always back up important PDFs before editing or exporting them.

QuickMarkPDF is an independent application and is not affiliated with or endorsed by
Adobe, Microsoft, or any other third-party software vendor.
