"""Shared pytest fixtures for the QuickMarkPDF (Python/PySide6) test suite.

The single most important thing in this file is `dialog_guard` (autouse):
it is the fix for the "native dialog pops up and the automated run just
sits there forever" failure mode described in CPP_PORT_POSTMORTEM.md. Every
native-dialog entry point the app uses (QFileDialog.*, QMessageBox.*,
QInputDialog.getText, QDialog.exec) is patched so that, unless a test has
explicitly queued a canned response, calling one raises immediately instead
of blocking on a human who will never show up. Combined with pytest-timeout
(configured in pyproject.toml), no test in this suite can hang indefinitely.
"""
import os

# Must happen before PySide6 is imported anywhere (including by test modules
# collected after this file), which is why this is the very first thing in
# conftest.py. Opt out with QUICKMARKPDF_REAL_SCREEN=1 (see tests/real_screen/).
if os.environ.get("QUICKMARKPDF_REAL_SCREEN") != "1":
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import tempfile
import shutil
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog


class UnexpectedDialog(RuntimeError):
    """A test path tried to show a real native dialog with no canned response
    queued for it. This is meant to fail loudly and immediately — the whole
    point is that it must never instead sit there waiting forever."""


class _DialogResponses:
    """Per-test registry of canned dialog answers, injected by `dialog_guard`."""

    def __init__(self):
        self._queues: dict[str, list] = {}
        self._defaults: dict[str, object] = {}

    def push(self, name: str, value):
        """Queue one canned return value for the next call to `name`."""
        self._queues.setdefault(name, []).append(value)
        return self

    def allow(self, name: str, value=None):
        """Permit unlimited calls to `name`, always returning `value`.

        Use for benign, non-blocking-in-practice boxes (e.g. a final
        "success" QMessageBox.information) a test doesn't care to assert on
        individually.
        """
        self._defaults[name] = value
        return self

    def resolve(self, name: str):
        queue = self._queues.get(name)
        if queue:
            return queue.pop(0)
        if name in self._defaults:
            return self._defaults[name]
        raise UnexpectedDialog(
            f"{name}() was invoked with no canned response queued and no "
            f"`dialog_responses.allow('{name}', ...)` registered. In real use "
            f"this would have opened a native dialog and blocked forever "
            f"waiting for a click that never comes — register a response "
            f"instead of letting this reach a real dialog."
        )


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp):
    """Guarantee a QApplication exists before every test body runs.

    Discovered while writing this suite: constructing a QWidget (e.g.
    QDialog()) with no QApplication yet created does not raise on this
    PySide6/Windows combination — it hangs indefinitely instead, which is
    exactly the class of failure this whole test program exists to prevent.
    Depending on pytest-qt's `qapp` fixture here means no individual test
    has to remember to request it.
    """
    return qapp


@pytest.fixture
def dialog_responses():
    """Use in a test to pre-register canned dialog answers, e.g.:

        dialog_responses.push("QFileDialog.getSaveFileName", (str(out), ""))
    """
    return _DialogResponses()


@pytest.fixture(autouse=True)
def dialog_guard(monkeypatch, dialog_responses):
    """Autouse: replaces every native-dialog call the app can make with a
    lookup into `dialog_responses`. See module docstring.
    """
    responses = dialog_responses

    def _make_static(name):
        def _fn(*_args, **_kwargs):
            return responses.resolve(name)
        return staticmethod(_fn)

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", _make_static("QFileDialog.getOpenFileNames"))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", _make_static("QFileDialog.getSaveFileName"))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", _make_static("QFileDialog.getExistingDirectory"))
    monkeypatch.setattr(QInputDialog, "getText", _make_static("QInputDialog.getText"))
    monkeypatch.setattr(QMessageBox, "information", _make_static("QMessageBox.information"))
    monkeypatch.setattr(QMessageBox, "warning", _make_static("QMessageBox.warning"))
    monkeypatch.setattr(QMessageBox, "question", _make_static("QMessageBox.question"))

    def _fake_dialog_exec(self, *_args, **_kwargs):
        name = f"QDialog.exec:{type(self).__name__}"
        value = responses.resolve(name)
        # A canned response may be a callable that configures the (real,
        # already-constructed) dialog instance before it "closes" — e.g. set
        # ExportDialog's fields — and optionally returns the exec() result.
        if callable(value):
            result = value(self)
            return result if result is not None else QDialog.DialogCode.Accepted
        return value

    monkeypatch.setattr(QDialog, "exec", _fake_dialog_exec)
    monkeypatch.setattr(QDialog, "exec_", _fake_dialog_exec, raising=False)

    return responses


@pytest.fixture
def synchronous_background(monkeypatch):
    """Patch a MainWindow instance's `_run_in_background` to run the given
    operation synchronously (no real QThread), for deterministic tests.
    Returns a function you call with the window to patch.
    """
    def _apply(window):
        monkeypatch.setattr(
            window,
            "_run_in_background",
            lambda operation, on_success, on_error=None, **_kwargs: on_success(operation()),
        )
        return window
    return _apply


@pytest.fixture
def main_window(qapp, synchronous_background, tmp_path):
    """A real MainWindow with background work forced synchronous, torn down
    cleanly after the test. Import is deferred so QT_QPA_PLATFORM is set
    first (see top of this file).

    `_qsettings` is redirected to a throwaway INI file: MainWindow.__init__
    creates `QSettings("maktak-105", "QuickMarkPDF")`, which on Windows
    reads/writes the real user's registry (HKCU\\Software\\...) — closeEvent
    in particular persists window geometry/last-used-dir there. Tests must
    not leak state into (or depend on) the real machine's settings.
    """
    from PySide6.QtCore import QSettings
    from src.pdf_editor.ui.main_window import MainWindow

    window = MainWindow()
    window._qsettings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    synchronous_background(window)
    yield window
    window.pdf_manager.close_all()
    window.deleteLater()
    qapp.processEvents()


@pytest.fixture
def tmp_pdf_dir():
    directory = Path(tempfile.mkdtemp(prefix="quickmarkpdf-test-"))
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def make_pdf(path: Path, pages: int = 2, size: tuple[float, float] = (200, 300)) -> Path:
    """Create a small multi-page PDF at `path` with page-number text on each
    page (handy for eyeballing screenshots), and return `path`.
    """
    doc = fitz.open()
    width, height = size
    for i in range(pages):
        page = doc.new_page(width=width, height=height)
        page.insert_text((20, 40), f"Page {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf_factory(tmp_pdf_dir):
    """Factory fixture: pdf_factory(name="a.pdf", pages=2) -> Path."""
    counter = {"n": 0}

    def _make(name: str | None = None, pages: int = 2, size: tuple[float, float] = (200, 300)) -> Path:
        counter["n"] += 1
        filename = name or f"doc{counter['n']}.pdf"
        return make_pdf(tmp_pdf_dir / filename, pages=pages, size=size)

    return _make
