"""Screenshot-based appearance regression tests ("見た目").

`QWidget.grab()` renders the widget even under the offscreen QPA platform
(it's a real software rasterizer, just not shown on a physical screen), so
these run in the default headless suite — no real display required.

Baselines live in tests/visual_baselines/ and are meant to be committed to
git as the reference images. First run against a fresh name creates the
baseline (and skips, since there's nothing yet to compare against). Set
QUICKMARKPDF_UPDATE_VISUAL_BASELINES=1 to intentionally refresh a baseline
after a deliberate UI change.

Pixel-perfect matching is not the goal (font hinting/anti-aliasing differs
slightly across machines) — a small mean-difference tolerance absorbs that
while still catching real layout/appearance regressions.
"""
import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

pytestmark = pytest.mark.visual

BASELINE_DIR = Path(__file__).resolve().parent.parent / "visual_baselines"
FAILURES_DIR = Path(__file__).resolve().parent.parent / "reports" / "visual_failures"
UPDATE_BASELINES = os.environ.get("QUICKMARKPDF_UPDATE_VISUAL_BASELINES") == "1"
DIFF_TOLERANCE = 3.0  # mean per-channel difference, 0-255 scale


def _grab(widget, tmp_path: Path, name: str) -> Image.Image:
    path = tmp_path / f"{name}.png"
    widget.grab().save(str(path), "PNG")
    return Image.open(path).convert("RGB")


def _assert_matches_baseline(actual: Image.Image, name: str):
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = BASELINE_DIR / f"{name}.png"

    if UPDATE_BASELINES or not baseline_path.exists():
        actual.save(baseline_path)
        pytest.skip(
            f"'{name}': baseline {'updated' if UPDATE_BASELINES else 'created (first run)'} "
            f"at {baseline_path} — nothing to compare against yet."
        )

    baseline = Image.open(baseline_path).convert("RGB")
    if baseline.size != actual.size:
        FAILURES_DIR.mkdir(parents=True, exist_ok=True)
        actual.save(FAILURES_DIR / f"{name}_actual.png")
        pytest.fail(f"'{name}': size differs from baseline ({actual.size} vs {baseline.size})")

    diff = ImageChops.difference(baseline, actual)
    mean_diff = sum(ImageStat.Stat(diff).mean) / 3
    if mean_diff > DIFF_TOLERANCE:
        FAILURES_DIR.mkdir(parents=True, exist_ok=True)
        actual.save(FAILURES_DIR / f"{name}_actual.png")
        diff.save(FAILURES_DIR / f"{name}_diff.png")
        pytest.fail(
            f"'{name}': visual diff mean={mean_diff:.2f} exceeds tolerance {DIFF_TOLERANCE} "
            f"(baseline: {baseline_path}, actual/diff saved under {FAILURES_DIR})"
        )


def _settle(qapp, window):
    window.resize(900, 650)
    qapp.processEvents()
    qapp.processEvents()


def test_main_window_appearance_empty_state(main_window, qapp, tmp_path):
    _settle(qapp, main_window)
    _assert_matches_baseline(_grab(main_window, tmp_path, "main_window_empty"), "main_window_empty")


def test_main_window_appearance_with_pdf_loaded(main_window, pdf_factory, qapp, tmp_path):
    main_window.open_pdfs([pdf_factory(name="a.pdf", pages=3)])
    main_window.thumbnail_panel.setCurrentRow(0)
    _settle(qapp, main_window)
    _assert_matches_baseline(_grab(main_window, tmp_path, "main_window_pdf_loaded"), "main_window_pdf_loaded")


def test_thumbnail_panel_appearance(main_window, pdf_factory, qapp, tmp_path):
    main_window.open_pdfs([pdf_factory(name="a.pdf", pages=3)])
    _settle(qapp, main_window)
    _assert_matches_baseline(
        _grab(main_window.thumbnail_panel, tmp_path, "thumbnail_panel_three_pages"),
        "thumbnail_panel_three_pages",
    )


def test_preview_label_appearance_after_page_select(main_window, pdf_factory, qapp, tmp_path):
    main_window.open_pdfs([pdf_factory(name="a.pdf", pages=2)])
    main_window.thumbnail_panel.setCurrentRow(0)
    _settle(qapp, main_window)
    _assert_matches_baseline(
        _grab(main_window.preview_label, tmp_path, "preview_label_page1"),
        "preview_label_page1",
    )
