"""Integration tests that drive the real MainWindow through the operation
flows a user actually performs: open, rotate, delete, reorder, undo,
save/save-as/overwrite, image export, PDF cut-out, password-protected open,
and the unsaved-changes close confirmation.

Every path that would normally show a native dialog goes through the
`dialog_guard` fixture (see conftest.py) instead of a real one — this suite
exists specifically so these flows can be exercised end-to-end without ever
risking the "dialog pops up and the run just sits there" failure mode.
"""
import fitz
import pytest
from PySide6.QtWidgets import QMessageBox, QDialog


def test_open_pdfs_with_explicit_list_skips_dialog_entirely(main_window, pdf_factory):
    """The CLI-args path (`main.py` -> `open_documents(files=[...])`) never
    touches QFileDialog — this is the bypass CPP_PORT_POSTMORTEM.md points to.
    No dialog_responses are registered here on purpose: if the app tried to
    show a dialog, this test would fail immediately via dialog_guard.
    """
    pdf = pdf_factory(pages=3)
    main_window.open_pdfs([pdf])
    assert main_window.pdf_manager.get_page_count() == 3
    assert main_window.thumbnail_panel.count() == 3
    assert main_window._is_dirty is False


def test_open_documents_with_no_args_uses_the_real_file_dialog(main_window, pdf_factory, dialog_responses):
    """Exercises the actual QFileDialog.getOpenFileNames call site in
    open_documents(), via a canned response instead of a real dialog.
    """
    pdf = pdf_factory(pages=2)
    dialog_responses.push("QFileDialog.getOpenFileNames", ([str(pdf)], "PDF Files (*.pdf)"))
    main_window.open_documents()
    assert main_window.pdf_manager.get_page_count() == 2


def test_open_password_protected_pdf_prompts_and_unlocks(main_window, tmp_pdf_dir, dialog_responses):
    locked = tmp_pdf_dir / "locked.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(locked), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret123", owner_pw="secret123")
    doc.close()

    dialog_responses.push("QInputDialog.getText", ("secret123", True))
    main_window.open_pdfs([locked])
    assert main_window.pdf_manager.get_page_count() == 1


def test_open_password_protected_pdf_cancelled_leaves_nothing_loaded(main_window, tmp_pdf_dir, dialog_responses):
    locked = tmp_pdf_dir / "locked.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(locked), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret123", owner_pw="secret123")
    doc.close()

    dialog_responses.push("QInputDialog.getText", ("", False))  # user hit Cancel
    dialog_responses.allow("QMessageBox.warning")  # "could not open" notice
    main_window.open_pdfs([locked])
    assert main_window.pdf_manager.get_page_count() == 0


def test_rotate_current_page_marks_dirty_and_persists(main_window, pdf_factory):
    main_window.open_pdfs([pdf_factory(pages=2)])
    main_window.thumbnail_panel.setCurrentRow(0)

    main_window.rotate_current_page(90)

    assert main_window.pdf_manager.all_pages[0].rotation == 90
    assert main_window._is_dirty is True


def test_delete_selected_pages_updates_count_and_selection(main_window, pdf_factory):
    main_window.open_pdfs([pdf_factory(pages=3)])
    main_window.thumbnail_panel.setCurrentRow(1)

    main_window.delete_selected_pages()

    assert main_window.pdf_manager.get_page_count() == 2
    assert main_window._is_dirty is True


def test_undo_after_rotate_restores_original_state(main_window, pdf_factory):
    main_window.open_pdfs([pdf_factory(pages=2)])
    main_window.thumbnail_panel.setCurrentRow(0)
    main_window.rotate_current_page(90)
    assert main_window.pdf_manager.all_pages[0].rotation == 90

    main_window.undo_last_action()

    assert main_window.pdf_manager.all_pages[0].rotation == 0


def test_drag_reorder_via_real_signal_updates_page_order(main_window, pdf_factory):
    """Emits the real ThumbnailPanel.page_reordered signal MainWindow is
    connected to, rather than calling the private handler directly.
    """
    main_window.open_pdfs([pdf_factory(pages=3)])
    original = [info.original_page_index for info in main_window.pdf_manager.page_infos]
    assert original == [0, 1, 2]

    new_order = main_window.thumbnail_panel._compute_new_order([0], 3)
    main_window.thumbnail_panel.page_reordered.emit(new_order, [0])

    assert [info.original_page_index for info in main_window.pdf_manager.page_infos] == [1, 2, 0]
    assert main_window._is_dirty is True


def test_save_pdf_overwrites_single_source_file_in_place(main_window, pdf_factory, dialog_responses):
    pdf = pdf_factory(pages=1)
    main_window.open_pdfs([pdf])
    main_window.thumbnail_panel.setCurrentRow(0)
    main_window.rotate_current_page(90)
    assert main_window.pdf_manager.can_overwrite_source() is True

    def click_overwrite(box):
        box.buttons()[0].click()  # first button added by _ask_overwrite_or_save_as is "上書き保存"

    dialog_responses.push("QDialog.exec:QMessageBox", click_overwrite)

    main_window.save_pdf()

    assert main_window._is_dirty is False
    with fitz.open(str(pdf)) as reopened:
        assert reopened[0].rotation == 90


def test_save_pdf_as_new_file_when_multiple_sources_open(main_window, pdf_factory, tmp_pdf_dir, dialog_responses):
    main_window.open_pdfs([pdf_factory(name="a.pdf", pages=1), pdf_factory(name="b.pdf", pages=1)])
    assert main_window.pdf_manager.can_overwrite_source() is False

    out_path = tmp_pdf_dir / "combined.pdf"
    dialog_responses.push("QFileDialog.getSaveFileName", (str(out_path), "PDF Files (*.pdf)"))
    dialog_responses.allow("QMessageBox.information")  # "完了" notice

    main_window.save_pdf()

    assert out_path.exists()
    assert main_window._is_dirty is False
    with fitz.open(str(out_path)) as saved:
        assert saved.page_count == 2


def test_save_pdf_as_cancelled_dialog_does_not_mark_clean(main_window, pdf_factory, dialog_responses):
    main_window.open_pdfs([pdf_factory(name="a.pdf", pages=1), pdf_factory(name="b.pdf", pages=1)])
    main_window._mark_dirty()

    dialog_responses.push("QFileDialog.getSaveFileName", ("", ""))  # user cancelled

    main_window.save_pdf()

    assert main_window._is_dirty is True


def test_split_document_exports_selected_pages_as_new_pdf(main_window, pdf_factory, tmp_pdf_dir, dialog_responses):
    main_window.open_pdfs([pdf_factory(pages=4)])
    main_window.thumbnail_panel.setCurrentRow(1)

    out_path = tmp_pdf_dir / "cutout.pdf"
    dialog_responses.push("QFileDialog.getSaveFileName", (str(out_path), "PDF Files (*.pdf)"))
    dialog_responses.allow("QMessageBox.information")

    main_window.split_document()

    assert out_path.exists()
    with fitz.open(str(out_path)) as saved:
        assert saved.page_count == 1


def test_export_images_writes_png_files_for_all_pages(main_window, pdf_factory, tmp_pdf_dir, dialog_responses):
    main_window.open_pdfs([pdf_factory(pages=3)])
    out_dir = tmp_pdf_dir / "images_out"
    out_dir.mkdir()

    def configure_export(dialog):
        dialog.dir_edit.setText(str(out_dir))
        dialog.scope_all.setChecked(True)  # export all 3 pages, not just the current selection
        return QDialog.DialogCode.Accepted

    dialog_responses.push("QDialog.exec:ExportDialog", configure_export)
    dialog_responses.allow("QMessageBox.information")

    main_window.export_images()

    produced = sorted(out_dir.glob("*.png"))
    assert len(produced) == 3


def test_closing_with_unsaved_changes_asks_and_respects_cancel(main_window, pdf_factory, dialog_responses):
    main_window.open_pdfs([pdf_factory(pages=1)])
    main_window._mark_dirty()

    dialog_responses.push("QMessageBox.question", QMessageBox.StandardButton.No)

    closed = main_window.close()

    # Declined discard: QWidget.close() returns False when closeEvent ignored it.
    assert closed is False
    assert main_window._is_dirty is True


def test_open_preferences_dialog_updates_wheel_mode(main_window, dialog_responses):
    assert main_window._wheel_mode == "zoom"

    def choose_scroll_mode(dialog):
        dialog.wheel_scroll.setChecked(True)
        return QDialog.DialogCode.Accepted

    dialog_responses.push("QDialog.exec:PreferencesDialog", choose_scroll_mode)
    main_window._open_preferences()

    assert main_window._wheel_mode == "scroll"


def test_open_preferences_dialog_cancelled_keeps_previous_mode(main_window, dialog_responses):
    dialog_responses.push("QDialog.exec:PreferencesDialog", QDialog.DialogCode.Rejected)
    main_window._open_preferences()
    assert main_window._wheel_mode == "zoom"


def test_load_markdown_document_switches_to_markdown_mode(main_window, tmp_pdf_dir):
    if main_window.markdown_view is None:
        pytest.skip("QtWebEngine not available in this environment")

    md_path = tmp_pdf_dir / "note.md"
    md_path.write_text("# Hello\n\nSome *text*.\n", encoding="utf-8")

    main_window._load_markdown_document(md_path)

    assert main_window.current_mode == "markdown"
    assert main_window.current_markdown_document is not None
    assert main_window.current_markdown_document.path == md_path


def test_closing_with_unsaved_changes_confirmed_proceeds(main_window, pdf_factory, dialog_responses):
    main_window.open_pdfs([pdf_factory(pages=1)])
    main_window._mark_dirty()

    dialog_responses.push("QMessageBox.question", QMessageBox.StandardButton.Yes)

    accepted = main_window.close()

    assert accepted is True

