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
    QDialog, QRubberBand, QStackedWidget, QLineEdit
)
from PySide6.QtCore import Qt, QSize, QEvent, QPoint, QRect, QTimer, QUrl, QMarginsF, QSettings
from PySide6.QtGui import QAction, QActionGroup, QPixmap, QImage, QIcon, QPageLayout, QPageSize, QKeySequence
from pathlib import Path
import os
import fitz

from src.pdf_editor.ui.thumbnail_panel import ThumbnailPanel
from src.pdf_editor.pdf.pdf_manager import PDFManager
from src.pdf_editor.markdown.markdown_manager import MarkdownManager
from src.pdf_editor.utils.resources import resource_path, get_icon
from src.pdf_editor.ui.dialogs import ExportDialog, PreferencesDialog
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
        self.setWindowTitle("QuickMarkPDF")
        self.resize(1024, 768)
        self.setMinimumSize(900, 600)  # Allow reasonable resizing
        self.setAcceptDrops(True)

        self.pdf_manager = PDFManager()
        self.markdown_manager = MarkdownManager()
        self.current_mode = "pdf"
        self.current_markdown_document = None
        self._pending_markdown_pdf_path: Path | None = None
        self._last_pdf_panel_width = None  # not yet resized by the user this session

        # Unsaved-changes tracking (checked on window close)
        self._is_dirty = False

        # Background task state (load / save / export run via workers.Worker
        # so the UI thread never blocks on large PDFs)
        self._busy = False
        self._active_worker: Worker | None = None
        self._pending_on_success = None
        self._pending_on_error = None

        # Remembered image-export preferences (format/DPI/JPEG quality) across
        # dialog opens in this session
        self._export_settings: dict = {}

        # Persisted across app restarts: window geometry, last-used folder,
        # last-used thumbnail size, wheel mode (see _restore_settings / _save_settings)
        self._qsettings = QSettings("maktak-105", "QuickMarkPDF")
        self._last_used_dir: str = ""
        # "zoom" (default): wheel = zoom, right-drag = pan.
        # "scroll": wheel = vertical scroll, right-drag = zoom (down=in, up=out).
        self._wheel_mode: str = "zoom"

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
        self.thumbnail_panel.page_delete_requested.connect(self._on_page_delete_requested)
        self.thumbnail_panel.page_rotate_requested.connect(self._on_page_rotate_requested)
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

        # For right-click drag: pans in "zoom" wheel mode, zooms in "scroll" wheel mode
        self._panning = False
        self._pan_start_pos = None
        self._h_scroll_start = 0
        self._v_scroll_start = 0
        self._zoom_drag_start = 1.0

        # Install event filter to control wheel behavior (zoom only, no scroll)
        viewport = self.preview_scroll.viewport()
        viewport.installEventFilter(self)

        self.splitter.addWidget(self.preview_stack)

        # Thumbnail panel: fixed size on window resize; preview takes all extra space
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([self.thumbnail_panel._panel_width, 1000])

        # Menu bar
        self._create_menu_bar()

        # Top toolbar
        self._create_toolbar()

        # Delete key: remove selected page(s) (not shown on the toolbar)
        self.delete_page_action = QAction(self)
        self.delete_page_action.setShortcut(QKeySequence(Qt.Key_Delete))
        self.delete_page_action.triggered.connect(self.delete_selected_pages)
        self.addAction(self.delete_page_action)

        # Ctrl+Z: undo the last reorder/rotate/delete/file-close (not shown on the toolbar)
        self.undo_action = QAction(self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.undo_last_action)
        self.addAction(self.undo_action)

        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("準備完了 - PDF または Markdown ファイルを開いてください")

        # Connect selection
        self.thumbnail_panel.currentItemChanged.connect(self._on_thumbnail_selected)

        self._restore_settings()

    def _restore_settings(self):
        """Restore window geometry, last-used folder, and thumbnail size from
        the previous session (QSettings). No-op fields default to their
        already-set-up initial values.
        """
        geometry = self._qsettings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        self._last_used_dir = self._qsettings.value("paths/last_used_dir", "", type=str)

        size = self._qsettings.value("thumbnails/size", "medium", type=str)
        if size in ("small", "medium", "large"):
            self.thumbnail_panel.set_thumbnail_size(size)
            action = {"small": self.small_action, "medium": self.medium_action, "large": self.large_action}[size]
            action.setChecked(True)

        wheel_mode = self._qsettings.value("preview/wheel_mode", "zoom", type=str)
        if wheel_mode in ("zoom", "scroll"):
            self._wheel_mode = wheel_mode

    def _save_settings(self):
        self._qsettings.setValue("window/geometry", self.saveGeometry())
        self._qsettings.setValue("paths/last_used_dir", self._last_used_dir)
        self._qsettings.setValue("thumbnails/size", self.thumbnail_panel._current_size)
        self._qsettings.setValue("preview/wheel_mode", self._wheel_mode)

    def _remember_dir_from_path(self, file_path: str):
        if file_path:
            self._last_used_dir = str(Path(file_path).parent)

    def _remember_dir_from_paths(self, file_paths: list[str]):
        if file_paths:
            self._remember_dir_from_path(file_paths[0])

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
        self._size_toolbar.setEnabled(enabled)
        central = self.centralWidget()
        if central is not None:
            central.setEnabled(enabled)

    def _run_in_background(self, func, on_success, on_error=None, busy_message: str = "処理中..."):
        """Run `func` on a background thread via workers.Worker so the UI stays responsive.

        Only one background task may run at a time; a second call while busy is
        ignored (with a status message) rather than queued or run concurrently.
        `on_success(result)` and `on_error(message)` run back on the UI thread.

        IMPORTANT: worker.finished/error are connected to `self._on_worker_finished`
        / `self._on_worker_error` — genuine bound methods of this QObject — and
        NOT directly to `on_success`/`on_error` (which are often plain closures
        defined at the call site). PySide6 only auto-detects a cross-thread
        connection (and dispatches it via the event loop, back on the main
        thread) when the receiver is a bound QObject method with known thread
        affinity; a signal connected directly to a plain function/lambda instead
        runs on the EMITTING thread. Connecting straight to on_success/on_error
        previously caused GUI code to execute on the worker thread — a Qt
        threading violation that manifested as freezes/crashes. Once dispatch
        has correctly reached the main thread via the bound-method connection,
        invoking the stored on_success/on_error callable is a plain same-thread
        call and is safe.
        """
        if self._busy:
            self.statusBar().showMessage("他の処理が完了するまでお待ちください")
            return

        self._set_ui_busy(True)
        self.statusBar().showMessage(busy_message)

        self._pending_on_success = on_success
        self._pending_on_error = on_error

        worker = Worker(func)
        self._active_worker = worker  # keep a reference so it isn't garbage-collected mid-run
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        worker.run_in_thread()

    def _on_worker_finished(self, result):
        """Bound-method receiver for Worker.finished — see _run_in_background docstring
        for why this must be a bound method rather than a closure."""
        self._set_ui_busy(False)
        callback = self._pending_on_success
        self._pending_on_success = None
        self._pending_on_error = None
        if callback:
            callback(result)

    def _on_worker_error(self, message: str):
        """Bound-method receiver for Worker.error — see _run_in_background docstring
        for why this must be a bound method rather than a closure."""
        self._set_ui_busy(False)
        callback = self._pending_on_error
        self._pending_on_success = None
        self._pending_on_error = None
        logger.error("Background task failed: %s", message)
        if callback:
            callback(message)
        else:
            self.statusBar().showMessage("処理に失敗しました")
            QMessageBox.warning(self, "エラー", f"処理に失敗しました。\n{message}")

    def _set_mode(self, mode: str):
        self.current_mode = mode
        is_pdf = mode == "pdf"
        self.preview_stack.setCurrentIndex(0 if is_pdf else 1)
        self.thumbnail_panel.setVisible(is_pdf)
        total_width = max(300, sum(self.splitter.sizes()) or self.width())
        if is_pdf:
            # The 220px floor only guards a remembered manual width (from an
            # earlier mode switch) against being unreasonably narrow. The
            # fallback — the panel's own exact width for the current thumbnail
            # size — already has its own correct minimum via setMinimumWidth(),
            # so it must NOT also be floored to 220, or "small"/"medium" (144px/
            # 184px) would be forced wider than needed on first PDF open.
            if self._last_pdf_panel_width:
                left_width = max(220, self._last_pdf_panel_width)
            else:
                left_width = self.thumbnail_panel._panel_width
            self.splitter.setSizes([left_width, max(200, total_width - left_width)])
        else:
            current_sizes = self.splitter.sizes()
            if current_sizes and current_sizes[0] > 0:
                self._last_pdf_panel_width = current_sizes[0]
            self.splitter.setSizes([0, total_width])

        for action in (
            getattr(self, "split_action", None),
            getattr(self, "img_export_action", None),
            getattr(self, "rotate_right_action", None),
            getattr(self, "rotate_left_action", None),
            getattr(self, "rotate_180_action", None),
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

        if not self._confirm_discard_pdf_changes("保存されていない変更があります。破棄してMarkdownを開きますか？"):
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
        self.setWindowTitle(f"QuickMarkPDF - {path.name}")
        self.statusBar().showMessage(f"Markdown を読み込みました: {path.name}")

        # 高DPI環境におけるフォントのかすれ・ぼやけ対策
        # 読み込み完了後に微小なリサイズを一瞬トリガーして、Chromium側の高解像度レンダリングを強制します
        def force_repaint():
            if self.markdown_view and self.markdown_view.isVisible():
                self.markdown_view.resize(self.markdown_view.width() + 1, self.markdown_view.height())
                self.markdown_view.resize(self.markdown_view.width() - 1, self.markdown_view.height())
        QTimer.singleShot(200, force_repaint)

    def _get_markdown_asset_urls(self) -> dict[str, str]:
        mermaid_path = resource_path("resources/vendor/mermaid/mermaid.min.js")
        mathjax_path = resource_path("resources/vendor/mathjax/tex-svg.js")
        asset_urls: dict[str, str] = {}
        if mermaid_path.exists():
            asset_urls["mermaid_js_url"] = QUrl.fromLocalFile(str(mermaid_path)).toString()
        if mathjax_path.exists():
            asset_urls["mathjax_js_url"] = QUrl.fromLocalFile(str(mathjax_path)).toString()
        return asset_urls

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        settings_menu = menu_bar.addMenu("設定")
        prefs_action = QAction("環境設定...", self)
        prefs_action.triggered.connect(self._open_preferences)
        settings_menu.addAction(prefs_action)

    def _open_preferences(self):
        dlg = PreferencesDialog(self, wheel_mode=self._wheel_mode)
        if dlg.exec() == QDialog.Accepted:
            self._wheel_mode = dlg.get_settings()["wheel_mode"]

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
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.triggered.connect(self.open_documents)
        toolbar.addAction(self.open_action)

        toolbar.addSeparator()

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

        # Save
        self.save_action = QAction(get_icon("save"), "保存", self)
        self.save_action.setToolTip("PDF または Markdown を PDF として保存")
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.triggered.connect(self.save_pdf)
        toolbar.addAction(self.save_action)

        # "開く"/"保存" are short-label buttons that end up narrower than
        # "画像出力" under ToolButtonTextUnderIcon sizing — pad them to match.
        img_export_width = toolbar.widgetForAction(self.img_export_action).sizeHint().width()
        for action in (self.open_action, self.save_action):
            btn = toolbar.widgetForAction(action)
            if btn is not None:
                btn.setMinimumWidth(img_export_width)

        # Thumbnail size — second toolbar row (below the main actions)
        self.addToolBarBreak(Qt.TopToolBarArea)
        size_toolbar = QToolBar("Thumbnail Size Toolbar")
        size_toolbar.setMovable(False)
        size_toolbar.setIconSize(QSize(28, 28))
        size_toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(Qt.TopToolBarArea, size_toolbar)
        self._size_toolbar = size_toolbar

        self.size_label_action = QAction("サムネ", self)
        self.size_label_action.setEnabled(False)
        size_toolbar.addAction(self.size_label_action)

        self._thumbnail_size_group = QActionGroup(self)
        self._thumbnail_size_group.setExclusive(True)

        self.small_action = QAction("小", self)
        self.small_action.setToolTip("サムネイルを小さく")
        self.small_action.setCheckable(True)
        self.small_action.triggered.connect(lambda: self.set_thumbnail_size("small"))
        self._thumbnail_size_group.addAction(self.small_action)
        size_toolbar.addAction(self.small_action)

        self.medium_action = QAction("中", self)
        self.medium_action.setToolTip("標準サイズ")
        self.medium_action.setCheckable(True)
        self.medium_action.setChecked(True)  # matches ThumbnailPanel's default ("medium")
        self.medium_action.triggered.connect(lambda: self.set_thumbnail_size("medium"))
        self._thumbnail_size_group.addAction(self.medium_action)
        size_toolbar.addAction(self.medium_action)

        self.large_action = QAction("大", self)
        self.large_action.setToolTip("サムネイルを大きく")
        self.large_action.setCheckable(True)
        self.large_action.triggered.connect(lambda: self.set_thumbnail_size("large"))
        self._thumbnail_size_group.addAction(self.large_action)
        size_toolbar.addAction(self.large_action)

    def _droppable_paths(self, mime_data):
        """Local .pdf/.md/.markdown file paths from a drag's URL list, or
        an empty list if the drag carries no such files (e.g. an internal
        ThumbnailPanel reorder drag, which has no URLs at all)."""
        if not mime_data.hasUrls():
            return []
        paths = [Path(url.toLocalFile()) for url in mime_data.urls() if url.isLocalFile()]
        return [p for p in paths if p.suffix.lower() in {".pdf", ".md", ".markdown"}]

    def dragEnterEvent(self, event):
        if self._droppable_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._droppable_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self._droppable_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._remember_dir_from_paths(paths)
        self.open_documents([str(p) for p in paths])

    def open_documents(self, files=None):
        """Open PDF files or a single Markdown document."""
        if not files:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "ファイルを選択",
                self._last_used_dir,
                "Supported Files (*.pdf *.md *.markdown);;PDF Files (*.pdf);;Markdown Files (*.md *.markdown);;All Files (*)"
            )
            if not files:
                return
            self._remember_dir_from_paths(files)

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
                self._last_used_dir,
                "PDF Files (*.pdf);;All Files (*)"
            )
            if not files:
                return
            self._remember_dir_from_paths(files)

        paths = [Path(f) for f in files]

        def _do_load():
            return self.pdf_manager.load_pdfs(paths)

        def _on_loaded(result):
            extra_loaded = self._retry_password_protected_files(result.password_required)
            total_loaded = result.loaded_count + extra_loaded

            if total_loaded > 0:
                # A fresh "open files" action isn't meaningfully undoable with the
                # lightweight snapshot mechanism, so start a new undo history.
                self.pdf_manager.clear_undo_history()
                self.current_markdown_document = None
                self._set_mode("pdf")
                self.thumbnail_panel.refresh()

                # Auto-select the first page so preview + thumbnails show immediately
                if self.thumbnail_panel.count() > 0:
                    first_page = self.thumbnail_panel.item(0)
                    self.thumbnail_panel.setCurrentItem(first_page)
                    # Force preview update in case the signal doesn't fire
                    self._on_thumbnail_selected(first_page)

                self.setWindowTitle("QuickMarkPDF")
                self.statusBar().showMessage(f"{total_loaded} ファイル読み込み完了（全{self.pdf_manager.get_page_count()}ページ）")
            elif not result.password_required and not result.duplicate_files:
                self.statusBar().showMessage("PDFの読み込みに失敗しました")
                QMessageBox.warning(self, "エラー", "PDFの読み込みに失敗しました")

            if result.duplicate_files:
                names = "\n".join(p.name for p in result.duplicate_files)
                QMessageBox.information(
                    self,
                    "読み込み済みのためスキップ",
                    f"以下のファイルは既に読み込み済みのため、スキップしました。\n{names}"
                )

        self._run_in_background(_do_load, _on_loaded, busy_message="PDFを読み込んでいます...")

    def _retry_password_protected_files(self, paths: list[Path]) -> int:
        """Prompt for a password for each encrypted file and try to load it.

        Runs synchronously on the UI thread (interactive dialogs), one file at a
        time, since password entry is inherently a user-in-the-loop operation.
        Returns the number of files successfully loaded this way.
        """
        if not paths:
            return 0

        loaded = 0
        failed_names = []
        for path in paths:
            opened = False
            for _attempt in range(3):
                pw, ok = QInputDialog.getText(
                    self,
                    "パスワードが必要です",
                    f"「{path.name}」はパスワードで保護されています。パスワードを入力してください。",
                    QLineEdit.Password,
                )
                if not ok:
                    break  # user cancelled — give up on this file
                result = self.pdf_manager.load_pdfs([path], passwords={path: pw})
                if result.loaded_count > 0:
                    opened = True
                    loaded += 1
                    break
            if not opened:
                failed_names.append(path.name)

        if failed_names:
            QMessageBox.warning(
                self,
                "パスワードが必要",
                "以下のファイルはパスワードが正しくないか、入力がキャンセルされたため開けませんでした。\n"
                + "\n".join(failed_names),
            )
        return loaded

    def _on_thumbnail_selected(self, current_item, previous_item=None):
        """Called when a thumbnail (page) is selected in the list."""
        if current_item is None or not self.pdf_manager:
            return

        row = current_item.data(Qt.UserRole)
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
        # Preview viewport input, gated by self._wheel_mode (Settings > 環境設定):
        # "zoom" (default): wheel = zoom, right-drag = pan.
        # "scroll": wheel = vertical scroll (native), right-drag = zoom (down=in, up=out).
        if obj is self.preview_scroll.viewport():
            if event.type() == QEvent.Type.Wheel:
                if self._wheel_mode == "zoom":
                    if self.current_preview_pixmap is not None:
                        delta = event.angleDelta().y()
                        factor = 1.15 if delta > 0 else 1 / 1.15
                        self.current_zoom *= factor
                        self.current_zoom = max(0.1, min(self.current_zoom, 8.0))
                        self._update_preview_display()
                    event.accept()
                    return True  # Block default scrolling
                # "scroll" mode: fall through to native QScrollArea vertical scrolling.
            # Right button drag: pan (zoom mode) or zoom (scroll mode)
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.RightButton:
                self._panning = True
                self._pan_start_pos = event.position().toPoint()
                if self._wheel_mode == "zoom":
                    self._h_scroll_start = self.preview_scroll.horizontalScrollBar().value()
                    self._v_scroll_start = self.preview_scroll.verticalScrollBar().value()
                else:
                    self._zoom_drag_start = self.current_zoom
                self.preview_scroll.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return True
            if event.type() == QEvent.Type.MouseMove and self._panning:
                if self._pan_start_pos:
                    delta = event.position().toPoint() - self._pan_start_pos
                    if self._wheel_mode == "zoom":
                        h_bar = self.preview_scroll.horizontalScrollBar()
                        v_bar = self.preview_scroll.verticalScrollBar()
                        h_bar.setValue(self._h_scroll_start - delta.x())
                        v_bar.setValue(self._v_scroll_start - delta.y())
                    elif self.current_preview_pixmap is not None:
                        factor = 1.005 ** delta.y()  # drag down (+y) = zoom in
                        self.current_zoom = max(0.1, min(self._zoom_drag_start * factor, 8.0))
                        self._update_preview_display()
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

    def _on_page_reordered(self, new_order: list[int], moved_old_indices: list[int]):
        """User dragged thumbnail(s) → reorder in manager."""
        self.pdf_manager.reorder_pages(new_order)
        self.thumbnail_panel.refresh()

        # Restore selection to the page(s) we were dragging, at their new positions.
        # set_selected_page_indices() already skips collapsed parents (no auto-expand).
        new_positions = sorted(
            new_order.index(old_idx) for old_idx in moved_old_indices if old_idx in new_order
        )
        if new_positions:
            self.thumbnail_panel.set_selected_page_indices(new_positions)
        elif self.thumbnail_panel.count() > 0:
            self.thumbnail_panel.setCurrentRow(0)

        self._mark_dirty()
        self.statusBar().showMessage("ページ順を更新しました")

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
        self._remember_dir_from_path(output_path)

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
            initial=self._export_settings,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        cfg = dialog.get_settings()
        self._export_settings = {"format": cfg["format"], "dpi": cfg["dpi"], "jpeg_quality": cfg["jpeg_quality"]}
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
            initial=self._export_settings,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        cfg = dialog.get_settings()
        self._export_settings = {"format": cfg["format"], "dpi": cfg["dpi"], "jpeg_quality": cfg["jpeg_quality"]}
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
        """Rotate the selected page(s) by the given degrees. Keep selection."""
        indices = self._get_selected_page_indices_in_order()
        if not indices:
            current = self.thumbnail_panel.currentRow()
            if current >= 0:
                indices = [current]
        self._rotate_pages(indices, degrees)

    def _on_page_rotate_requested(self, indices: list[int], degrees: int):
        """Context menu (thumbnail right-click) → 回転"""
        if not indices:
            indices = self.thumbnail_panel.get_selected_page_indices()
        if not indices:
            cur = self.thumbnail_panel.currentRow()
            if cur >= 0:
                indices = [cur]
        self._rotate_pages(indices, degrees)

    def _rotate_pages(self, indices: list[int], degrees: int):
        if not indices:
            QMessageBox.information(self, "情報", "回転したいページを選択してください")
            return

        self.pdf_manager.rotate_pages(indices, degrees)

        # Remember selection and restore after refresh
        self.thumbnail_panel.refresh()
        self.thumbnail_panel.set_selected_page_indices(indices)

        # Refresh preview (signal will also fire, but we force it for safety)
        current_item = self.thumbnail_panel.currentItem()
        if self.current_preview_pixmap is not None and current_item:
            self._on_thumbnail_selected(current_item)

        self._mark_dirty()
        if len(indices) > 1:
            self.statusBar().showMessage(f"{len(indices)}ページを{degrees}度回転しました")
        else:
            self.statusBar().showMessage(f"ページを{degrees}度回転しました")

    def delete_selected_pages(self):
        """Delete the selected page(s). Bound to the Delete key."""
        indices = self._get_selected_page_indices_in_order()
        if not indices:
            current = self.thumbnail_panel.currentRow()
            if current >= 0:
                indices = [current]
        self._delete_pages(indices)

    def _on_page_delete_requested(self, indices: list[int]):
        """Context menu (thumbnail right-click) → ページを削除"""
        if not indices:
            indices = self.thumbnail_panel.get_selected_page_indices()
        if not indices:
            cur = self.thumbnail_panel.currentRow()
            if cur >= 0:
                indices = [cur]
        self._delete_pages(indices)

    def _delete_pages(self, indices: list[int]):
        if not indices:
            QMessageBox.information(self, "情報", "削除したいページを選択してください")
            return
        if self.pdf_manager.get_page_count() == 0:
            return

        self.pdf_manager.delete_pages(indices)
        self.thumbnail_panel.refresh()

        if self.pdf_manager.get_page_count() > 0:
            # Select the page that now occupies the position of the first deleted
            # page (or the last remaining page, if the tail was deleted).
            next_row = min(min(indices), self.pdf_manager.get_page_count() - 1)
            self.thumbnail_panel.setCurrentRow(next_row)
            current_item = self.thumbnail_panel.currentItem()
            if current_item:
                self._on_thumbnail_selected(current_item)
        else:
            self._clear_pdf_preview()

        self._mark_dirty()
        count = len(indices)
        self.statusBar().showMessage(f"{count}ページを削除しました" if count > 1 else "ページを削除しました")

    def undo_last_action(self):
        """Undo the most recent reorder/rotate/page-delete/file-close."""
        if self.current_mode != "pdf":
            return
        if not self.pdf_manager.undo():
            self.statusBar().showMessage("元に戻す操作がありません")
            return

        self.thumbnail_panel.refresh()
        if self.thumbnail_panel.count() > 0:
            first_page = self.thumbnail_panel.item(0)
            self.thumbnail_panel.setCurrentItem(first_page)
            self._on_thumbnail_selected(first_page)
        else:
            self._clear_pdf_preview()

        self._mark_dirty()
        self.statusBar().showMessage("元に戻しました")

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
        """Export current state (after reorder/rotate) as a new PDF, or overwrite the source."""
        if self.current_mode == "markdown":
            self._save_markdown_as_pdf()
            return

        if self.pdf_manager.get_page_count() == 0:
            QMessageBox.information(self, "情報", "保存する内容がありません")
            return

        if self.pdf_manager.can_overwrite_source():
            choice = self._ask_overwrite_or_save_as()
            if choice == "cancel":
                return
            if choice == "overwrite":
                self._overwrite_current_pdf()
                return
            # choice == "save_as": fall through to the normal Save As flow below

        self._save_pdf_as_new_file()

    def _ask_overwrite_or_save_as(self) -> str:
        """Ask whether to overwrite the currently open source file or save as a new
        file. Returns "overwrite", "save_as", or "cancel".
        """
        box = QMessageBox(self)
        box.setWindowTitle("保存方法の選択")
        box.setText("開いているファイルを上書き保存しますか？\nそれとも新しいファイルとして保存しますか？")
        overwrite_btn = box.addButton("上書き保存", QMessageBox.AcceptRole)
        save_as_btn = box.addButton("新規で保存", QMessageBox.ActionRole)
        box.addButton("キャンセル", QMessageBox.RejectRole)
        box.setDefaultButton(save_as_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked is overwrite_btn:
            return "overwrite"
        if clicked is save_as_btn:
            return "save_as"
        return "cancel"

    def _overwrite_current_pdf(self):
        def _do_overwrite():
            return self.pdf_manager.overwrite_source()

        def _on_overwritten(success):
            if success:
                self.thumbnail_panel.refresh()
                if self.thumbnail_panel.count() > 0:
                    first_page = self.thumbnail_panel.item(0)
                    self.thumbnail_panel.setCurrentItem(first_page)
                    self._on_thumbnail_selected(first_page)
                self.statusBar().showMessage("上書き保存しました")
                self._mark_clean()
            else:
                self.statusBar().showMessage("上書き保存に失敗しました")
                QMessageBox.warning(
                    self, "エラー",
                    "上書き保存に失敗しました。\nファイルが他のアプリで開かれていないか確認してください。"
                )

        self._run_in_background(_do_overwrite, _on_overwritten, busy_message="上書き保存しています...")

    def _save_pdf_as_new_file(self):
        default_path = str(Path(self._last_used_dir) / "edited.pdf") if self._last_used_dir else "edited.pdf"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "名前を付けて保存",
            default_path,
            "PDF Files (*.pdf)"
        )
        if not output_path:
            return
        self._remember_dir_from_path(output_path)

        def _do_save():
            return self.pdf_manager.save_as(Path(output_path))

        def _on_saved(success):
            if success:
                self.statusBar().showMessage(f"保存しました: {output_path}")
                QMessageBox.information(self, "完了", f"PDFを保存しました。\n{output_path}")
                self._mark_clean()
            else:
                self.statusBar().showMessage("PDFの保存に失敗しました")
                QMessageBox.warning(self, "エラー", f"PDFの保存に失敗しました。\n{output_path}")

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
        """Return list of page indices currently selected in the list, in visual order (delegates to panel)."""
        return self.thumbnail_panel.get_selected_page_indices()

    def _on_file_close_requested(self, path: Path):
        """Close an entire PDF file that was opened (right-click on any of its pages)."""
        if self.pdf_manager.close_document(path):
            # Block panel signals during refresh + selection to prevent any stale
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
                    # This bypasses list selection entirely to guarantee the old closed page's image is replaced.
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

                # Now set the selection (signals are blocked so it won't trigger preview update)
                if self.thumbnail_panel.count() > 0:
                    first_page_item = self.thumbnail_panel.item(0)
                    self.thumbnail_panel.setCurrentItem(first_page_item)

            finally:
                self.thumbnail_panel.blockSignals(False)

            self._mark_dirty()
            self.statusBar().showMessage(f"{path.name} を閉じました")
        else:
            QMessageBox.warning(self, "エラー", f"{path.name} のクローズに失敗しました")

    def _confirm_discard_pdf_changes(self, question: str) -> bool:
        """If there are unsaved PDF edits, ask the user before discarding them.

        Returns True if it's OK to proceed (no unsaved changes, or the user
        confirmed discarding them). Shared by closeEvent and opening a Markdown
        document (which also discards the current PDF session state).
        """
        if not self._is_dirty:
            return True
        reply = QMessageBox.question(
            self,
            "未保存の変更",
            question,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def closeEvent(self, event):
        """Confirm before closing if there are unsaved PDF edits."""
        if not self._confirm_discard_pdf_changes("保存されていない変更があります。終了しますか？"):
            event.ignore()
            return
        self._save_settings()
        event.accept()
