# Development Environment

[日本語版 environment_jp.md](environment_jp.md)

## Status (read this first)

`core/native/` (C++17 + WebView2) is the **shipped product**. When asked to
"build the app" without qualification, build this version.

`python/prototype/` (PySide6) is a **development-time evaluation prototype**. It is
not distributed. It remains in the tree so page-editing behavior can still
be compared during development. Visual match with the Python UI is **not**
a goal — the native GUI uses the Modern Dark theme on purpose.

A first C++/WebView2 port was fully discarded. See
[`../CPP_PORT_POSTMORTEM.md`](../CPP_PORT_POSTMORTEM.md) for why (it treated
"build passes, tests pass" as done without driving the real app). The second
port (from 2026-08-19) is what ships as v1.2.1.

**In short:** users run the C++ GUI. Python is a prototype, not the spec of
the shipped UI. If page-editing behavior differs, investigate both; the C++
build is what must be correct for a user.

---

## Runtime requirements

- Windows 10 / 11 (64-bit)
- Microsoft Edge WebView2 Runtime (to run the GUI)
- Python 3.11+ (build scripts; developed against 3.14)
- MinGW-w64 C++17 compiler and `windres` (WinLibs MCF UCRT)

## Setup

### MinGW toolchain

```powershell
winget install --id BrechtSanders.WinLibs.MCF.UCRT --exact --source winget
```

Standard install location:

```text
%LOCALAPPDATA%\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.MCF.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin
```

`build_native.py` searches this location automatically and uses `windres.exe`
next to the detected compiler, so PATH registration is not required just to
build. Add `mingw64\bin` to the **user** PATH only if you want to invoke
`g++` / `windres` directly (restart the terminal/IDE afterward).

### WebView2 SDK and PDFium

Both are fetched into `third_party/` (gitignored, not committed):

```powershell
powershell -File scripts\fetch_webview2_sdk.ps1
powershell -File scripts\fetch_pdfium.ps1
```

Default search paths (override with env vars if needed):

| Component | Default | Env var |
| --- | --- | --- |
| WebView2 headers | `third_party/webview2/build/native/include` | `WEBVIEW2_INCLUDE` |
| PDFium headers | `third_party/pdfium/include` | `PDFIUM_INCLUDE` |

## Building the shipped native version

```powershell
python build_native.py            # also runs core/native/engine_tests.cpp
python build_native.py --skip-tests
```

### What `build_native.py` does

1. Detects `g++` or `clang++` (PATH, then the WinGet WinLibs location, then a few fallbacks).
2. Runs `bundle_html.py`: inlines CSS/JS/images into `dist/binary/index.html`, leaving Mermaid/MathJax as `vendor/` script tags.
3. Compiles the `.rc` (icon + version info) with `windres` / `llvm-windres`.
4. Statically links (`-static`) `webview_main.cpp` + engine into `QuickMarkPDF.exe`.
5. Statically links the CLI demo into `QuickMarkPDF_cli.exe`.
6. Copies `pdfium.dll`, `WebView2Loader.dll`, and `resources/vendor/` into `dist/binary/`.
7. Unless `--skip-tests`, builds and runs `engine_tests.cpp` (this test exe is **not** `-static`, so MinGW runtime DLLs are copied next to it).

### Build output

| File | Description |
| --- | --- |
| `dist/binary/QuickMarkPDF.exe` | GUI (shipped app) |
| `dist/binary/QuickMarkPDF_cli.exe` | Non-GUI page-model demo |
| `dist/binary/pdfium.dll` | PDFium |
| `dist/binary/WebView2Loader.dll` | WebView2 loader |
| `dist/binary/index.html` | Bundled GUI |
| `dist/binary/vendor/` | Mermaid.js and MathJax |
| `core/native/QuickMarkPDF_native_tests.exe` | Engine tests (not shipped) |

Keep `QuickMarkPDF.exe`, `pdfium.dll`, `WebView2Loader.dll`, `index.html`, and
`vendor/` in the same folder.

**Known environment quirk:** on machines running CrowdStrike Falcon Sensor
(confirmed on this dev machine), a freshly-built unsigned `.exe` can be
flagged and blocked. Observed: `QuickMarkPDF_cli.exe` vanishing from
`dist/binary/` right after a successful build, and `engine_tests.exe`
failing once with `STATUS_ENTRYPOINT_NOT_FOUND` (exit `3221225785`) then
succeeding on a clean re-run. Re-run and check that the binary still exists
before treating that exit code as a real regression. If Falcon blocks the
GUI binary, the fix is an IT exclusion for the build output path, not a
code change.

Never terminate WebView2 processes by image name. `msedgewebview2.exe` is
shared by Teams, Windows Search, and other apps. Stop only
`QuickMarkPDF.exe` by PID (`taskkill /PID <pid> /T /F`).

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| WebView2 headers not found | Run `scripts\fetch_webview2_sdk.ps1`, or set `WEBVIEW2_INCLUDE` |
| PDFium headers/DLL not found | Run `scripts\fetch_pdfium.ps1` |
| `windres` not found | It lives next to the compiler; PATH changes need a terminal restart |
| White/blank GUI | Rebuild so `index.html` is bundled; confirm `vendor/` sits beside it |
| GUI will not start (Runtime) | Install Microsoft Edge WebView2 Runtime (Evergreen) |
| `g++` / `windres` not found when invoked directly | Add WinLibs `mingw64\bin` to user PATH — not needed for `build_native.py` |
| Fresh unsigned exe disappears or tests fail with exit `3221225785` | CrowdStrike quirk above; re-run before assuming a regression |
| `ModuleNotFoundError: No module named 'src'` | Python tests need the repo root as cwd (`pyproject.toml` sets `pythonpath = ["python/prototype"]`) |

## Evaluation prototype (Python)

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python python/prototype/main.py
python python/prototype/main.py path\to\file.pdf
```

PyInstaller onedir (not shipped):

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

Output: `dist/QuickMarkPDF/` (`QuickMarkPDF.exe` plus `_internal`).

### Python automated tests

```powershell
.venv\Scripts\python.exe python/tests/run_tests.py
```

This runs the default pytest suite, then writes `python/tests/reports/summary.md`
plus JUnit XML and HTML coverage under `python/tests/reports/` (gitignored).

`python/tests/conftest.py` installs an autouse `dialog_guard` that patches
`QFileDialog` / `QMessageBox` / `QInputDialog` / `QDialog.exec`. An
unregistered dialog fails immediately instead of hanging. Combined with a
60s per-test timeout, the suite cannot wait forever for a click.

| Location | What it checks | Default? |
| --- | --- | --- |
| `python/tests/test_*.py` | Unit + `MainWindow` flows (open/rotate/delete/reorder/undo/save/export) | Yes |
| `python/tests/visual/` | Screenshot regression vs `python/tests/visual_baselines/` | Yes |
| `python/tests/perf/` | Timing for load/rotate/reorder/undo/export | Yes |
| `python/tests/real_screen/` | Visible window + `QTest` input | No (`--real-screen`) |

Tests use offscreen Qt (`QT_QPA_PLATFORM=offscreen`) unless
`QUICKMARKPDF_REAL_SCREEN=1`. Offscreen Qt in this environment has no CJK
font, so Japanese UI text is tofu in visual baselines — they catch layout
regressions, not real Japanese rendering.

```powershell
.venv\Scripts\python.exe run_tests.py --update-visual-baselines
.venv\Scripts\python.exe run_tests.py --real-screen
.venv\Scripts\python.exe -m pytest tests/test_pdf_manager.py -v
```

## QA parity dashboard (Python vs C++)

`qa/` measures whether the C++ build still matches the prototype on
**page-editing behavior**. Pixel/HSV match with the Python UI is no longer
a goal after the dark-theme switch.

```powershell
.venv\Scripts\python.exe qa\extract_python.py          # -> qa/baseline.json
.venv\Scripts\python.exe qa\check_behaviors_python.py  # -> qa/behaviors.json
.venv\Scripts\python.exe qa\check_behaviors_cpp.py     # -> qa/behaviors_cpp.json (TCP API)
.venv\Scripts\python.exe qa\check_ui_behaviors_cpp.py  # UI-layer checks via WebDriver
.venv\Scripts\python.exe qa\dashboard.py               # -> qa/dashboard.html
```

As of 2026-08-21:

- `check_behaviors_cpp.py`: 18/26 pass. The rest are UI-layer-only (preview
  zoom/pan, thumbnail-size buttons, preferences) that `PdfManager` cannot
  observe over TCP.
- `check_ui_behaviors_cpp.py`: 9/9 pass.
- Merged `qa/behaviors_cpp.json`: **27/27 pass**.
- `qa/extract_cpp.py` (DOM coordinates/colors via Edge WebDriver) remains
  **known-unstable**. Polling `execute_script` faster than about once a
  second can starve the WebView2 renderer. Treat a fresh
  `qa/baseline_cpp.json` as not yet reliably reproducible.

C++ measurement tools launch the exe with `QUICKMARKPDF_OFFSCREEN=1`
(`WS_EX_LAYERED` + alpha 0). **Never launch the exe for QA without this
flag** if the window must stay invisible.

The TCP control channel (`core/native/test_api_server.cpp`) is gated on
`QUICKMARKPDF_TEST_PORT`. It is a no-op if unset. Command names there
(`load_pdfs`, `undo`, `save_as`, …) are test-only and are not the GUI
WebMessage protocol documented in [`spec.md`](spec.md).

## Dependencies

Shipped C++ binary: PDFium (`pdfium.dll`) plus the Windows WebView2 Runtime
and WIC. Frontend is framework-free. Mermaid.js and MathJax are bundled
under `vendor/` for Markdown preview.

Python prototype / tests: `requirements.txt` (PyMuPDF, PySide6, Pillow,
Markdown, PyInstaller) and `requirements-dev.txt` (pytest, pytest-qt,
pytest-timeout, pytest-cov). QA extras: `python/qa/requirements-qa.txt`.

## File structure (shipped layout)

```text
QuickMarkPDF/
├── .github/workflows/     ci.yml, release.yml (native ZIP on v* tags)
├── core/native/           C++ engine, WebView2 host, CLI demo, resources
├── templates/             development HTML
├── static/                development CSS/JS
├── python/prototype/      evaluation prototype (not shipped)
├── python/tests/          Python prototype tests
├── python/qa/             Python vs C++ behavior dashboard
├── python/tools/          helper scripts
├── scripts/               fetch_webview2_sdk.ps1, fetch_pdfium.ps1
├── resources/vendor/      Mermaid / MathJax source copied to dist/binary/vendor/
├── assets/                README screenshots (not in the ZIP)
├── document/              developer docs (en + _jp)
├── plans/                 dated plans and results
├── dist/binary/           native build output (gitignored except folder)
├── dist/documents/        shipped txt (readme / history / LICENSE)
├── build_native.py
├── bundle_html.py
├── README.md / README_jp.md
└── HISTORY.md / HISTORY_jp.md
```

## Remaining work (build/CI, not the app)

- GitHub Release for v1.2.1 is not published yet (v1.1.0 has been published).
- `.github/workflows/ci.yml` and `release.yml` still run a PyInstaller
  (Python) build. They do **not** produce the shipped native binary.
- `QuickMarkPDF_cli.exe` has no product-grade `--option` interface.
- Nested lists in Markdown are not implemented.
- Page rendering/export in the native build is synchronous (no parallel
  render of large page counts).
