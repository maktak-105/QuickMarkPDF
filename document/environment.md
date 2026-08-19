# Development Environment

[日本語版 environment_jp.md](environment_jp.md)

`python/` (PySide6) is the spec of record for this app — see
[`../CPP_PORT_POSTMORTEM.md`](../CPP_PORT_POSTMORTEM.md) for why a prior
C++/WebView2 port was abandoned. This document covers running the Python
version from source, building the Windows executable, and — the bulk of it —
running the automated test program.

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
