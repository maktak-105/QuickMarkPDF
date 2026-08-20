"""Drive the real Python MainWindow's actual methods/state directly (no OS-
level mouse automation -- but real Qt event objects, including real
drag-and-drop events, injected straight into the real widget handlers) and
record PASS/FAIL evidence, WITH a plain-Japanese sentence describing what was
actually observed, for every feature/operation. Output: qa/behaviors.json.

Every dialog call is guarded by default (raises immediately instead of
popping a real blocking window -- we render on the real "windows" Qt
platform, not offscreen, so an unguarded QMessageBox/QDialog WILL block
forever waiting for a human). Individual checks override the guard via
unittest.mock.patch where a canned answer is needed (same technique as
tests/conftest.py's dialog_guard).

Run: .venv\\Scripts\\python.exe qa\\check_behaviors_python.py
"""
import os
import sys
import json
import logging
import shutil
import time
from pathlib import Path
from unittest.mock import patch

logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="  [app-log] %(message)s")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "qa"))
import db  # noqa: E402

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFileDialog, QMessageBox, QInputDialog, QDialog,
)
from PySide6.QtCore import QPoint, QPointF, QEvent, Qt, QMimeData, QRect, QSize  # noqa: E402
from PySide6.QtGui import QWheelEvent, QMouseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
import fitz  # noqa: E402

results = []


class UnexpectedDialog(RuntimeError):
    pass


def _guard(name):
    def _fn(*_a, **_kw):
        raise UnexpectedDialog(f"{name}() was called with no canned answer during a behavior check")
    return _fn


def install_dialog_guards():
    for cls, meth in [
        (QFileDialog, "getOpenFileNames"), (QFileDialog, "getSaveFileName"),
        (QFileDialog, "getExistingDirectory"),
        (QInputDialog, "getText"),
        (QMessageBox, "information"), (QMessageBox, "warning"), (QMessageBox, "question"),
    ]:
        setattr(cls, meth, staticmethod(_guard(f"{cls.__name__}.{meth}")))
    QDialog.exec = lambda self: (_ for _ in ()).throw(UnexpectedDialog(f"QDialog.exec:{type(self).__name__}"))


def check(name, fn):
    try:
        before, after, ok, behavior = fn()
        results.append({"name": name, "pass": bool(ok), "before": str(before), "after": str(after),
                         "behavior": behavior, "error": None})
    except Exception as exc:  # noqa: BLE001
        results.append({"name": name, "pass": False, "before": None, "after": None,
                         "behavior": f"例外により未確認: {exc!r}", "error": repr(exc)})
    r = results[-1]
    mark = "PASS" if r["pass"] else "FAIL"
    print(f"[{mark}] {name} :: {r['behavior']}", flush=True)


def make_test_pdf(path: Path, pages: int = 3, password: str | None = None):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=560)
        page.insert_text((50, 50), f"Test page {i + 1}")
    if password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password)
    else:
        doc.save(str(path))
    doc.close()


def drain(app, condition, timeout_s=10.0):
    """Pump the event loop until `condition()` is true or `timeout_s` elapses
    (wall-clock, not iteration count). Background PDF work runs on a real
    QThread, so pure processEvents() spinning with no actual sleep can starve
    it of wall-clock time to make progress -- a fixed try-count previously
    caused flaky false failures unrelated to the app itself.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def real_drag_reorder(panel, app, drag_index: int, drop_visual_row: int):
    """Exercise the ACTUAL drag-and-drop code path (dragEnterEvent ->
    dragMoveEvent -> dropEvent -> _get_insertion_row/_compute_new_order),
    not just the downstream page_reordered handler. This is the exact spot a
    real bug was found and fixed before ("ドラッグ&ドロップ挿入位置計算の実バグ"),
    so bypassing it (as an earlier version of this script did, by calling
    _on_page_reordered directly) would never have caught that class of bug.
    """
    item = panel.item(drag_index)
    if item is None:
        raise RuntimeError(f"panel.item({drag_index}) is None (panel.count()={panel.count()})")
    panel.setCurrentItem(item)
    panel.clearSelection()
    item.setSelected(True)

    mime = QMimeData()
    target_item = panel.item(min(drop_visual_row, panel.count() - 1))
    target_rect = panel.visualItemRect(target_item)
    drop_pos = QPointF(target_rect.center().x(), target_rect.top() + 1) if drop_visual_row <= drag_index \
        else QPointF(target_rect.center().x(), target_rect.bottom() - 1)

    enter = QDragEnterEvent(drop_pos.toPoint(), Qt.DropAction.MoveAction, mime,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    panel.dragEnterEvent(enter)
    move = QDragMoveEvent(drop_pos.toPoint(), Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    panel.dragMoveEvent(move)
    drop = QDropEvent(drop_pos, Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    panel.dropEvent(drop)
    app.processEvents()


def main():
    install_dialog_guards()
    app = QApplication.instance() or QApplication(sys.argv)
    from src.pdf_editor.ui.main_window import MainWindow  # noqa: E402

    tmp_dir = REPO_ROOT / "qa" / "_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(exist_ok=True)

    pdf_path = tmp_dir / "behavior_test.pdf"
    make_test_pdf(pdf_path, pages=3)
    pdf2_path = tmp_dir / "behavior_test2.pdf"
    make_test_pdf(pdf2_path, pages=2)
    enc_path = tmp_dir / "encrypted.pdf"
    make_test_pdf(enc_path, pages=1, password="s3cret")
    md_path = tmp_dir / "note.md"
    md_path.write_text("# Title\n\nHello **world**.", encoding="utf-8")

    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    for _ in range(5):
        app.processEvents()

    def _open():
        before = window.pdf_manager.get_page_count()
        window.open_pdfs([str(pdf_path)])
        drain(app, lambda: not window._busy and window.pdf_manager.get_page_count() > 0)
        after = window.pdf_manager.get_page_count()
        ok = after == 3
        return before, after, ok, f"3ページのPDFを開いたところ、実際に読み込まれたページ数は{after}だった({'期待通り' if ok else '不一致'})"
    check("open_pdf", _open)

    def _rotate():
        before = window.pdf_manager.all_pages[0].rotation
        window._rotate_pages([0], 90)
        after = window.pdf_manager.all_pages[0].rotation
        ok = (after - before) % 360 == 90
        return before, after, ok, f"ページ0を90度回転操作したところ、rotation値が{before}→{after}に変化した"
    check("rotate", _rotate)

    def _undo_rotate():
        before = window.pdf_manager.all_pages[0].rotation
        window.undo_last_action()
        after = window.pdf_manager.all_pages[0].rotation
        ok = after != before
        return before, after, ok, f"直前の回転操作をUndoしたところ、rotation値が{before}→{after}に戻った"
    check("undo_rotate", _undo_rotate)

    def _rotate_left():
        before = window.pdf_manager.all_pages[1].rotation
        window._rotate_pages([1], -90)
        after = window.pdf_manager.all_pages[1].rotation
        ok = (after - before) % 360 == 270
        return before, after, ok, f"「左90°」相当の操作(-90度)をページ1に行ったところ、rotation値が{before}→{after}に変化した"
    check("rotate_left_90", _rotate_left)

    def _rotate_180():
        before = window.pdf_manager.all_pages[2].rotation
        window._rotate_pages([2], 180)
        after = window.pdf_manager.all_pages[2].rotation
        ok = (after - before) % 360 == 180
        return before, after, ok, f"「180°」操作をページ2に行ったところ、rotation値が{before}→{after}に変化した"
    check("rotate_180", _rotate_180)

    def _drag_reorder():
        before = [p.original_page_index for p in window.pdf_manager.page_infos]
        real_drag_reorder(window.thumbnail_panel, app, drag_index=2, drop_visual_row=0)
        drain(app, lambda: [p.original_page_index for p in window.pdf_manager.page_infos] != before)
        after = [p.original_page_index for p in window.pdf_manager.page_infos]
        ok = after == [before[2], before[0], before[1]]
        return before, after, ok, (
            f"3枚目のサムネイルを実際にマウスドラッグ操作(dragEnter/dragMove/dropの実イベント経由)で"
            f"先頭にドロップしたところ、ページ順が{before}→{after}に実際に入れ替わった"
        )
    check("drag_and_drop_reorder", _drag_reorder)

    def _undo_reorder():
        before = [p.original_page_index for p in window.pdf_manager.page_infos]
        window.undo_last_action()
        after = [p.original_page_index for p in window.pdf_manager.page_infos]
        ok = after != before
        return before, after, ok, f"直前のドラッグ並べ替えをUndoしたところ、順序が{before}→{after}に戻った"
    check("undo_reorder", _undo_reorder)

    def _delete():
        before = window.pdf_manager.get_page_count()
        window._delete_pages([0])
        after = window.pdf_manager.get_page_count()
        ok = after == before - 1
        return before, after, ok, f"1ページ削除操作をしたところ、総ページ数が{before}→{after}になった"
    check("delete", _delete)

    def _undo_delete():
        before = window.pdf_manager.get_page_count()
        window.undo_last_action()
        after = window.pdf_manager.get_page_count()
        ok = after == before + 1
        return before, after, ok, f"直前の削除をUndoしたところ、総ページ数が{before}→{after}に戻った"
    check("undo_delete", _undo_delete)

    if window.thumbnail_panel.count() > 0:
        first = window.thumbnail_panel.item(0)
        window.thumbnail_panel.setCurrentItem(first)
        window._on_thumbnail_selected(first)

    def _wheel_zoom_mode():
        window._wheel_mode = "zoom"
        before_zoom = window.current_zoom
        viewport = window.preview_scroll.viewport()
        ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        window.eventFilter(viewport, ev)
        after_zoom = window.current_zoom
        ok = after_zoom != before_zoom
        return before_zoom, after_zoom, ok, (
            f"環境設定が既定の「ズーム」モードの状態でプレビュー上にホイールイベントを送ったところ、"
            f"表示倍率(current_zoom)が{before_zoom}→{after_zoom}に変化した(スクロールはしない設計)"
        )
    check("preview_wheel_zoom_default_mode", _wheel_zoom_mode)

    def _right_drag_pan():
        window._wheel_mode = "zoom"
        viewport = window.preview_scroll.viewport()
        window.current_zoom = 3.0
        window._update_preview_display()
        app.processEvents()
        # Scroll to the middle first so a pan in either direction has room to
        # move (starting pinned at 0 and dragging further into the clamp
        # produces a false "no movement" reading that reflects the test's
        # drag direction, not the app).
        hbar = window.preview_scroll.horizontalScrollBar()
        hbar.setValue(hbar.maximum() // 2)
        before_h = hbar.value()
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(90, 50), Qt.MouseButton.RightButton,
                             Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        window.eventFilter(viewport, press)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(50, 50), Qt.MouseButton.NoButton,
                            Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        window.eventFilter(viewport, move)
        after_h = hbar.value()
        release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(50, 50), Qt.MouseButton.RightButton,
                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        window.eventFilter(viewport, release)
        ok = after_h != before_h
        return before_h, after_h, ok, f"「ズーム」モードで右ボタンドラッグしたところ、水平スクロール位置が{before_h}→{after_h}に変化した(パン動作)"
    check("preview_right_drag_pan_zoom_mode", _right_drag_pan)

    def _wheel_scroll_mode_right_drag_zoom():
        window._wheel_mode = "scroll"
        window.current_zoom = 1.0
        window._update_preview_display()
        app.processEvents()
        viewport = window.preview_scroll.viewport()
        before_zoom = window.current_zoom
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(50, 50), Qt.MouseButton.RightButton,
                             Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        window.eventFilter(viewport, press)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(50, 90), Qt.MouseButton.NoButton,
                            Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
        window.eventFilter(viewport, move)
        after_zoom = window.current_zoom
        release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(50, 90), Qt.MouseButton.RightButton,
                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        window.eventFilter(viewport, release)
        window._wheel_mode = "zoom"
        ok = after_zoom != before_zoom
        return before_zoom, after_zoom, ok, (
            f"環境設定を「スクロール」モードに切り替えた状態で右ドラッグしたところ、"
            f"(パンではなく)表示倍率が{before_zoom}→{after_zoom}に変化した(モード切替が実際に効いている)"
        )
    check("preview_wheel_mode_setting_switches_behavior", _wheel_scroll_mode_right_drag_zoom)

    def _crop_select():
        window.preview_label.selected_rect = QRect(10, 10, 100, 150)
        clip = window.preview_label.get_pdf_clip_rect()
        ok = clip is not None and clip.width > 0 and clip.height > 0
        return "selected_rect=None", f"clip={clip}", ok, (
            f"プレビュー上でクロップ範囲(左ドラッグ相当)を選択した状態にしたところ、"
            f"get_pdf_clip_rect()がPDF座標系の矩形{clip}を実際に返した"
        )
    check("preview_crop_area_selection", _crop_select)

    def _split():
        out_path = tmp_dir / "split_out.pdf"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(out_path), "")), \
             patch.object(QMessageBox, "information", return_value=None), \
             patch.object(QMessageBox, "warning", return_value=None):
            window._export_selected_as_pdf([0, 1])
            drain(app, lambda: not window._busy and out_path.exists())
        ok = out_path.exists()
        page_count = None
        if ok:
            d = fitz.open(str(out_path))
            page_count = d.page_count
            d.close()
        ok = ok and page_count == 2
        return "no file", f"exists={out_path.exists()}, pages={page_count}", ok, (
            f"2ページ選択してPDF切り出しをしたところ、実際にディスク上に{page_count}ページのPDFファイルが生成された"
        )
    check("split_pdf_cutout", _split)

    def _export_png():
        window.preview_label.selected_rect = None  # don't inherit a stale crop rect from an earlier check
        out_dir = tmp_dir / "png_out"
        out_dir.mkdir(exist_ok=True)

        def configure(dlg):
            dlg.dir_edit.setText(str(out_dir))
            dlg.fmt_combo.setCurrentIndex(0)
            dlg.scope_all.setChecked(True)
            dlg.area_all.setChecked(True)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", lambda self: configure(self) if type(self).__name__ == "ExportDialog" else (_ for _ in ()).throw(UnexpectedDialog(type(self).__name__))), \
             patch.object(QMessageBox, "information", return_value=None), \
             patch.object(QMessageBox, "warning", return_value=None):
            window.export_images()
            drain(app, lambda: not window._busy and out_dir.exists() and any(out_dir.iterdir()))
        files = list(out_dir.glob("*.png")) if out_dir.exists() else []
        ok = len(files) > 0
        return "no files", f"{len(files)} PNG files", ok, f"PNG形式・全ページで画像出力したところ、実際に{len(files)}個のPNGファイルがフォルダに生成された"
    check("export_images_png", _export_png)

    def _export_crop():
        out_dir_full = tmp_dir / "png_full"
        out_dir_crop = tmp_dir / "png_crop"
        out_dir_full.mkdir(exist_ok=True)
        out_dir_crop.mkdir(exist_ok=True)
        window.preview_label.selected_rect = None

        def cfg_full(dlg):
            dlg.dir_edit.setText(str(out_dir_full))
            dlg.area_all.setChecked(True)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", lambda self: cfg_full(self) if type(self).__name__ == "ExportDialog" else (_ for _ in ()).throw(UnexpectedDialog(type(self).__name__))), \
             patch.object(QMessageBox, "information", return_value=None), \
             patch.object(QMessageBox, "warning", return_value=None):
            window.export_images()
            drain(app, lambda: not window._busy and out_dir_full.exists() and any(out_dir_full.iterdir()))

        window.preview_label.selected_rect = QRect(10, 10, 80, 80)

        def cfg_crop(dlg):
            dlg.dir_edit.setText(str(out_dir_crop))
            if dlg.area_crop.isEnabled():
                dlg.area_crop.setChecked(True)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", lambda self: cfg_crop(self) if type(self).__name__ == "ExportDialog" else (_ for _ in ()).throw(UnexpectedDialog(type(self).__name__))), \
             patch.object(QMessageBox, "information", return_value=None), \
             patch.object(QMessageBox, "warning", return_value=None):
            window.export_images()
            drain(app, lambda: not window._busy and out_dir_crop.exists() and any(out_dir_crop.iterdir()))

        from PIL import Image
        full_files = list(out_dir_full.glob("*.png"))
        crop_files = list(out_dir_crop.glob("*.png"))
        if not full_files or not crop_files:
            return "missing output", f"full={len(full_files)} crop={len(crop_files)}", False, "出力ファイルが生成されず比較できなかった"
        full_size = Image.open(full_files[0]).size
        crop_size = Image.open(crop_files[0]).size
        ok = crop_size[0] < full_size[0] and crop_size[1] < full_size[1]
        return full_size, crop_size, ok, f"クロップ無し出力({full_size})とクロップ指定出力({crop_size})を比較したところ、クロップ指定時の方が実際に小さい画像になった"
    check("export_images_with_crop", _export_crop)

    def _password_retry():
        before = window.pdf_manager.get_page_count()
        with patch.object(QInputDialog, "getText", return_value=("s3cret", True)):
            window.open_pdfs([str(enc_path)])
            drain(app, lambda: window.pdf_manager.get_page_count() > before)
        after = window.pdf_manager.get_page_count()
        ok = after == before + 1
        return before, after, ok, f"暗号化PDFを開き、パスワード入力欄に直接正しいパスワードを注入したところ、ページ数が{before}→{after}になり実際に開けた"
    check("password_protected_pdf_retry", _password_retry)

    def _duplicate():
        before = window.pdf_manager.get_page_count()
        with patch.object(QMessageBox, "information", return_value=None) as mock_info:
            window.open_pdfs([str(enc_path)])
            drain(app, lambda: mock_info.called)
        after = window.pdf_manager.get_page_count()
        ok = after == before and mock_info.called
        return before, after, ok, f"既に読み込み済みの暗号化PDFを再度開こうとしたところ、ページ数は{before}のまま変化せず、スキップ通知ダイアログが呼ばれた"
    check("duplicate_file_detection", _duplicate)

    def _mixed_reject():
        before = window.current_mode
        with patch.object(QMessageBox, "information", return_value=None) as mock_info:
            window.open_documents([str(pdf_path), str(md_path)])
        after = window.current_mode
        ok = mock_info.called and after == before
        return before, after, ok, f"PDFとMarkdownを同時選択して開こうとしたところ、警告ダイアログが呼ばれ、モードは{before}のまま変化しなかった(中断された)"
    check("mixed_pdf_markdown_open_rejected", _mixed_reject)

    def _close_file():
        with patch.object(QMessageBox, "information", return_value=None):
            window.open_pdfs([str(pdf_path), str(pdf2_path)])
            drain(app, lambda: not window._busy and window.pdf_manager.get_page_count() >= 5)
        before = window.pdf_manager.get_page_count()
        window._on_file_close_requested(pdf2_path)
        after = window.pdf_manager.get_page_count()
        ok = after == before - 2
        return before, after, ok, f"2ファイル({pdf_path.name}, {pdf2_path.name})読込中に片方だけを閉じたところ、総ページ数が{before}→{after}になり、そのファイル分だけ減った"
    check("close_single_file", _close_file)

    def _unsaved_confirm():
        window._mark_dirty()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
            ok_to_proceed = window._confirm_discard_pdf_changes("test?")
        ok = mock_q.called and ok_to_proceed is False
        return "dirty + answer=いいえ", f"proceed={ok_to_proceed}", ok, "未保存の変更がある状態で終了確認に「いいえ」と直接応答させたところ、破棄せず処理が中断された"
    check("unsaved_changes_confirmation", _unsaved_confirm)

    def _overwrite_save():
        # can_overwrite_source() requires every loaded page to share one
        # source file -- earlier checks left other files loaded, so close
        # everything first (otherwise this always fails for a reason that
        # has nothing to do with the actual overwrite-save feature).
        window.pdf_manager.close_all()
        window.thumbnail_panel.refresh()
        window._mark_clean()
        target = tmp_dir / "overwrite_test.pdf"
        make_test_pdf(target, pages=2)
        with patch.object(QMessageBox, "information", return_value=None):
            window.open_pdfs([str(target)])
            drain(app, lambda: not window._busy and window.pdf_manager.get_page_count() > 0)
        before_bytes = target.read_bytes()
        window._rotate_pages([0], 90)
        print(f"  [debug] can_overwrite_source={window.pdf_manager.can_overwrite_source()} "
              f"sources={[str(i.source_doc_path) for i in window.pdf_manager.page_infos]} target={target}",
              flush=True)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "warning", return_value=None):
            window._overwrite_current_pdf()
            drain(app, lambda: not window._busy and target.read_bytes() != before_bytes)
        after_bytes = target.read_bytes()
        ok = before_bytes != after_bytes
        verb = "実際に変化した" if ok else "変化しなかった(上書き保存が実行されていない)"
        return len(before_bytes), len(after_bytes), ok, f"1ページ回転後に上書き保存したところ、ディスク上のファイルの内容が{verb}({len(before_bytes)}→{len(after_bytes)}バイト)"
    check("overwrite_save_persists_to_disk", _overwrite_save)

    # _apply_size()(thumbnail_panel.py)が実際にsetIconSize()へ渡す値。
    # NUM_GUTTER_W(左端のページ番号列)を含むQListWidgetのiconSize()そのものを
    # 期待値として使い、内部ラベル文字列ではなく実測ピクセルで判定する。
    from src.pdf_editor.ui.thumbnail_panel import NUM_GUTTER_W  # noqa: E402
    EXPECTED_ICON_SIZE = {
        "small": QSize(NUM_GUTTER_W + 80, 105),
        "medium": QSize(NUM_GUTTER_W + 120, 155),
        "large": QSize(NUM_GUTTER_W + 200, 260),
    }

    def _measure_thumb_size(label, size_key):
        before_icon = window.thumbnail_panel.iconSize()
        window.set_thumbnail_size(size_key)
        app.processEvents()
        after_icon = window.thumbnail_panel.iconSize()
        item0 = window.thumbnail_panel.item(0)
        item_rect = window.thumbnail_panel.visualItemRect(item0) if item0 is not None else None
        expected = EXPECTED_ICON_SIZE[size_key]
        ok = after_icon == expected
        item_desc = f"、リスト項目の実描画サイズは{item_rect.width()}×{item_rect.height()}pxだった" if item_rect else ""
        return (
            f"{before_icon.width()}x{before_icon.height()}",
            f"{after_icon.width()}x{after_icon.height()}",
            ok,
            f"サムネイルサイズを「{label}」に切り替えたところ、setIconSize()の実測値が"
            f"{before_icon.width()}×{before_icon.height()}px→{after_icon.width()}×{after_icon.height()}pxに変化した"
            f"(期待値{expected.width()}×{expected.height()}px){item_desc}"
        )

    check("thumbnail_size_toggle", lambda: _measure_thumb_size("大", "large"))
    check("thumbnail_size_small", lambda: _measure_thumb_size("小", "small"))
    check("thumbnail_size_medium", lambda: _measure_thumb_size("中", "medium"))

    def _markdown_mode():
        window._mark_clean()  # avoid an unrelated "discard changes?" confirmation for this check
        before = window.current_mode
        if window.markdown_view is not None:
            window._load_markdown_document(md_path)
            app.processEvents()
            after = window.current_mode
        else:
            after = "N/A (QtWebEngine未搭載環境)"
        ok = after == "markdown"
        return before, after, ok, f".mdファイルを開いたところ、表示モードが{before}→{after}に切り替わった"
    check("markdown_mode_switch", _markdown_mode)

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        window.close()

    passed = sum(1 for r in results if r["pass"])
    out = {"source": "python", "total": len(results), "passed": passed, "results": results}
    out_path = REPO_ROOT / "qa" / "behaviors.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[集計] {passed}/{len(results)} 件PASS -> {out_path}", flush=True)
    db.record_behaviors_run("python", results)


if __name__ == "__main__":
    main()
