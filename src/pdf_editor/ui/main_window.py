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
    QDialog, QGroupBox, QCheckBox, QLineEdit, QRadioButton, QButtonGroup, QPushButton,
    QComboBox, QSlider, QSpinBox, QRubberBand
)
from PySide6.QtCore import Qt, QSize, QEvent, QPoint, QRect
from PySide6.QtGui import QAction, QPixmap, QImage, QIcon
from pathlib import Path
import os
import fitz

from src.pdf_editor.ui.thumbnail_panel import ThumbnailPanel
from src.pdf_editor.pdf.pdf_manager import PDFManager


class PreviewLabel(QLabel):
    """Custom QLabel that allows selecting a crop area using mouse left drag."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.rubber_band: QRubberBand | None = None
        self.origin = QPoint()
        # Selected region relative to the base_pixmap coordinates (1.5x scale)
        self.selected_rect: QRect | None = None
        self.base_pixmap: QPixmap | None = None
        self.zoom = 1.0

    def set_base_pixmap(self, pixmap: QPixmap | None):
        self.base_pixmap = pixmap
        self.selected_rect = None
        if self.rubber_band:
            self.rubber_band.hide()
        self.update_display()

    def set_zoom(self, zoom: float):
        self.zoom = zoom
        self.update_display()
        self.update_rubber_band()

    def update_display(self):
        if not self.base_pixmap:
            self.clear()
            self.setText("PDFページをここに表示します")
            return

        scaled = self.base_pixmap.scaled(
            self.base_pixmap.size() * self.zoom,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.setPixmap(scaled)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.base_pixmap:
            scaled_size = self.base_pixmap.size() * self.zoom
            img_x = (self.width() - scaled_size.width()) // 2
            img_y = (self.height() - scaled_size.height()) // 2

            pos = event.position().toPoint()
            # Check if clicked inside the rendered page image
            if img_x <= pos.x() < img_x + scaled_size.width() and img_y <= pos.y() < img_y + scaled_size.height():
                self.origin = pos
                if not self.rubber_band:
                    self.rubber_band = QRubberBand(QRubberBand.Rectangle, self)
                self.rubber_band.setGeometry(QRect(self.origin, QSize()))
                self.rubber_band.show()
            else:
                self.clear_selection()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.rubber_band and self.rubber_band.isVisible() and self.base_pixmap:
            pos = event.position().toPoint()
            scaled_size = self.base_pixmap.size() * self.zoom
            img_x = (self.width() - scaled_size.width()) // 2
            img_y = (self.height() - scaled_size.height()) // 2

            # Constrain selection within the page boundaries
            x = max(img_x, min(pos.x(), img_x + scaled_size.width()))
            y = max(img_y, min(pos.y(), img_y + scaled_size.height()))

            self.rubber_band.setGeometry(QRect(self.origin, QPoint(x, y)).normalized())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rubber_band and self.rubber_band.isVisible() and self.base_pixmap:
            geom = self.rubber_band.geometry()
            # If the selected area is tiny, treat it as a click to clear selection
            if geom.width() > 5 and geom.height() > 5:
                scaled_size = self.base_pixmap.size() * self.zoom
                img_x = (self.width() - scaled_size.width()) // 2
                img_y = (self.height() - scaled_size.height()) // 2

                # Convert to base_pixmap coordinates
                rx = (geom.x() - img_x) / self.zoom
                ry = (geom.y() - img_y) / self.zoom
                rw = geom.width() / self.zoom
                rh = geom.height() / self.zoom

                self.selected_rect = QRect(int(rx), int(ry), int(rw), int(rh))
            else:
                self.clear_selection()
        else:
            super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_rubber_band()

    def update_rubber_band(self):
        if not self.selected_rect or not self.rubber_band or not self.base_pixmap:
            if self.rubber_band:
                self.rubber_band.hide()
            return

        scaled_size = self.base_pixmap.size() * self.zoom
        img_x = (self.width() - scaled_size.width()) // 2
        img_y = (self.height() - scaled_size.height()) // 2

        x = int(self.selected_rect.x() * self.zoom + img_x)
        y = int(self.selected_rect.y() * self.zoom + img_y)
        w = int(self.selected_rect.width() * self.zoom)
        h = int(self.selected_rect.height() * self.zoom)

        self.rubber_band.setGeometry(QRect(x, y, w, h))
        self.rubber_band.show()

    def clear_selection(self):
        self.selected_rect = None
        if self.rubber_band:
            self.rubber_band.hide()

    def get_pdf_clip_rect(self) -> fitz.Rect | None:
        """Get selection as fitz.Rect (in PDF points, relative to current page)."""
        if not self.selected_rect or not self.base_pixmap:
            return None
        # base_pixmap uses Matrix(1.5, 1.5), meaning 1 point = 1.5 pixels.
        # Scale back to PDF points by dividing by 1.5.
        x0 = self.selected_rect.x() / 1.5
        y0 = self.selected_rect.y() / 1.5
        x1 = (self.selected_rect.x() + self.selected_rect.width()) / 1.5
        y1 = (self.selected_rect.y() + self.selected_rect.height()) / 1.5
        return fitz.Rect(x0, y0, x1, y1)


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


class ExportDialog(QDialog):
    """Dialog for exporting pages as PNG or JPEG images.
    Supports scope (all/selected), format, DPI (incl. custom), JPEG quality, output folder (defaults to original file dir), prefix.
    """

    def __init__(
        self,
        parent=None,
        total_pages: int = 0,
        selected_pages: int = 0,
        initial_dir: str = "",
        suggested_prefix: str = "page",
        has_crop: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("画像としてエクスポート")
        self.setMinimumWidth(480)

        self._total = max(0, total_pages)
        self._selected = max(0, selected_pages)

        root = QVBoxLayout(self)

        # ── 出力対象 ─────────────────────────────────────
        scope_box = QGroupBox("出力対象")
        sl = QVBoxLayout(scope_box)
        self.scope_all = QRadioButton(f"すべてのページ（{self._total}ページ）")
        self.scope_sel = QRadioButton(f"選択中のページ（{self._selected}ページ）")
        if self._selected > 0:
            self.scope_sel.setChecked(True)
        else:
            self.scope_all.setChecked(True)
            self.scope_sel.setEnabled(False)
        sl.addWidget(self.scope_all)
        sl.addWidget(self.scope_sel)
        root.addWidget(scope_box)

        # ── 出力領域 ─────────────────────────────────────
        area_box = QGroupBox("出力領域")
        al = QVBoxLayout(area_box)
        self.area_all = QRadioButton("ページ全体")
        self.area_crop = QRadioButton("クロップした範囲")
        if has_crop:
            self.area_crop.setChecked(True)
        else:
            self.area_all.setChecked(True)
            self.area_crop.setEnabled(False)
            self.area_crop.setToolTip("プレビュー上で左ドラッグして範囲を選択すると利用可能になります")
        al.addWidget(self.area_all)
        al.addWidget(self.area_crop)
        root.addWidget(area_box)

        # ── 画像設定 ─────────────────────────────────────
        img_box = QGroupBox("画像設定")
        il = QVBoxLayout(img_box)

        # Format
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("形式:"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem("PNG（可逆・高品質）", "png")
        self.fmt_combo.addItem("JPEG（圧縮）", "jpg")
        self.fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        fmt_row.addWidget(self.fmt_combo)
        fmt_row.addStretch()
        il.addLayout(fmt_row)

        # DPI
        dpi_row = QHBoxLayout()
        dpi_row.addWidget(QLabel("解像度 (DPI):"))
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItem("72（画面・軽量）", 72)
        self.dpi_combo.addItem("150（標準）", 150)
        self.dpi_combo.addItem("300（印刷品質）", 300)
        self.dpi_combo.addItem("カスタム...", 0)
        self.dpi_combo.currentIndexChanged.connect(self._on_dpi_changed)
        dpi_row.addWidget(self.dpi_combo)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(50, 1200)
        self.dpi_spin.setValue(150)
        self.dpi_spin.setSuffix(" DPI")
        self.dpi_spin.setEnabled(False)
        dpi_row.addWidget(self.dpi_spin)
        dpi_row.addStretch()
        il.addLayout(dpi_row)

        # JPEG quality (only for JPEG)
        self.quality_row = QHBoxLayout()
        self.quality_row.addWidget(QLabel("JPEG画質:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(60, 100)
        self.quality_slider.setValue(90)
        self.quality_slider.setTickInterval(10)
        self.quality_slider.setTickPosition(QSlider.TicksBelow)
        self.quality_slider.valueChanged.connect(self._on_quality_changed)
        self.quality_row.addWidget(self.quality_slider)
        self.quality_label = QLabel("90")
        self.quality_label.setMinimumWidth(30)
        self.quality_row.addWidget(self.quality_label)
        il.addLayout(self.quality_row)

        root.addWidget(img_box)

        # ── 保存先 ───────────────────────────────────────
        save_box = QGroupBox("保存先")
        svl = QVBoxLayout(save_box)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("フォルダ:"))
        self.dir_edit = QLineEdit(initial_dir or str(Path.cwd()))
        self.dir_edit.setReadOnly(False)
        dir_row.addWidget(self.dir_edit, 1)
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        svl.addLayout(dir_row)

        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("接頭辞:"))
        self.prefix_edit = QLineEdit(suggested_prefix)
        self.prefix_edit.setPlaceholderText("page など")
        self.prefix_edit.textChanged.connect(self._update_example)
        prefix_row.addWidget(self.prefix_edit)
        svl.addLayout(prefix_row)

        self.example_label = QLabel()
        self.example_label.setStyleSheet("color: #666; font-size: 11px;")
        svl.addWidget(self.example_label)

        root.addWidget(save_box)

        # ── Buttons ─────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        export_btn = QPushButton("エクスポート実行")
        export_btn.setDefault(True)
        export_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(export_btn)
        root.addLayout(btn_row)

        # init UI state
        self._on_format_changed(0)
        self._on_dpi_changed(0)
        self._update_example()

    def _on_format_changed(self, _idx: int):
        is_jpg = self.fmt_combo.currentData() == "jpg"
        self.quality_slider.setEnabled(is_jpg)
        self.quality_label.setEnabled(is_jpg)
        for i in range(self.quality_row.count()):
            w = self.quality_row.itemAt(i).widget()
            if w:
                w.setEnabled(is_jpg)
        self._update_example()

    def _on_dpi_changed(self, _idx: int):
        is_custom = self.dpi_combo.currentData() == 0
        self.dpi_spin.setEnabled(is_custom)
        if is_custom:
            self.dpi_spin.setFocus()
            self.dpi_spin.selectAll()

    def _on_quality_changed(self, val: int):
        self.quality_label.setText(str(val))

    def _browse_dir(self):
        start = self.dir_edit.text() or str(Path.cwd())
        d = QFileDialog.getExistingDirectory(self, "保存先フォルダを選択", start)
        if d:
            self.dir_edit.setText(d)
            self._update_example()

    def _update_example(self):
        prefix = self.prefix_edit.text().strip() or "page"
        fmt = "png" if self.fmt_combo.currentData() == "png" else "jpg"
        ex1 = f"{prefix}_0001.{fmt}"
        ex2 = f"{prefix}_0002.{fmt}"
        self.example_label.setText(f"出力例: {ex1}  {ex2}  ...")

    def _get_dpi(self) -> int:
        data = self.dpi_combo.currentData()
        if data == 0:
            return self.dpi_spin.value()
        return int(data) if data else 150

    def get_settings(self) -> dict:
        """Return export config."""
        scope = "selected" if self.scope_sel.isChecked() and self.scope_sel.isEnabled() else "all"
        area = "crop" if self.area_crop.isChecked() and self.area_crop.isEnabled() else "all"
        fmt = self.fmt_combo.currentData() or "png"
        return {
            "scope": scope,
            "area": area,
            "format": fmt,
            "dpi": self._get_dpi(),
            "jpeg_quality": self.quality_slider.value(),
            "output_dir": self.dir_edit.text().strip() or str(Path.cwd()),
            "prefix": self.prefix_edit.text().strip() or "page",
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
        self.thumbnail_panel.pdf_extract_requested.connect(self._on_pdf_extract_requested)
        self.thumbnail_panel.image_extract_requested.connect(self._on_image_extract_requested)
        self.thumbnail_panel.file_close_requested.connect(self._on_file_close_requested)
        self.splitter.addWidget(self.thumbnail_panel)

        # Right: Preview (with scroll + zoom support)
        self.preview_label = PreviewLabel("PDFページをここに表示します")
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

        # Split / PDF cut-out
        split_action = QAction(self._load_icon("split"), "PDF切り出し", self)
        split_action.setToolTip("選択ページを新しいPDFとして保存（切り出し）")
        split_action.triggered.connect(self.split_document)
        toolbar.addAction(split_action)

        # Image export
        img_export_action = QAction(self._load_icon("image_export"), "画像出力", self)
        img_export_action.setToolTip("ページをPNG/JPG画像としてエクスポート（右クリックメニューからも可）")
        img_export_action.triggered.connect(self.export_images)
        toolbar.addAction(img_export_action)

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

    def open_pdfs(self, files=None):
        """Open one or more PDF files."""
        if not files:
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
        self.preview_label.set_base_pixmap(self.current_preview_pixmap)

        # Default to fit document width to the preview area
        self._fit_to_width()

    def _update_preview_display(self):
        """Apply current zoom to the preview label."""
        if self.current_preview_pixmap is None:
            return
        self.preview_label.set_zoom(self.current_zoom)

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
        has_crop = self.preview_label.selected_rect is not None
        dialog = ExportDialog(
            self,
            total_pages=total,
            selected_pages=sel_count,
            initial_dir=default_dir,
            suggested_prefix=suggested_prefix,
            has_crop=has_crop,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        cfg = dialog.get_settings()
        use_indices = selected if (cfg["scope"] == "selected" and selected) else list(range(total))
        clip = self.preview_label.get_pdf_clip_rect() if cfg["area"] == "crop" else None
        success, attempted, errs = self.pdf_manager.export_pages_to_images(
            indices=use_indices,
            output_dir=Path(cfg["output_dir"]),
            fmt=cfg["format"],
            dpi=cfg["dpi"],
            jpeg_quality=cfg.get("jpeg_quality", 90),
            prefix=cfg["prefix"],
            clip=clip,
        )
        out_dir = cfg["output_dir"]
        if success > 0:
            # Clear selection rubber band after export
            self.preview_label.clear_selection()
            msg = f"{success}/{attempted} ページを画像として保存しました。\n保存先: {out_dir}"
            if errs:
                msg += f"\n（{len(errs)}件のエラーあり。詳細はコンソール）"
            self.statusBar().showMessage(f"画像エクスポート完了: {out_dir}")
            QMessageBox.information(self, "完了", msg)
        else:
            QMessageBox.warning(self, "エラー", "画像エクスポートに失敗しました")

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
        has_crop = self.preview_label.selected_rect is not None
        dialog = ExportDialog(
            self,
            total_pages=total,
            selected_pages=sel_count,
            initial_dir=default_dir,
            suggested_prefix=suggested_prefix,
            has_crop=has_crop,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        cfg = dialog.get_settings()
        use_indices = indices if (cfg["scope"] == "selected" and indices) else list(range(total))
        clip = self.preview_label.get_pdf_clip_rect() if cfg["area"] == "crop" else None
        success, attempted, errs = self.pdf_manager.export_pages_to_images(
            indices=use_indices,
            output_dir=Path(cfg["output_dir"]),
            fmt=cfg["format"],
            dpi=cfg["dpi"],
            jpeg_quality=cfg.get("jpeg_quality", 90),
            prefix=cfg["prefix"],
            clip=clip,
        )
        out_dir = cfg["output_dir"]
        if success > 0:
            self.preview_label.clear_selection()
            msg = f"{success}/{attempted} ページを画像として保存しました。\n保存先: {out_dir}"
            if errs:
                msg += f"\n（{len(errs)}件のエラーあり）"
            self.statusBar().showMessage(f"画像エクスポート完了: {out_dir}")
            QMessageBox.information(self, "完了", msg)
        else:
            QMessageBox.warning(self, "エラー", "画像エクスポートに失敗しました")

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
        """Return list of page indices currently selected in the tree, in visual order (delegates to panel)."""
        return self.thumbnail_panel.get_selected_page_indices()

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

            finally:
                self.thumbnail_panel.blockSignals(False)

            self.statusBar().showMessage(f"{path.name} を閉じました")
        else:
            QMessageBox.warning(self, "エラー", f"{path.name} のクローズに失敗しました")
