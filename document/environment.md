# Development Environment

[日本語版 environment_jp.md](environment_jp.md)

## Status (read this first)

`python/` (PySide6) is the **spec of record**: it defines the correct
behavior, UI, and feature set that any port must match. It is not itself
what ships.

`core/native/` (C++17 + WebView2) is the **current version being built and
shipped**. A first C++/WebView2 port was attempted and fully discarded — see
[`../CPP_PORT_POSTMORTEM.md`](../CPP_PORT_POSTMORTEM.md) for why (it treated
"build passes, tests pass" as done without ever driving the real app, and
drifted from the Python spec). A second port (commits `3cb33f1` onward,
starting 2026-08-19) followed that postmortem's rules — real UI verification
plus independent file-level checks (PyMuPDF/Pillow) rather than build/test
alone — and has reached feature parity with the Python spec for most of the
toolbar; see `plans/2026-08-20_*` for the per-feature verification record and
its own listed gaps (Mermaid/MathJax, GFM tables, an `ExportDialog`
equivalent, etc.).

**In short:** when the Python and C++ versions disagree on behavior, the
Python version is right and the C++ version has a bug. When asked to "build
the app" without qualification, build the C++ version (see below) — that's
what a user runs.

---

This document covers running the Python version from source, building its
Windows executable, and — the bulk of it — running its automated test
program. For the C++ version's build, see "Building the C++/WebView2
version" below.

## Runtime requirements

- Windows 10 / 11 (64-bit)
- Python 3.11+ (developed against 3.14)

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` is what the app itself needs; `requirements-dev.txt`
adds the test toolchain (pytest, pytest-qt, pytest-timeout, pytest-cov).

## Running from source

```powershell
python python/main.py
python python/main.py path\to\file.pdf    # opens it directly, no file dialog
```

## Building the Windows executable

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

The onedir package is generated under `dist/QuickMarkPDF/`. Keep
`QuickMarkPDF.exe` and its `_internal` directory together.

## Automated tests

Run everything with one command:

```powershell
.venv\Scripts\python.exe run_tests.py
```

This runs the whole default suite via pytest, then writes
`tests/reports/summary.md` (pass rate, failures, timing table) plus a JUnit
XML and an HTML coverage report under `tests/reports/`. Exit code is
pytest's, so it's safe to use in a script. `tests/reports/` is git-ignored —
it's a generated artifact, not something to commit.

### Why a dialog guard exists

The C++ port's postmortem names two root causes of a day of wasted work:
treating "build passes, automated tests pass" as proof of correctness
without ever actually running the app, and repeatedly trying to automate
the native file-selection dialog for verification — which was never stable.

`tests/conftest.py` addresses the second one directly: an autouse
`dialog_guard` fixture patches every native-dialog entry point the app uses
(`QFileDialog.*`, `QMessageBox.*`, `QInputDialog.getText`, `QDialog.exec`).
Unless a test explicitly queues a canned answer, calling one raises
immediately instead of blocking forever waiting for a click that will never
come. Combined with a 60s per-test timeout (pytest-timeout), no test in this
suite can hang the run indefinitely.

To drive a flow that goes through a real dialog, queue a response in the
test:

```python
def test_something(main_window, dialog_responses):
    dialog_responses.push("QFileDialog.getSaveFileName", (str(out_path), "PDF Files (*.pdf)"))
    dialog_responses.allow("QMessageBox.information")  # any number of benign "success" popups
    main_window.save_pdf()
```

For a real `QDialog` subclass (e.g. `ExportDialog`, `PreferencesDialog`, or
a hand-built `QMessageBox`), the canned value can be a callable that
configures the already-constructed dialog instance before "closing" it:

```python
def configure(dialog):
    dialog.dir_edit.setText(str(out_dir))
    dialog.scope_all.setChecked(True)
    return QDialog.DialogCode.Accepted

dialog_responses.push("QDialog.exec:ExportDialog", configure)
```

An unregistered dialog call fails the test immediately with a clear
`UnexpectedDialog` message naming the call site — see
`tests/test_dialog_guard.py` for the guard's own tests.

### Test tiers

| Location | What it checks | Runs by default? |
| --- | --- | --- |
| `tests/test_*.py` | Unit tests (`PDFManager`, `MarkdownManager`) and integration tests that drive a real `MainWindow` through open/rotate/delete/reorder/undo/save/export flows | Yes |
| `tests/visual/` | Screenshot-based appearance regression (`QWidget.grab()` vs. a baseline PNG) | Yes |
| `tests/perf/` | Timing checks for load/rotate/reorder/undo/export, logged to `tests/reports/perf.json` | Yes |
| `tests/real_screen/` | Real, visible window driven with `QTest` synthetic mouse/keyboard input; screenshots saved for a human to look at | No — opt-in only |

All tests run under the offscreen Qt platform (`QT_QPA_PLATFORM=offscreen`,
set at the top of `tests/conftest.py`) unless `QUICKMARKPDF_REAL_SCREEN=1`
is set beforehand.

### Visual regression tests

Baselines live in `tests/visual_baselines/` and are committed to git. The
first run against a new baseline name creates it (and the test is reported
as skipped, since there's nothing yet to compare). Comparison uses a small
mean-pixel-difference tolerance, not exact matching, to absorb minor
rendering variance.

**Known limitation**: this development environment's offscreen Qt platform
has no CJK-capable font installed, so Japanese UI text renders as tofu boxes
in these screenshots. The baselines are still useful for catching layout/
structural regressions (panel sizes, widget placement, missing elements),
but they do **not** represent the real, Japanese-rendered appearance a user
sees — for that, use the `real_screen` tier on a normal Windows session, or
just run the app.

To intentionally refresh baselines after a deliberate UI change:

```powershell
.venv\Scripts\python.exe run_tests.py --update-visual-baselines
```

### Real-screen tier

Needs a live, unlocked Windows desktop session, and two separate opt-ins
(one before pytest starts, since `QT_QPA_PLATFORM` must not be forced to
`offscreen` before PySide6 is imported; one to select the marker):

```powershell
.venv\Scripts\python.exe run_tests.py --real-screen
# equivalent to:
$env:QUICKMARKPDF_REAL_SCREEN = "1"
.venv\Scripts\python.exe -m pytest -m real_screen tests/real_screen -v
```

These tests show the real `MainWindow`, click on it with `QTest.mouseClick`
(dispatched through the real window, not an OS-level automation tool — the
postmortem's other lesson is that those weren't stable), and save
screenshots under `tests/reports/real_screen/` for manual review. This tier
is the fallback for what automated screenshots structurally can't confirm:
that the app actually looks and behaves right when someone looks at it.

### Running a subset

```powershell
.venv\Scripts\python.exe -m pytest tests/test_pdf_manager.py -v
.venv\Scripts\python.exe run_tests.py -- tests/test_pdf_manager.py -v
```

## QA parity dashboard (Python vs. C++)

Separate from the pytest suite above, `qa/` numerically measures whether the
C++ port actually matches the Python spec — pixel sizes, HSV colors, and
observed behavior — instead of relying on a plan doc's self-reported "looks
right." See `plans/2026-08-20_C++版Python完全一致化_v1.3.md` for the full
design; summary:

```powershell
.venv\Scripts\python.exe qa\extract_python.py          # -> qa/baseline.json
.venv\Scripts\python.exe qa\check_behaviors_python.py  # -> qa/behaviors.json
.venv\Scripts\python.exe qa\dashboard.py                # -> qa/dashboard.html
```

- `extract_python.py` builds the real `MainWindow` on the real Windows
  desktop (deliberately **not** `QT_QPA_PLATFORM=offscreen` — this
  environment's offscreen platform has no CJK font, so Japanese text would
  render as tofu and the screenshot would be useless), walks every widget via
  `findChildren`, grabs one window screenshot, and samples each widget's
  rect + representative HSV from it. Every `QAction` is listed with its
  text/shortcut/enabled state/`isSeparator()`.
- `check_behaviors_python.py` drives the app's real methods and real Qt
  events (including a real `QDragEnterEvent`/`QDropEvent` for drag-reorder,
  not a shortcut through the downstream handler) — never OS-level mouse
  automation, and dialogs are answered by injecting values directly
  (`unittest.mock.patch`) rather than clicking. Currently 26/26 checks pass;
  the thumbnail-size checks measure the actual `iconSize()` pixel value the
  panel sets (`small`→108×105, `medium`→148×155, `large`→228×260), not just
  the internal size-name string.
- `dashboard.py` renders both into `qa/dashboard.html` — the artifact meant
  to be read directly, with a prose sentence per check ("dragged thumbnail 3
  to the front, page order actually became [...]"), not a bare ✓/✗. Every
  table has Python and **C++** columns side by side, read from
  `qa/baseline_cpp.json` / `qa/behaviors_cpp.json` when present (gray
  "未計測" otherwise), and matched to their Python counterparts via
  `qa/part_mapping.yaml`.

C++-side measurement is split into two independent tools that do **not**
share a transport, because they measure different things:

- `qa/check_behaviors_cpp.py` → `qa/behaviors_cpp.json`. Drives
  `PdfManager` directly over a loopback-only TCP control channel
  (`core/native/test_api_server.{h,cpp}`, gated behind the
  `QUICKMARKPDF_TEST_PORT` env var — a no-op if unset, so it's inert in a
  normal user run). This bypasses WebView2/JS entirely: the TCP thread posts
  a `WM_APP_TEST_COMMAND` to the main UI thread and blocks on a
  `condition_variable` for the result, so commands run serialized on the
  real UI thread against the real `PdfManager`. Currently **15/26 pass**;
  the rest are UI-layer-only behaviors `PdfManager` can't observe (preview
  zoom/pan, thumbnail-size buttons, the preferences dialog) or genuinely
  unimplemented C++ features (crop export, the mixed PDF/Markdown warning,
  unsaved-changes confirmation) — see `qa/behaviors_cpp.json` for the
  per-check reason.
- `qa/extract_cpp.py` → `qa/baseline_cpp.json`. Measures the actual
  rendered DOM (coordinates, colors) the way `extract_python.py` measures
  Qt widgets, so it has to go through WebView2's real Chromium renderer —
  the TCP API has no concept of pixel layout. It attaches Microsoft Edge
  WebDriver (`msedgedriver.exe`, must match the installed WebView2 Runtime
  version — not committed, fetch it separately) to the running WebView2
  instance via `EdgeOptions.use_webview` / `debugger_address` pointed at
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`, then
  walks the DOM with `execute_script`. **Known-unstable**: polling
  `execute_script`/`Runtime.evaluate` faster than about once/second starves
  the WebView2 renderer's main thread and the C++↔JS `postMessage` bridge
  stops answering entirely — `qa/selenium_client.py` works around this with
  a single fixed `time.sleep()` instead of a poll loop, but `connect()`
  attaching WebDriver still intermittently raises
  `SessionNotCreatedException`, root cause not yet isolated. Treat a fresh
  `qa/baseline_cpp.json` / visual parity number as **not yet reliably
  reproducible** until that's fixed.

Both `check_behaviors_cpp.py` and `extract_cpp.py` launch the exe with
`QUICKMARKPDF_OFFSCREEN=1` set, which makes `webview_main.cpp` create the
main window `WS_EX_LAYERED` with `SetLayeredWindowAttributes(hwnd, 0, 0,
LWA_ALPHA)` (fully transparent, not moved off-screen — an earlier
off-screen-coordinates approach made the WebView2 message bus flaky, likely
because DWM stops compositing/optimizing rendering for a window parked
outside the visible desktop). **Never launch the exe for QA purposes
without this flag** — the app must not become visible on screen during
automated measurement.

## Building the C++/WebView2 version

This is the current shippable build (see "Status" above). Source lives in
`core/native/`, `templates/`, `static/`.

```powershell
# One-time: fetch SDKs into third_party/ (gitignored, not committed)
powershell -File scripts\fetch_webview2_sdk.ps1
powershell -File scripts\fetch_pdfium.ps1

# Build
python build_native.py            # also runs core/native/engine_tests.cpp
python build_native.py --skip-tests
```

Needs a MinGW-w64 `g++`/`clang++` on PATH (or under one of the fallback
paths `build_native.py` checks, including a WinGet-installed WinLibs UCRT
toolchain). Requires C++17, `-static` linking for the shipped binaries so
they don't need the compiler's runtime DLLs at the user's machine — note the
standalone `engine_tests.cpp` build is **not** `-static`, so it does need
`libgcc_s_seh-1.dll`/`libstdc++-6.dll` next to it or on PATH.

Output: `dist/binary/QuickMarkPDF.exe` (+ `pdfium.dll`, `WebView2Loader.dll`,
bundled `index.html`) is the app to hand to a user. `QuickMarkPDF_cli.exe` is
a lightweight non-GUI demo/verification binary, not part of the shipped app.

**Known environment quirk:** on machines running CrowdStrike Falcon Sensor
(confirmed on this dev machine, "悪意のある振る舞いが検知されたため、プロセスは
ブロックされました" — 13+ notifications from one build), a freshly-built,
unsigned `.exe` can get flagged and blocked moments after being
written/executed. Observed: `QuickMarkPDF_cli.exe` vanishing from
`dist/binary/` right after a successful build, and `engine_tests.exe`'s
first run failing with `STATUS_ENTRYPOINT_NOT_FOUND` (exit code
`3221225785`) before succeeding on a clean re-run. If a fresh build's tests
fail with that exact exit code, re-run before assuming a real regression —
check whether the binary still exists first. `QuickMarkPDF.exe` itself
survived in the one incident observed so far, but if Falcon starts blocking
the shipped GUI binary too, the fix is an IT-side exclusion for the build
output path, not a code change.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'src'` | Don't run `unittest`/`pytest` directly without the project root as `cwd` — `pyproject.toml`'s `pythonpath = ["python"]` handles this automatically for `pytest`; for a plain script use `PYTHONPATH=python`. |
| A test hangs and never returns | Should not happen — file an issue against `dialog_guard`/`pytest-timeout` if it does. Check whether the code path constructs a `QWidget` before a `QApplication` exists (observed to hang rather than raise on this Qt/Windows combination); `tests/conftest.py`'s autouse `_ensure_qapp` fixture exists specifically to prevent that. |
| Visual test fails after an intentional UI change | Re-run with `--update-visual-baselines`, review the new PNGs under `tests/visual_baselines/`, and commit them. |
| `QtWebEngine not available` skip on Markdown tests | Expected in some environments; `PySide6-Addons` provides it. Not a test failure. |

## Dependencies

No third-party C++ library dependencies. See `requirements.txt` (runtime:
PyMuPDF, PySide6, Pillow, Markdown, PyInstaller) and `requirements-dev.txt`
(test-only: pytest, pytest-qt, pytest-timeout, pytest-cov).
