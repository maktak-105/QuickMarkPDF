"""
Main Window for PDF Editor
Layout (per spec):
- Top: Icon-based menu (QToolBar)
- Left: Vertical thumbnail list (ThumbnailPanel)
- Right: Page preview
"""
import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea,
    QToolBar, QStatusBar, QFileDialog, QMessageBox, QInputDialog, QSplitter,
    QDialog, QRubberBand, QStackedWidget
)
from PySide6.QtCore import Qt, QSize, QEvent, QPoint, QRect, QTimer, QUrl, QMarginsF
from PySide6.QtGui import QAction, QPixmap, QImage, QIcon, QPageLayout, QPageSize
from pathlib import Path
import os
import fitz

from src.pdf_editor.ui.thumbnail_panel import ThumbnailPanel
from src.pdf_editor.pdf.pdf_manager import PDFManager
from src.pdf_editor.markdown.markdown_manager import MarkdownManager
from src.pdf_editor.utils.resources import resource_path, get_icon
from src.pdf_editor.ui.dialogs import HeaderFooterDialog, ExportDialog
from src.pdf_editor.ui.workers import Worker

try:
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineSettings = None
    QWebEngineView = None

logger = logging.getLogger(__name__)


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Editor")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)  # Allow reasonable resizing

        self.pdf_manager = PDFManager()
        self.markdown_manager = MarkdownManager()
        self.current_mode = "pdf"
        self.current_markdown_document = None
        self._pending_markdown_pdf_path: Path | None = None
        self._last_pdf_panel_width = 320

        # Unsaved-changes tracking (checked on window close)
        self._is_dirty = False

        # Background task state (load / save / export run via workers.Worker
        # so the UI thread never blocks on large PDFs)
        self._busy = False
        self._active_worker: Worker | None = None

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

        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview_scroll)

        self.markdown_view = QWebEngineView() if QWebEngineView else None
        if self.markdown_view is not None:
            settings = self.markdown_view.settings()
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            self.preview_stack.addWidget(self.markdown_view)
            self.markdown_view.page().pdfPrintingFinished.connect(self._on_markdown_pdf_finished)
        else:
            markdown_placeholder = QLabel("この環境では Markdown プレビューを利用できません")
            markdown_placeholder.setAlignment(Qt.AlignCenter)
            markdown_placeholder.setStyleSheet(
                "background-color: #f7f1e8; color: #6b6156; font-size: 18px; border: 1px solid #d8cfbf;"
            )
            self.preview_stack.addWidget(markdown_placeholder)

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

        self.splitter.addWidget(self.preview_stack)

        # Thumbnail panel: fixed size on window resize; preview takes all extra space
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([self.thumbnail_panel._panel_width, 1000])

        # Top toolbar
        self._create_toolbar()

        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("準備完了 - PDF または Markdown ファイルを開いてください")

        # Connect selection (now using QTreeWidget)
        self.thumbnail_panel.currentItemChanged.connect(self._on_thumbnail_selected)

    def _clear_pdf_preview(self):
        self.preview_label.clear_selection()
        self.preview_label.clear()
        self.preview_label.setText("PDFページをここに表示します")
        self.current_preview_pixmap = None
        self.current_zoom = 1.0

    def _mark_dirty(self):
        self._is_dirty = True

    def _mark_clean(self):
        self._is_dirty = False

    def _set_ui_busy(self, busy: bool):
        """Disable toolbar + thumbnail/preview area while a background task runs.

        This also prevents the user from triggering a second pdf_manager
        operation (e.g. clicking another thumbnail) while a worker thread is
        touching pdf_manager state, avoiding races on the underlying PyMuPDF
        documents (which are not thread-safe for concurrent access).
        """
        self._busy = busy
        enabled = not busy
        self._toolbar.setEnabled(enabled)
        central = self.centralWidget()
        if central is not None:
            central.setEnabled(enabled)

    def _run_in_background(self, func, on_success, on_error=None, busy_message: str = "処理中..."):
        """Run `func` on a background thread via workers.Worker so the UI stays responsive.

        Only one background task may run at a time; a second call while busy is
        ignored (with a status message) rather than queued or run concurrently.
        `on_success(result)` and `on_error(message)` run back on the UI thread.
        """
        if self._busy:
            self.statusBar().showMessage("他の処理が完了するまでお待ちください")
            return

        self._set_ui_busy(True)
        self.statusBar().showMessage(busy_message)

        worker = Worker(func)
        self._active_worker = worker  # keep a reference so it isn't garbage-collected mid-run

        def _handle_finished(result):
            self._set_ui_busy(False)
            on_success(result)

        def _handle_error(message):
            self._set_ui_busy(False)
            logger.error("Background task failed: %s", message)
            if on_error:
                on_error(message)
            else:
                self.statusBar().showMessage("処理に失敗しました")
                QMessageBox.warning(self, "エラー", f"処理に失敗しました。\n{message}")

        worker.finished.connect(_handle_finished)
        worker.error.connect(_handle_error)
        worker.run_in_thread()

    def _set_mode(self, mode: str):
        self.current_mode = mode
        is_pdf = mode == "pdf"
        self.preview_stack.setCurrentIndex(0 if is_pdf else 1)
        self.thumbnail_panel.setVisible(is_pdf)
        total_width = max(300, sum(self.splitter.sizes()) or self.width())
        if is_pdf:
            left_width = max(220, self._last_pdf_panel_width or self.thumbnail_panel._panel_width)
            self.splitter.setSizes([left_width, max(200, total_width - left_width)])
        else:
            current_sizes = self.splitter.sizes()
            if current_sizes and current_sizes[0] > 0:
                self._last_pdf_panel_width = current_sizes[0]
            self.splitter.setSizes([0, total_width])

        for action in (
            getattr(self, "merge_action", None),
            getattr(self, "split_action", None),
            getattr(self, "img_export_action", None),
            getattr(self, "rotate_right_action", None),
            getattr(self, "rotate_left_action", None),
            getattr(self, "rotate_180_action", None),
            getattr(self, "header_action", None),
            getattr(self, "small_action", None),
            getattr(self, "medium_action", None),
            getattr(self, "large_action", None),
            getattr(self, "size_label_action", None),
        ):
            if action is not None:
                action.setEnabled(is_pdf)

    def _load_markdown_document(self, path: Path):
        if self.markdown_view is None:
            QMessageBox.warning(
                self,
                "未対応",
                "この実行環境には Qt WebEngine が見つからないため、Markdown のプレビューを表示できません。"
            )
            return

        try:
            document = self.markdown_manager.load_markdown(path)
            html = self.markdown_manager.render_html_document(
                document,
                asset_urls=self._get_markdown_asset_urls(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "エラー", f"Markdown の読み込みに失敗しました。\n{exc}")
            return

        self.pdf_manager.close_all()
        self.thumbnail_panel.refresh()
        self.thumbnail_panel.clearSelection()
        self.current_markdown_document = document
        self._clear_pdf_preview()

        base_url = QUrl.fromLocalFile(str(path.parent) + os.sep)
        self.markdown_view.setHtml(html, base_url)
        self._set_mode("markdown")
        self.setWindowTitle(f"PDF Editor - {path.name}")
        self.statusBar().showMessage(f"Markdown を読み込みました: {path.name}")

    def _get_markdown_asset_urls(self) -> dict[str, str]:
        mermaid_path = resource_path("resources/vendor/mermaid/mermaid.min.js")
        mathjax_path = resource_path("resources/vendor/mathjax/tex-svg.js")
        asset_urls: dict[str, str] = {}
        if mermaid_path.exists():
            asset_urls["mermaid_js_url"] = QUrl.fromLocalFile(str(mermaid_path)).toString()
        if mathjax_path.exists():
            asset_urls["mathjax_js_url"] = QUrl.fromLocalFile(str(mathjax_path)).toString()
        return asset_urls

    def _create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(28, 28))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        self._toolbar = toolbar

        # Open
        self.open_action = QAction(get_icon("open"), "開く", self)
        self.open_action.setToolTip("PDF または Markdown ファイルを開く")
        self.open_action.triggered.connect(self.open_documents)
        toolbar.addAction(self.open_action)

        toolbar.addSeparator()

        # Merge
        self.merge_action = QAction(get_icon("merge"), "連結", self)
        self.merge_action.setToolTip("現在の状態を1つのPDFとして保存（連結）")
        self.merge_action.triggered.connect(self.merge_documents)
        toolbar.addAction(self.merge_action)

        # Split / PDF cut-out
        self.split_action = QAction(get_icon("split"), "PDF切り出し", self)
        self.split_action.setToolTip("選択ページを新しいPDFとして保存（切り出し）")
        self.split_action.triggered.connect(self.split_document)
        toolbar.addAction(self.split_action)

        # Image export
        self.img_export_action = QAction(get_icon("image_export"), "画像出力", self)
        self.img_export_action.setToolTip("ページをPNG/JPG画像としてエクスポート（右クリックメニューからも可）")
        self.img_export_action.triggered.connect(self.export_images)
        toolbar.addAction(self.img_export_action)

        toolbar.addSeparator()

        # Rotation
        self.rotate_right_action = QAction(get_icon("rotate_right"), "右90°", self)
        self.rotate_right_action.setToolTip("選択ページを右に90度回転")
        self.rotate_right_action.triggered.connect(lambda: self.rotate_current_page(90))
        toolbar.addAction(self.rotate_right_action)

        self.rotate_left_action = QAction(get_icon("rotate_left"), "左90°", self)
        self.rotate_left_action.setToolTip("選択ページを左に90度回転")
        self.rotate_left_action.triggered.connect(lambda: self.rotate_current_page(-90))
        toolbar.addAction(self.rotate_left_action)

        self.rotate_180_action = QAction(get_icon("rotate_180"), "180°", self)
        self.rotate_180_action.setToolTip("選択ページを180度回転")
        self.rotate_180_action.triggered.connect(lambda: self.rotate_current_page(180))
        toolbar.addAction(self.rotate_180_action)

        toolbar.addSeparator()

        # Header/Footer
        self.header_action = QAction(get_icon("header_footer"), "ヘッダー/フッター", self)
        self.header_action.setToolTip("ページ番号やタイトルを追加")
        self.header_action.triggered.connect(self.edit_header_footer)
        toolbar.addAction(self.header_action)

        toolbar.addSeparator()

        # Save
        self.save_action = QAction(get_icon("save"), "保存", self)
        self.save_action.setToolTip("PDF または Markdown を PDF として保存")
        self.save_action.triggered.connect(self.save_pdf)
        toolbar.addAction(self.save_action)

        toolbar.addSeparator()

        # Thumbnail size
        self.size_label_action = QAction("サムネ", self)
        self.size_label_action.setEnabled(False)
        toolbar.addAction(self.size_label_action)

        self.small_action = QAction("小", self)
        self.small_action.setToolTip("サムネイルを小さく")
        self.small_action.triggered.connect(lambda: self.set_thumbnail_size("small"))
        toolbar.addAction(self.small_action)

        self.medium_action = QAction("中", self)
        self.medium_action.setToolTip("標準サイズ")
        self.medium_action.triggered.connect(lambda: self.set_thumbnail_size("medium"))
        toolbar.addAction(self.medium_action)

        self.large_action = QAction("大", self)
        self.large_action.setToolTip("サムネイルを大きく")
        self.large_action.triggered.connect(lambda: self.set_thumbnail_size("large"))
        toolbar.addAction(self.large_action)

    def open_documents(self, files=None):
        """Open PDF files or a single Markdown document."""
        if not files:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "ファイルを選択",
                "",
                "Supported Files (*.pdf *.md *.markdown);;PDF Files (*.pdf);;Markdown Files (*.md *.markdown);;All Files (*)"
            )
            if not files:
                return

        paths = [Path(f) for f in files]
        markdown_paths = [path for path in paths if path.suffix.lower() in {".md", ".markdown"}]
        pdf_paths = [path for path in paths if path.suffix.lower() == ".pdf"]

        if markdown_paths and pdf_paths:
            QMessageBox.information(
                self,
                "読み込み方法",
                "Markdown と PDF の同時読み込みは未対応です。どちらか一方を選んでください。"
            )
            return

        if markdown_paths:
            if len(markdown_paths) > 1:
                QMessageBox.information(
                    self,
                    "読み込み方法",
                    "Markdown は1ファイルずつ表示します。先頭の1件を読み込みます。"
                )
            self._load_markdown_document(markdown_paths[0])
            return

        if not pdf_paths:
            QMessageBox.information(self, "未対応", "対応しているのは PDF / Markdown ファイルです。")
            return

        self.open_pdfs(pdf_paths)

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

        def _do_load():
            return self.pdf_manager.load_pdfs(paths)

        def _on_loaded(loaded):
            if loaded > 0:
                self.current_markdown_document = None
                self._set_mode("pdf")
                self.thumbnail_panel.refresh()

                # Auto-select the first page so preview + thumbnails show immediately
                if self.thumbnail_panel.topLevelItemCount() > 0:
                    first_file = self.thumbnail_panel.topLevelItem(0)
                    if first_file.childCount() > 0:
                        first_page = first_file.child(0)
                        self.thumbnail_panel.setCurrentItem(first_page)
                        # Force preview update in case the signal doesn't fire
                        self._on_thumbnail_selected(first_page)

                self.setWindowTitle("PDF Editor")
                self.statusBar().showMessage(f"{loaded} ファイル読み込み完了（全{self.pdf_manager.get_page_count()}ページ）")
                self._mark_dirty()
            else:
                self.statusBar().showMessage("PDFの読み込みに失敗しました")
                QMessageBox.warning(self, "エラー", "PDFの読み込みに失敗しました")

        self._run_in_background(_do_load, _on_loaded, busy_message="PDFを読み込んでいます...")

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
        if self.current_mode != "pdf":
            self._set_mode("pdf")

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

        self._mark_dirty()
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

        def _do_export():
            return self.pdf_manager.save_selected_pages(indices, Path(output_path))

        def _on_exported(success):
            if success:
                self.statusBar().showMessage(f"PDFを切り出しました: {output_path}")
                QMessageBox.information(self, "完了", f"{len(indices)}ページを新しいPDFとして保存しました。\n{output_path}")
            else:
                self.statusBar().showMessage("PDFの切り出し保存に失敗しました")
                QMessageBox.warning(self, "エラー", "PDFの切り出し保存に失敗しました")

        self._run_in_background(_do_export, _on_exported, busy_message="PDFを切り出しています...")

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
        out_dir = cfg["output_dir"]

        def _do_export():
            return self.pdf_manager.export_pages_to_images(
                indices=use_indices,
                output_dir=Path(out_dir),
                fmt=cfg["format"],
                dpi=cfg["dpi"],
                jpeg_quality=cfg.get("jpeg_quality", 90),
                prefix=cfg["prefix"],
                clip=clip,
            )

        def _on_exported(result):
            success, attempted, errs = result
            if success > 0:
                # Clear selection rubber band after export
                self.preview_label.clear_selection()
                msg = f"{success}/{attempted} ページを画像として保存しました。\n保存先: {out_dir}"
                if errs:
                    msg += f"\n（{len(errs)}件のエラーあり。詳細はコンソール）"
                self.statusBar().showMessage(f"画像エクスポート完了: {out_dir}")
                QMessageBox.information(self, "完了", msg)
            else:
                self.statusBar().showMessage("画像エクスポートに失敗しました")
                QMessageBox.warning(self, "エラー", "画像エクスポートに失敗しました")

        self._run_in_background(_do_export, _on_exported, busy_message="画像をエクスポートしています...")

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
        out_dir = cfg["output_dir"]

        def _do_export():
            return self.pdf_manager.export_pages_to_images(
                indices=use_indices,
                output_dir=Path(out_dir),
                fmt=cfg["format"],
                dpi=cfg["dpi"],
                jpeg_quality=cfg.get("jpeg_quality", 90),
                prefix=cfg["prefix"],
                clip=clip,
            )

        def _on_exported(result):
            success, attempted, errs = result
            if success > 0:
                self.preview_label.clear_selection()
                msg = f"{success}/{attempted} ページを画像として保存しました。\n保存先: {out_dir}"
                if errs:
                    msg += f"\n（{len(errs)}件のエラーあり）"
                self.statusBar().showMessage(f"画像エクスポート完了: {out_dir}")
                QMessageBox.information(self, "完了", msg)
            else:
                self.statusBar().showMessage("画像エクスポートに失敗しました")
                QMessageBox.warning(self, "エラー", "画像エクスポートに失敗しました")

        self._run_in_background(_do_export, _on_exported, busy_message="画像をエクスポートしています...")

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

            self._mark_dirty()
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
            self._mark_dirty()
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
        self._mark_dirty()
        self.statusBar().showMessage("ヘッダー/フッターを適用しました")

    def _refresh_after_hf(self):
        self.thumbnail_panel.refresh()
        current_item = self.thumbnail_panel.currentItem()
        if current_item:
            self._on_thumbnail_selected(current_item)

    def _save_markdown_as_pdf(self):
        if self.current_markdown_document is None or self.markdown_view is None:
            QMessageBox.information(self, "情報", "保存する Markdown がありません")
            return

        default_name = f"{self.current_markdown_document.path.stem}.pdf"
        default_path = str(self.current_markdown_document.path.with_suffix(".pdf"))
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Markdown を PDF として保存",
            default_path or default_name,
            "PDF Files (*.pdf)"
        )
        if not output_path:
            return

        self._pending_markdown_pdf_path = Path(output_path)
        self.statusBar().showMessage("Markdown を PDF に変換しています...")
        self._export_markdown_pdf_when_ready()

    def _export_markdown_pdf_when_ready(self, attempts: int = 0):
        if self.markdown_view is None or self._pending_markdown_pdf_path is None:
            return

        def after_check(is_ready):
            ready = bool(is_ready)
            if ready or attempts >= 24:
                layout = QPageLayout(
                    QPageSize(QPageSize.PageSizeId.A4),
                    QPageLayout.Orientation.Portrait,
                    QMarginsF(12, 12, 12, 12),
                )
                self.markdown_view.page().printToPdf(str(self._pending_markdown_pdf_path), layout)
                return
            QTimer.singleShot(250, lambda: self._export_markdown_pdf_when_ready(attempts + 1))

        self.markdown_view.page().runJavaScript(
            "document.body && document.body.dataset.rendered === '1';",
            after_check,
        )

    def _on_markdown_pdf_finished(self, file_path: str, success: bool):
        if not self._pending_markdown_pdf_path:
            return
        path = str(self._pending_markdown_pdf_path)
        self._pending_markdown_pdf_path = None
        if success:
            self.statusBar().showMessage(f"Markdown PDF を保存しました: {path}")
            QMessageBox.information(self, "完了", f"PDFを保存しました。\n{path}")
        else:
            self.statusBar().showMessage("Markdown PDF の保存に失敗しました")
            QMessageBox.warning(self, "エラー", f"Markdown の PDF 保存に失敗しました。\n{file_path or path}")

    def save_pdf(self):
        """Export current state (after reorder/rotate/header) as a new PDF."""
        if self.current_mode == "markdown":
            self._save_markdown_as_pdf()
            return

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

        def _do_save():
            return self.pdf_manager.save_as(Path(output_path))

        def _on_saved(success):
            if success:
                self.statusBar().showMessage(f"保存しました: {output_path}")
                QMessageBox.information(self, "完了", f"PDFを保存しました。\n{output_path}")
                self._mark_clean()

        self._run_in_background(_do_save, _on_saved, busy_message="PDFを保存しています...")

    def set_thumbnail_size(self, size: str):
        """Change left thumbnail size and refresh."""
        current_page = self.thumbnail_panel.currentRow()

        self.thumbnail_panel.set_thumbnail_size(size)
        self.thumbnail_panel.refresh()

        # Resize the left pane to fit the new thumbnail width (transfer the difference to the right pane)
        sizes = self.splitter.sizes()
        new_w = self.thumbnail_panel._panel_width
        self.splitter.setSizes([new_w, max(200, sizes[0] + sizes[1] - new_w)])
        self._last_pdf_panel_width = new_w

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

            self._mark_dirty()
            self.statusBar().showMessage(f"{path.name} を閉じました")
        else:
            QMessageBox.warning(self, "エラー", f"{path.name} のクローズに失敗しました")

    def closeEvent(self, event):
        """Confirm before closing if there are unsaved PDF edits."""
        if self._is_dirty:
            reply = QMessageBox.question(
                self,
                "未保存の変更",
                "保存されていない変更があります。終了しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
