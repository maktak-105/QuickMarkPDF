"""
Main Window for PDF Editor
Layout (per spec):
- Top: Icon-based menu (QToolBar)
- Left: Vertical thumbnail list (ThumbnailPanel)
- Right: Page preview
"""
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea,
    QToolBar, QStatusBar, QFileDialog, QMessageBox, QInputDialog, QSplitter,
    QDialog, QGroupBox, QCheckBox, QLineEdit, QRadioButton, QButtonGroup, QPushButton
)
from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QAction, QPixmap, QImage, QIcon
from pathlib import Path
import os

from src.pdf_editor.ui.thumbnail_panel import ThumbnailPanel
from src.pdf_editor.pdf.pdf_manager import PDFManager


class HeaderFooterDialog(QDialog):
    """Dialog for configuring and applying/removing header & footer.
    Pass `initial` (a dict from get_settings()) to pre-populate fields.
    """

    _RESULT_DELETE = 2

    def __init__(self, parent=None, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("ヘッダー/フッター設定")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        s = initial or {}

        # ── Header ──────────────────────────────────────────
        h_group = QGroupBox("ヘッダー")
        hl = QVBoxLayout(h_group)

        self.header_check = QCheckBox("ヘッダーを追加する")
        self.header_check.setChecked(s.get("header_enabled", False))
        hl.addWidget(self.header_check)

        h_text_row = QHBoxLayout()
        h_text_row.addWidget(QLabel("テキスト:"))
        self.header_text = QLineEdit(s.get("header_text", ""))
        self.header_text.setPlaceholderText("表示するテキスト")
        h_text_row.addWidget(self.header_text)
        hl.addLayout(h_text_row)

        self._h_align_grp, self._h_rbs = self._make_align_row(hl, s.get("header_align", "center"))
        root.addWidget(h_group)

        # ── Footer: page number ──────────────────────────────
        fn_group = QGroupBox("フッター ― ページ番号")
        fnl = QVBoxLayout(fn_group)

        self.footer_page_num = QCheckBox("ページ番号を追加 (- N / M -)")
        self.footer_page_num.setChecked(s.get("footer_page_num", False))
        fnl.addWidget(self.footer_page_num)

        self._fn_align_grp, self._fn_rbs = self._make_align_row(fnl, s.get("footer_page_num_align", "center"))
        root.addWidget(fn_group)

        # ── Footer: custom text ──────────────────────────────
        ft_group = QGroupBox("フッター ― テキスト")
        ftl = QVBoxLayout(ft_group)

        self.footer_text_check = QCheckBox("テキストを追加する")
        self.footer_text_check.setChecked(s.get("footer_text_enabled", False))
        ftl.addWidget(self.footer_text_check)

        ft_text_row = QHBoxLayout()
        ft_text_row.addWidget(QLabel("テキスト:"))
        self.footer_text = QLineEdit(s.get("footer_text", ""))
        self.footer_text.setPlaceholderText("表示するテキスト")
        ft_text_row.addWidget(self.footer_text)
        ftl.addLayout(ft_text_row)

        self._ft_align_grp, self._ft_rbs = self._make_align_row(ftl, s.get("footer_text_align", "center"))
        root.addWidget(ft_group)

        # ── Buttons ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        del_btn = QPushButton("削除（ヘッダー/フッターをクリア）")
        del_btn.setStyleSheet("color: #c0392b;")
        del_btn.clicked.connect(lambda: self.done(self._RESULT_DELETE))
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("適用")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(apply_btn)
        root.addLayout(btn_row)

    @staticmethod
    def _make_align_row(parent_layout, current: str):
        """Add a 左/中央/右 radio row to parent_layout; return (QButtonGroup, dict of rbs)."""
        row = QHBoxLayout()
        row.addWidget(QLabel("位置:"))
        rbs = {"left": QRadioButton("左"), "center": QRadioButton("中央"), "right": QRadioButton("右")}
        grp = QButtonGroup()
        for key, rb in rbs.items():
            grp.addButton(rb)
            row.addWidget(rb)
            if key == current:
                rb.setChecked(True)
        if not any(rb.isChecked() for rb in rbs.values()):
            rbs["center"].setChecked(True)
        row.addStretch()
        parent_layout.addLayout(row)
        return grp, rbs

    @staticmethod
    def _read_align(rbs: dict) -> str:
        for key, rb in rbs.items():
            if rb.isChecked():
                return key
        return "center"

    def get_settings(self) -> dict:
        """Return current dialog values as a dict (for persistence in MainWindow)."""
        return {
            "header_enabled":       self.header_check.isChecked(),
            "header_text":          self.header_text.text(),
            "header_align":         self._read_align(self._h_rbs),
            "footer_page_num":      self.footer_page_num.isChecked(),
            "footer_page_num_align": self._read_align(self._fn_rbs),
            "footer_text_enabled":  self.footer_text_check.isChecked(),
            "footer_text":          self.footer_text.text(),
            "footer_text_align":    self._read_align(self._ft_rbs),
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Editor")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)  # Allow reasonable resizing

        self.pdf_manager = PDFManager()

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
        self.splitter.addWidget(self.thumbnail_panel)

        # Right: Preview (with scroll + zoom support)
        self.preview_label = QLabel("PDFページをここに表示します")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #1e1e1e; color: #aaaaaa; font-size: 20px; border: 1px solid #333;"
        )

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

    def _load_icon(self, name: str) -> QIcon:
        """Load icon from resources/icons/ with fallback."""
        icon_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "resources", "icons", f"{name}.png"
        )
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon()  # empty icon as fallback

    def _create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(28, 28))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # Open
        open_action = QAction(self._load_icon("open"), "開く", self)
        open_action.setToolTip("PDFファイルを開く")
        open_action.triggered.connect(self.open_pdfs)
        toolbar.addAction(open_action)

        toolbar.addSeparator()

        # Merge
        merge_action = QAction(self._load_icon("merge"), "連結", self)
        merge_action.setToolTip("現在の状態を1つのPDFとして保存（連結）")
        merge_action.triggered.connect(self.merge_documents)
        toolbar.addAction(merge_action)

        # Split (stub)
        split_action = QAction(self._load_icon("split"), "分割", self)
        split_action.setToolTip("PDFを分割（未実装）")
        split_action.triggered.connect(self.split_document)
        toolbar.addAction(split_action)

        toolbar.addSeparator()

        # Rotation
        rotate_right = QAction(self._load_icon("rotate_right"), "右90°", self)
        rotate_right.setToolTip("選択ページを右に90度回転")
        rotate_right.triggered.connect(lambda: self.rotate_current_page(90))
        toolbar.addAction(rotate_right)

        rotate_left = QAction(self._load_icon("rotate_left"), "左90°", self)
        rotate_left.setToolTip("選択ページを左に90度回転")
        rotate_left.triggered.connect(lambda: self.rotate_current_page(-90))
        toolbar.addAction(rotate_left)

        rotate_180 = QAction(self._load_icon("rotate_180"), "180°", self)
        rotate_180.setToolTip("選択ページを180度回転")
        rotate_180.triggered.connect(lambda: self.rotate_current_page(180))
        toolbar.addAction(rotate_180)

        toolbar.addSeparator()

        # Header/Footer
        header_action = QAction(self._load_icon("header_footer"), "ヘッダー/フッター", self)
        header_action.setToolTip("ページ番号やタイトルを追加")
        header_action.triggered.connect(self.edit_header_footer)
        toolbar.addAction(header_action)

        toolbar.addSeparator()

        # Save
        save_action = QAction(self._load_icon("save"), "保存", self)
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
        """Split: Save the currently selected pages as a new PDF (in current visual order)."""
        selected_pages = self._get_selected_page_indices_in_order()
        if not selected_pages:
            QMessageBox.information(self, "情報", "分割したいページをサムネイルで選択してください")
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "分割したPDFを保存",
            "split_pages.pdf",
            "PDF Files (*.pdf)"
        )
        if not output_path:
            return

        success = self.pdf_manager.save_selected_pages(selected_pages, Path(output_path))
        if success:
            self.statusBar().showMessage(f"選択ページを分割して保存しました: {output_path}")
            QMessageBox.information(self, "完了", f"{len(selected_pages)}ページを新しいPDFとして保存しました。\n{output_path}")
        else:
            QMessageBox.warning(self, "エラー", "分割保存に失敗しました")

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

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "名前を付けて保存",
            "edited.pdf",
            "PDF Files (*.pdf)"
        )
        if not output_path:
            return

        success = self.pdf_manager.save_as(Path(output_path))
        if success:
            self.statusBar().showMessage(f"保存しました: {output_path}")
            QMessageBox.information(self, "完了", f"PDFを保存しました。\n{output_path}")

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
        """Return list of page indices currently selected in the tree, in visual order."""
        selected = []
        for i in range(self.thumbnail_panel.topLevelItemCount()):
            file_item = self.thumbnail_panel.topLevelItem(i)
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if child.isSelected():
                    idx = child.data(0, Qt.UserRole)
                    if idx is not None:
                        selected.append(idx)
        return selected
