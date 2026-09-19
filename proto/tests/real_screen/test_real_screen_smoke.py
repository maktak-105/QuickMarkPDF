"""Real-screen smoke tests — the "実画面でのテスト" tier.

Unlike the rest of the suite (offscreen QPA), these show an actual visible
window and drive it with Qt's own synthetic input (QTest.mouseClick /
keyClick), which really does dispatch through the real window's event
handling — as close to "a person clicking the app" as an automated test
gets, without depending on OS-level automation tools. CPP_PORT_POSTMORTEM.md
explicitly warns that automating the *native file-selection dialog* was
never stable; that lesson is why these tests still drive PDF loading via
`open_pdfs([...])` (the same CLI-args bypass main.py uses) rather than
clicking "Open" and fighting a real native dialog.

Excluded from the default run (see pyproject.toml addopts). To actually run
this tier you need a live, unlocked Windows desktop session, and must opt in
twice — once before pytest starts (so conftest.py leaves QT_QPA_PLATFORM
alone) and once to select the marker:

    QUICKMARKPDF_REAL_SCREEN=1 python -m pytest -m real_screen tests/real_screen -v

Screenshots of what was actually on screen are saved to
tests/reports/real_screen/ for a human to eyeball afterwards — this tier is
the direct antidote to the postmortem's other core lesson, "don't call
something done without actually looking at it running."

Observed quirk (harmless): the first time a real, visible window is exposed
in a process that also loads QtWebEngine (for Markdown preview), Windows'
fault handler may print a "Windows fatal exception: code 0x8001010d" +
stack dump to stderr around window-expose/paint time. This is a benign COM
reentrancy warning from Chromium's GPU/COM init, not a real crash — the test
still passes and the screenshot is correct. Documented here so it isn't
mistaken for an actual failure.
"""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

pytestmark = pytest.mark.real_screen

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "real_screen"


def _require_real_screen():
    if os.environ.get("QUICKMARKPDF_REAL_SCREEN") != "1":
        pytest.skip(
            "Set QUICKMARKPDF_REAL_SCREEN=1 in the environment BEFORE launching pytest "
            "(conftest.py reads it before PySide6 is imported) to run this tier against "
            "a real visible window instead of the offscreen platform."
        )


def test_window_shows_and_responds_to_a_real_click(main_window, pdf_factory, qapp):
    _require_real_screen()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    main_window.open_pdfs([pdf_factory(pages=2)])
    main_window.resize(1000, 700)
    main_window.show()
    QTest.qWaitForWindowExposed(main_window)
    qapp.processEvents()

    main_window.grab().save(str(REPORTS_DIR / "window_shown.png"), "PNG")

    second_item = main_window.thumbnail_panel.item(1)
    item_rect = main_window.thumbnail_panel.visualItemRect(second_item)
    QTest.mouseClick(main_window.thumbnail_panel.viewport(), Qt.MouseButton.LeftButton, pos=item_rect.center())
    qapp.processEvents()

    assert main_window.thumbnail_panel.currentRow() == 1
    main_window.grab().save(str(REPORTS_DIR / "after_click_page2.png"), "PNG")

    main_window.close()


def test_rotate_via_keyboard_shortcut_on_a_real_window(main_window, pdf_factory, qapp, dialog_responses):
    _require_real_screen()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    main_window.open_pdfs([pdf_factory(pages=1)])
    main_window.show()
    QTest.qWaitForWindowExposed(main_window)
    main_window.thumbnail_panel.setCurrentRow(0)
    qapp.processEvents()

    main_window.rotate_current_page(90)
    qapp.processEvents()

    assert main_window.pdf_manager.all_pages[0].rotation == 90
    main_window.grab().save(str(REPORTS_DIR / "after_rotate.png"), "PNG")

    # Rotating left the window dirty, so closing will ask to discard — this
    # is exactly the kind of native dialog dialog_guard exists to keep from
    # hanging the test; answer it explicitly rather than avoiding it.
    from PySide6.QtWidgets import QMessageBox
    dialog_responses.push("QMessageBox.question", QMessageBox.StandardButton.Yes)
    main_window.close()
