"""Timing-based smoothness/performance checks ("スムースさ").

Machine performance varies a lot, so thresholds here are deliberately
generous — the goal is to catch a severe regression or an accidental hang,
not to chase fine-grained performance numbers. Every measurement is also
appended to tests/reports/perf.json so the *actual* numbers are visible and
can be watched for drift over time, independent of the pass/fail thresholds.
"""
import json
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

pytestmark = pytest.mark.perf

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def _record(name: str, seconds: float):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "perf.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data[name] = round(seconds, 4)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def test_loading_a_50_page_pdf_completes_quickly(main_window, pdf_factory):
    pdf = pdf_factory(pages=50)
    start = time.perf_counter()
    main_window.open_pdfs([pdf])
    elapsed = time.perf_counter() - start
    _record("open_50_page_pdf_seconds", elapsed)
    assert main_window.pdf_manager.get_page_count() == 50
    assert elapsed < 15.0


def test_rotating_20_pages_is_fast(main_window, pdf_factory):
    main_window.open_pdfs([pdf_factory(pages=20)])
    start = time.perf_counter()
    main_window.pdf_manager.rotate_pages(list(range(20)), 90)
    main_window.thumbnail_panel.refresh()
    elapsed = time.perf_counter() - start
    _record("rotate_20_pages_seconds", elapsed)
    assert elapsed < 10.0


def test_reordering_is_fast(main_window, pdf_factory):
    main_window.open_pdfs([pdf_factory(pages=20)])
    start = time.perf_counter()
    new_order = main_window.thumbnail_panel._compute_new_order([0], 20)
    main_window.thumbnail_panel.page_reordered.emit(new_order, [0])
    elapsed = time.perf_counter() - start
    _record("reorder_20_pages_seconds", elapsed)
    assert elapsed < 10.0


def test_undo_is_fast(main_window, pdf_factory):
    main_window.open_pdfs([pdf_factory(pages=20)])
    main_window.pdf_manager.rotate_pages([0], 90)
    start = time.perf_counter()
    main_window.undo_last_action()
    elapsed = time.perf_counter() - start
    _record("undo_seconds", elapsed)
    assert elapsed < 10.0


def test_exporting_20_page_images_is_reasonably_fast(main_window, pdf_factory, tmp_pdf_dir, dialog_responses):
    main_window.open_pdfs([pdf_factory(pages=20)])
    out_dir = tmp_pdf_dir / "perf_export"
    out_dir.mkdir()

    def configure(dialog):
        dialog.dir_edit.setText(str(out_dir))
        dialog.scope_all.setChecked(True)
        dialog.dpi_combo.setCurrentIndex(0)  # 72 DPI — keep this a light I/O check, not a rendering benchmark
        return QDialog.DialogCode.Accepted

    dialog_responses.push("QDialog.exec:ExportDialog", configure)
    dialog_responses.allow("QMessageBox.information")

    start = time.perf_counter()
    main_window.export_images()
    elapsed = time.perf_counter() - start
    _record("export_20_page_images_seconds", elapsed)

    assert elapsed < 30.0
    assert len(list(out_dir.glob("*.png"))) == 20
