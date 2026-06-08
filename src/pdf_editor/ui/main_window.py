"""
Main Window for PDF Editor
Layout (per spec):
- Top: Icon-based menu (QToolBar)
- Left: Vertical thumbnail list (ThumbnailPanel)
- Right: Page preview
"""
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea,
    QToolBar, QStatusBar, QFileDialog, QMessageBox, QInputDialog, QSplitter,
    QDialog, QGroupBox, QCheckBox, QLineEdit, QRadioButton, QButtonGroup, QPushButton,
    QComboBox, QSlider, QSpinBox, QProgressDialog
)
from PySide6.QtCore import Qt, QSize, QEvent, QThread
from PySide6.QtGui import QAction, QPixmap, QImage, QIcon

from src.pdf_editor.ui.thumbnail_panel import ThumbnailPanel
from src.pdf_editor.pdf.pdf_manager import PDFManager
from src.pdf_editor.utils.resources import get_icon
from src.pdf_editor.ui.dialogs import HeaderFooterDialog, ExportDialog
from src.pdf_editor.ui.workers import Worker  # for type annotation in __init__

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Editor")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)  # Allow reasonable resizing

        self.pdf_manager = PDFManager()
        self._is_dirty = False
        self._save_thread: QThread | None = None
        self._save_worker: Worker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        outer_layout = QHBoxLayout(central)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(4)
        outer_layout.addWidget(self.splitter)

        # Left: Thumbnails
        self.thumbnail_panel = ThumbnailPanel()
        self.thumbnail_panel.set_pdf_manager(self.pdf_manager)
        self.thumbnail_panel.page_reordered.connect(self._on_page_reordered)
        self.thumbnail_panel.pdf_extract_requested.connect(self._on_pdf_extract_requested)
        self.thumbnail_panel.image_extract_requested.connect(self._on_image_extract_requested)
        self.thumbnail_panel.file_close_requested.connect(self._on_file_close_requested)
        self.splitter.addWidget(self.thumbnail_panel)

        # Right: Preview (with scroll + zoom support)
        self.preview_label = QLabel("PDFページをここに表示します")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #1e1e1e; color: #aaaaaa; font-size: 20px; border: 1px solid #333;"
        )

        # Save a reference "default" preview image the first time we are in the cleared state
        # (useful for the preview_judge.py image analysis tool)
        self._default_reference_saved = False

        # Try to save reference default early if we start with no files
        QTimer.singleShot(800, self._maybe_save_default_reference)

    def _maybe_save_default_reference(self):
        if not self._default_reference_saved and self.pdf_manager.get_page_count() == 0:
            try:
                ref_path = "reference_default_preview.png"
                if not os.path.exists(ref_path):
                    pix = self.preview_label.grab()
                    pix.save(ref_path)
                    print(f"[Debug] Saved reference default preview: {ref_path}")
                self._default_reference_saved = True
            except Exception as e:
                print(f"[Debug] Could not save reference default: {e}")

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidget(self.preview_label)
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.current_preview_pixmap = None
        self.current_zoom = 1.0

        # Persist header/footer dialog settings across opens (session-level memory)
        self._hf_settings: dict = {}

        # For right-click drag panning
        self._panning = False
        self._pan_start_pos = None
        self._h_scroll_start = 0
        self._v_scroll_start = 0

        # Install event filter to control wheel behavior (zoom only, no scroll)
        viewport = self.preview_scroll.viewport()
        viewport.installEventFilter(self)

        self.splitter.addWidget(self.preview_scroll)

        # Thumbnail panel: fixed size on window resize; preview takes all extra space
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([self.thumbnail_panel._panel_width, 1000])

        # Top toolbar
        self._create_toolbar()

        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("準備完了 - PDFファイルを開いてください")

        # Connect selection (now using QTreeWidget)
        self.thumbnail_panel.currentItemChanged.connect(self._on_thumbnail_selected)

    def _create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(28, 28))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # Open
        open_action = QAction(get_icon("open"), "開く", self)
        open_action.setToolTip("PDFファイルを開く")
        open_action.triggered.connect(self.open_pdfs)
        toolbar.addAction(open_action)

        toolbar.addSeparator()

        # Merge
        merge_action = QAction(get_icon("merge"), "連結", self)
        merge_action.setToolTip("現在の状態を1つのPDFとして保存（連結）")
        merge_action.triggered.connect(self.merge_documents)
        toolbar.addAction(merge_action)

        # Split / PDF cut-out
        split_action = QAction(get_icon("split"), "PDF切り出し", self)
        split_action.setToolTip("選択ページを新しいPDFとして保存（切り出し）")
        split_action.triggered.connect(self.split_document)
        toolbar.addAction(split_action)

        # Image export (text button for now; primary access is also via thumbnail right-click)
        img_export_action = QAction("画像出力", self)
        img_export_action.setToolTip("ページをPNG/JPG画像としてエクスポート（右クリックメニューからも可）")
        img_export_action.triggered.connect(self.export_images)
        toolbar.addAction(img_export_action)

        toolbar.addSeparator()

        # Rotation
        rotate_right = QAction(get_icon("rotate_right"), "右90°", self)
        rotate_right.setToolTip("選択ページを右に90度回転")
        rotate_right.triggered.connect(lambda: self.rotate_current_page(90))
        toolbar.addAction(rotate_right)

        rotate_left = QAction(get_icon("rotate_left"), "左90°", self)
        rotate_left.setToolTip("選択ページを左に90度回転")
        rotate_left.triggered.connect(lambda: self.rotate_current_page(-90))
        toolbar.addAction(rotate_left)

        rotate_180 = QAction(get_icon("rotate_180"), "180°", self)
        rotate_180.setToolTip("選択ページを180度回転")
        rotate_180.triggered.connect(lambda: self.rotate_current_page(180))
        toolbar.addAction(rotate_180)

        toolbar.addSeparator()

        # Header/Footer
        header_action = QAction(get_icon("header_footer"), "ヘッダー/フッター", self)
        header_action.setToolTip("ページ番号やタイトルを追加")
        header_action.triggered.connect(self.edit_header_footer)
        toolbar.addAction(header_action)

        toolbar.addSeparator()

        # Save
        save_action = QAction(get_icon("save"), "保存", self)
        save_action.setToolTip("編集後のPDFを保存")
        save_action.triggered.connect(self.save_pdf)
        toolbar.addAction(save_action)

        toolbar.addSeparator()

        # Thumbnail size
        size_label = QAction("サムネ", self)
        size_label.setEnabled(False)
        toolbar.addAction(size_label)

        small_action = QAction("小", self)
        small_action.setToolTip("サムネイルを小さく")
        small_action.triggered.connect(lambda: self.set_thumbnail_size("small"))
        toolbar.addAction(small_action)

        medium_action = QAction("中", self)
        medium_action.setToolTip("標準サイズ")
        medium_action.triggered.connect(lambda: self.set_thumbnail_size("medium"))
        toolbar.addAction(medium_action)

        large_action = QAction("大", self)
        large_action.setToolTip("サムネイルを大きく")
        large_action.triggered.connect(lambda: self.set_thumbnail_size("large"))
        toolbar.addAction(large_action)

    def open_pdfs(self):
        """Open one or more PDF files."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "PDFファイルを選択",
            "",
            "PDF Files (*.pdf);;All Files (*)"
        )
        if not files:
            return

        paths = [Path(f) for f in files]
        loaded = self.pdf_manager.load_pdfs(paths)

        if loaded > 0:
            self._is_dirty = True
            self.thumbnail_panel.refresh()

            # Auto-select the first page so preview + thumbnails show immediately
            if self.thumbnail_panel.topLevelItemCount() > 0:
                first_file = self.thumbnail_panel.topLevelItem(0)
                if first_file.childCount() > 0:
                    first_page = first_file.child(0)
                    self.thumbnail_panel.setCurrentItem(first_page)
                    # Force preview update in case the signal doesn't fire
                    self._on_thumbnail_selected(first_page)

            self.statusBar().showMessage(f"{loaded} ファイル読み込み完了（全{self.pdf_manager.get_page_count()}ページ）")
        else:
            QMessageBox.warning(self, "エラー", "PDFの読み込みに失敗しました")

    def _on_thumbnail_selected(self, current_item, previous_item=None):
        """Called when a thumbnail (page) is selected in the tree."""
        if current_item is None or not self.pdf_manager:
            return

        # Only react to page items (children), not file headers (top-level)
        if current_item.parent() is None:
            return

        row = current_item.data(0, Qt.UserRole)
        if row is None or row < 0:
            return

        pix = self.pdf_manager.get_preview_pixmap(row, zoom=1.5)
        if pix is None:
            return

        img_data = pix.tobytes("png")
        qimage = QImage.fromData(img_data, "PNG")
        self.current_preview_pixmap = QPixmap.fromImage(qimage)

        # Default to fit document width to the preview area
        self._fit_to_width()

    def _update_preview_display(self):
        """Apply current zoom to the preview label."""
        if self.current_preview_pixmap is None:
            return

        scaled = self.current_preview_pixmap.scaled(
            self.current_preview_pixmap.size() * self.current_zoom,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.setAlignment(Qt.AlignCenter)

    def _fit_to_width(self):
        """Set zoom so the page width fits the available preview width."""
        if self.current_preview_pixmap is None:
            return

        viewport_width = self.preview_scroll.viewport().width() - 30  # margin for scrollbar
        pixmap_width = self.current_preview_pixmap.width()

        if pixmap_width > 0 and viewport_width > 0:
            self.current_zoom = viewport_width / pixmap_width
            self.current_zoom = max(0.05, min(self.current_zoom, 8.0))
            self._update_preview_display()
        else:
            self.current_zoom = 1.0
            self._update_preview_display()

    # Note: Wheel and right-drag panning for preview are now handled via eventFilter on the viewport
    # for more reliable interception.

    def eventFilter(self, obj, event):
        # Control wheel on preview viewport: only zoom, never scroll
        if obj is self.preview_scroll.viewport():
            if event.type() == QEvent.Type.Wheel:
                if self.current_preview_pixmap is not None:
                    delta = event.angleDelta().y()
                    factor = 1.15 if delta > 0 else 1 / 1.15
                    self.current_zoom *= factor
                    self.current_zoom = max(0.1, min(self.current_zoom, 8.0))
                    self._update_preview_display()
                    event.accept()
                    return True  # Block default scrolling
            # Right button drag panning
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.RightButton:
                self._panning = True
                self._pan_start_pos = event.position().toPoint()
                self._h_scroll_start = self.preview_scroll.horizontalScrollBar().value()
                self._v_scroll_start = self.preview_scroll.verticalScrollBar().value()
                self.preview_scroll.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return True
            if event.type() == QEvent.Type.MouseMove and self._panning:
                if self._pan_start_pos:
                    delta = event.position().toPoint() - self._pan_start_pos
                    h_bar = self.preview_scroll.horizontalScrollBar()
                    v_bar = self.preview_scroll.verticalScrollBar()
                    h_bar.setValue(self._h_scroll_start - delta.x())
                    v_bar.setValue(self._v_scroll_start - delta.y())
                    event.accept()
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.RightButton:
                if self._panning:
                    self._panning = False
                    self._pan_start_pos = None
                    self.preview_scroll.setCursor(Qt.ArrowCursor)
                    event.accept()
                    return True
        return super().eventFilter(obj, event)

    def _on_page_reordered(self, new_order: list[int]):
        """User dragged thumbnails → reorder in manager."""
        moved_page_idx = getattr(self.thumbnail_panel, '_dragged_page_idx', -1)

        self.pdf_manager.reorder_pages(new_order)
        self.thumbnail_panel.refresh()

        # Try to restore selection to the page we were dragging.
        # Only call setCurrentItem when the parent file is expanded — calling it on a
        # collapsed parent causes Qt to auto-expand that file (and any other files it
        # needs to scroll past), which undoes the user's collapsed state.
        restored = False
        if moved_page_idx >= 0:
            for i in range(self.thumbnail_panel.topLevelItemCount()):
                file_item = self.thumbnail_panel.topLevelItem(i)
                for j in range(file_item.childCount()):
                    child = file_item.child(j)
                    if child.data(0, Qt.UserRole) == moved_page_idx:
                        if file_item.isExpanded():
                            self.thumbnail_panel.setCurrentItem(child)
                            restored = True
                        break
                if restored:
                    break

        # Only use the "first page" fallback if we had no dragged page recorded
        if not restored and self.thumbnail_panel.count() > 0:
            self.thumbnail_panel.setCurrentRow(0)

        # Clear the marker
        if hasattr(self.thumbnail_panel, '_dragged_page_idx'):
            self.thumbnail_panel._dragged_page_idx = -1

        self._is_dirty = True
        self.statusBar().showMessage("ページ順を更新しました")

    # === Stub actions (to be implemented) ===
    def merge_documents(self):
        """連結 = 現在のページ状態（並び替え・回転・ヘッダー適用済み）を1つのPDFとして保存"""
        if self.pdf_manager.get_page_count() == 0:
            QMessageBox.information(self, "情報", "PDFを先に開いてください")
            return
        self.statusBar().showMessage("連結（マージ）: 現在の状態を1つのPDFとして保存します")
        self.save_pdf()

    def split_document(self):
        """Toolbar: PDF cut-out using current selection (delegates to smart default path)."""
        selected = self._get_selected_page_indices_in_order()
        if not selected:
            QMessageBox.information(self, "情報", "PDFを切り出したいページをサムネイルで選択してください")
            return
        self._export_selected_as_pdf(selected)

    def _export_selected_as_pdf(self, indices: list[int]):
        """PDF export (切り出し) with default location = original file's folder."""
        if not indices:
            return
        default_dir = self.pdf_manager.get_source_dir_for_pages(indices)
        base = self.pdf_manager.suggest_export_basename(indices, for_images=False)
        default_file = str(default_dir / f"{base}.pdf")

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "PDFを切り出して保存",
            default_file,
            "PDF Files (*.pdf)"
        )
        if not output_path:
            return

        success = self.pdf_manager.save_selected_pages(indices, Path(output_path))
        if success:
            self._is_dirty = False
            self.statusBar().showMessage(f"PDFを切り出しました: {output_path}")
            QMessageBox.information(self, "完了", f"{len(indices)}ページを新しいPDFとして保存しました。\n{output_path}")
        else:
            QMessageBox.warning(self, "エラー", "PDFの切り出し保存に失敗しました")

    def _on_pdf_extract_requested(self, indices: list[int]):
        """Context menu (thumbnail right-click) → PDFを切り出し"""
        if not indices:
            indices = self.thumbnail_panel.get_selected_page_indices()
        if not indices:
            cur = self.thumbnail_panel.currentRow()
            if cur >= 0:
                indices = [cur]
        if not indices:
            QMessageBox.information(self, "情報", "PDFを切り出したいページを選択してください")
            return
        self._export_selected_as_pdf(indices)

    def export_images(self):
        """Toolbar action: open image export dialog (respects current selection for default scope/dir)."""
        if self.pdf_manager.get_page_count() == 0:
            QMessageBox.information(self, "情報", "PDFを先に開いてください")
            return
        selected = self._get_selected_page_indices_in_order()
        total = self.pdf_manager.get_page_count()
        sel_count = len(selected)
        default_dir = str(
            self.pdf_manager.get_source_dir_for_pages(selected)
            if selected else self.pdf_manager.get_source_dir_for_pages(list(range(total)))
        )
        suggested_prefix = self.pdf_manager.suggest_export_basename(
            selected or list(range(min(3, total))), for_images=True
        )
        dialog = ExportDialog(
            self,
            total_pages=total,
            selected_pages=sel_count,
            initial_dir=default_dir,
            suggested_prefix=suggested_prefix,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        cfg = dialog.get_settings()
        use_indices = selected if (cfg["scope"] == "selected" and selected) else list(range(total))
        out_dir = cfg["output_dir"]

        # Run the heavy export in background
        progress = QProgressDialog("画像をエクスポートしています...", None, 0, 0, self)
        progress.setWindowTitle("エクスポート中")
        progress.setModal(True)
        progress.show()

        def _do_export():
            return self.pdf_manager.export_pages_to_images(
                indices=use_indices,
                output_dir=Path(cfg["output_dir"]),
                fmt=cfg["format"],
                dpi=cfg["dpi"],
                jpeg_quality=cfg.get("jpeg_quality", 90),
                prefix=cfg["prefix"],
            )

        worker = Worker(_do_export)

        def _on_finished(result):
            progress.close()
            success, attempted, errs = result or (0, 0, [])
            if success > 0:
                msg = f"{success}/{attempted} ページを画像として保存しました。\n保存先: {out_dir}"
                if errs:
                    msg += f"\n（{len(errs)}件のエラーあり。詳細はコンソール）"
                self.statusBar().showMessage(f"画像エクスポート完了: {out_dir}")
                QMessageBox.information(self, "完了", msg)
            else:
                QMessageBox.warning(self, "エラー", "画像エクスポートに失敗しました")

        def _on_error(msg):
            progress.close()
            logger.error(f"Image export failed: {msg}")
            QMessageBox.warning(self, "エラー", f"画像エクスポートに失敗しました\n{msg}")

        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)

        # Start on a new thread
        thread = QThread(self)
        worker.run_in_thread(thread)

    def _on_image_extract_requested(self, indices: list[int]):
        """Context menu (thumbnail right-click) → 画像を切り出し (PNG/JPG)"""
        if not indices:
            indices = self.thumbnail_panel.get_selected_page_indices()
        if not indices:
            cur = self.thumbnail_panel.currentRow()
            if cur >= 0:
                indices = [cur]
        total = self.pdf_manager.get_page_count()
        sel_count = len(indices)
        if total == 0 or sel_count == 0 and total > 0:
            # fallback to dialog with all if no specific selection
            sel_count = 0
        default_dir = str(
            self.pdf_manager.get_source_dir_for_pages(indices) if indices else Path.cwd()
        )
        suggested_prefix = self.pdf_manager.suggest_export_basename(indices or [], for_images=True)
        dialog = ExportDialog(
            self,
            total_pages=total,
            selected_pages=sel_count,
            initial_dir=default_dir,
            suggested_prefix=suggested_prefix,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        cfg = dialog.get_settings()
        use_indices = indices if (cfg["scope"] == "selected" and indices) else list(range(total))
        out_dir = cfg["output_dir"]

        progress = QProgressDialog("画像をエクスポートしています...", None, 0, 0, self)
        progress.setWindowTitle("エクスポート中")
        progress.setModal(True)
        progress.show()

        def _do_export():
            return self.pdf_manager.export_pages_to_images(
                indices=use_indices,
                output_dir=Path(cfg["output_dir"]),
                fmt=cfg["format"],
                dpi=cfg["dpi"],
                jpeg_quality=cfg.get("jpeg_quality", 90),
                prefix=cfg["prefix"],
            )

        worker = Worker(_do_export)

        def _on_finished(result):
            progress.close()
            success, attempted, errs = result or (0, 0, [])
            if success > 0:
                msg = f"{success}/{attempted} ページを画像として保存しました。\n保存先: {out_dir}"
                if errs:
                    msg += f"\n（{len(errs)}件のエラーあり）"
                self.statusBar().showMessage(f"画像エクスポート完了: {out_dir}")
                QMessageBox.information(self, "完了", msg)
            else:
                QMessageBox.warning(self, "エラー", "画像エクスポートに失敗しました")

        def _on_error(msg):
            progress.close()
            logger.error(f"Image export failed: {msg}")
            QMessageBox.warning(self, "エラー", f"画像エクスポートに失敗しました\n{msg}")

        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)

        thread = QThread(self)
        worker.run_in_thread(thread)

    def _on_file_close_requested(self, path: Path):
        """Close an entire PDF file that was opened (right-click on file header in tree)."""
        if self.pdf_manager.close_document(path):
            # Block tree signals during refresh + selection to prevent any stale
            # currentItemChanged from re-setting an old preview pixmap.
            self.thumbnail_panel.blockSignals(True)
            try:
                self.thumbnail_panel.refresh()

                # Always clear the preview from the closed file first.
                # This ensures the right-side page view no longer shows content from the closed file.
                self.preview_label.clear()
                self.preview_label.setText("PDFページをここに表示します")
                self.current_preview_pixmap = None
                self.preview_label.repaint()  # Force immediate visual update
                self.preview_scroll.repaint()

                if self.pdf_manager.get_page_count() > 0:
                    # Directly load preview for the first remaining page from the manager.
                    # This bypasses tree selection entirely to guarantee the old closed page's image is replaced.
                    pix = self.pdf_manager.get_preview_pixmap(0, zoom=1.5)
                    if pix is not None:
                        img_data = pix.tobytes("png")
                        qimage = QImage.fromData(img_data, "PNG")
                        self.current_preview_pixmap = QPixmap.fromImage(qimage)
                        self._fit_to_width()
                    else:
                        # Fallback if pixmap generation fails for some reason
                        self.preview_label.clear()
                        self.preview_label.setText("PDFページをここに表示します")
                        self.current_preview_pixmap = None

                # Now set the tree selection (signals are blocked so it won't trigger preview update)
                if self.thumbnail_panel.topLevelItemCount() > 0:
                    first_file = self.thumbnail_panel.topLevelItem(0)
                    first_file.setExpanded(True)
                    if first_file.childCount() > 0:
                        first_page_item = first_file.child(0)
                        self.thumbnail_panel.setCurrentItem(first_page_item)

                # Automatic debug for image-based verification (test environment):
                # - Always save a clean grab of the preview_label right after the close action.
                # - Also save a small JSON with key state so the judge script can cross-check.
                # The preview_judge.py can then analyze the image + references and output
                # an objective verdict (DEFAULT_TEXT / SHOWING_NEW_PAGE / STILL_OLD_PAGE).
                try:
                    import datetime, json
                    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                    debug_base = f"debug_close_{path.stem}_{ts}"
                    preview_grab = self.preview_label.grab()
                    preview_grab.save(f"{debug_base}.png")
                    state = {
                        "closed_path": str(path),
                        "remaining_page_count": self.pdf_manager.get_page_count(),
                        "preview_cleared": self.current_preview_pixmap is None,
                        "preview_label_text": self.preview_label.text(),
                        "timestamp": ts,
                    }
                    with open(f"{debug_base}.json", "w", encoding="utf-8") as f:
                        json.dump(state, f, indent=2, ensure_ascii=False)
                    print(f"[Debug] Auto-saved preview image for judgment: {debug_base}.png")
                    print(f"[Debug] State: {state}")
                except Exception as e:
                    print(f"[Debug] Failed to save debug preview after close: {e}")
            finally:
                self.thumbnail_panel.blockSignals(False)

            self.statusBar().showMessage(f"{path.name} を閉じました")
        else:
            QMessageBox.warning(self, "エラー", f"{path.name} のクローズに失敗しました")

    def rotate_current_page(self, degrees: int):
        """Rotate the currently selected page by the given degrees. Keep selection."""
        current = self.thumbnail_panel.currentRow()
        if current >= 0:
            self.pdf_manager.rotate_page(current, degrees)

            # Remember selection and restore after refresh
            self.thumbnail_panel.refresh()
            self.thumbnail_panel.setCurrentRow(current)

            # Refresh preview (signal will also fire, but we force it for safety)
            current_item = self.thumbnail_panel.currentItem()
            if self.current_preview_pixmap is not None and current_item:
                self._on_thumbnail_selected(current_item)

            self._is_dirty = True
            self.statusBar().showMessage(f"ページを{degrees}度回転しました")
        else:
            QMessageBox.information(self, "情報", "回転したいページを選択してください")

    def edit_header_footer(self):
        """Open header/footer settings dialog (pre-filled with last-used values)."""
        if self.pdf_manager.get_page_count() == 0:
            QMessageBox.information(self, "情報", "PDFを先に開いてください")
            return

        dialog = HeaderFooterDialog(self, initial=self._hf_settings)
        result = dialog.exec()

        if result == HeaderFooterDialog._RESULT_DELETE:
            self.pdf_manager.remove_header_footer()
            self._refresh_after_hf()
            self._is_dirty = True
            self.statusBar().showMessage("ヘッダー/フッターを削除しました")
            return

        if result != QDialog.Accepted:
            return

        cfg = dialog.get_settings()
        self._hf_settings = cfg  # remember for next open

        self.pdf_manager.add_header_footer(
            header_enabled=cfg["header_enabled"],
            header_text=cfg["header_text"],
            header_align=cfg["header_align"],
            footer_page_num=cfg["footer_page_num"],
            footer_page_num_align=cfg["footer_page_num_align"],
            footer_text_enabled=cfg["footer_text_enabled"],
            footer_text=cfg["footer_text"],
            footer_text_align=cfg["footer_text_align"],
        )
        self._refresh_after_hf()
        self._is_dirty = True
        self.statusBar().showMessage("ヘッダー/フッターを適用しました")

    def _refresh_after_hf(self):
        self.thumbnail_panel.refresh()
        current_item = self.thumbnail_panel.currentItem()
        if current_item:
            self._on_thumbnail_selected(current_item)

    def save_pdf(self):
        """Export current state (after reorder/rotate/header) as a new PDF."""
        if self.pdf_manager.get_page_count() == 0:
            QMessageBox.information(self, "情報", "保存する内容がありません")
            return

        if self._save_thread is not None and self._save_thread.isRunning():
            QMessageBox.information(self, "情報", "保存処理が実行中です。完了までお待ちください。")
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "名前を付けて保存",
            "edited.pdf",
            "PDF Files (*.pdf)"
        )
        if not output_path:
            return

        progress = QProgressDialog("PDFを保存しています...", None, 0, 0, self)
        progress.setWindowTitle("保存中")
        progress.setModal(True)
        progress.show()

        def _do_save():
            return self.pdf_manager.save_as(Path(output_path))

        # Parent the worker to self to keep it alive
        worker = Worker(_do_save, self)

        def _on_finished(ok):
            self._save_worker = None
            self._save_thread = None
            progress.close()
            if ok:
                self._is_dirty = False
                self.statusBar().showMessage(f"保存しました: {output_path}")
                QMessageBox.information(self, "完了", f"PDFを保存しました。\n{output_path}")
            else:
                QMessageBox.warning(self, "エラー", "PDFの保存に失敗しました")

        def _on_error(msg):
            self._save_worker = None
            self._save_thread = None
            progress.close()
            logger.error(f"Save failed: {msg}")
            QMessageBox.warning(self, "エラー", f"PDFの保存に失敗しました\n{msg}")

        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)

        thread = QThread(self)
        self._save_worker = worker
        self._save_thread = thread
        worker.run_in_thread(thread)

    def set_thumbnail_size(self, size: str):
        """Change left thumbnail size and refresh."""
        current_page = self.thumbnail_panel.currentRow()

        self.thumbnail_panel.set_thumbnail_size(size)
        self.thumbnail_panel.refresh()

        # Resize the left pane to fit the new thumbnail width (transfer the difference to the right pane)
        sizes = self.splitter.sizes()
        new_w = self.thumbnail_panel._panel_width
        self.splitter.setSizes([new_w, max(200, sizes[0] + sizes[1] - new_w)])

        if current_page >= 0:
            self.thumbnail_panel.setCurrentRow(current_page)

        size_name = {"small": "小", "medium": "中", "large": "大"}.get(size, size)
        self.statusBar().showMessage(f"サムネイルサイズを「{size_name}」に変更しました")

    def _get_selected_page_indices_in_order(self):
        """Return list of page indices currently selected in the tree, in visual order (delegates to panel)."""
        return self.thumbnail_panel.get_selected_page_indices()

    def closeEvent(self, event):
        """Ask for confirmation if there are unsaved changes."""
        if self._is_dirty and self.pdf_manager.get_page_count() > 0:
            reply = QMessageBox.question(
                self,
                "確認",
                "変更が保存されていません。終了してよろしいですか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()
