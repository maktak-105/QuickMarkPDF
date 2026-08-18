"""
ThumbnailPanel (QListWidget version)
- Flat list, one row per page (no per-file grouping — every page carries its
  own filename tag baked into its thumbnail, so the tag travels with it on
  any drag/reorder without needing to "re-parent" into anything)
- Drag & drop reordering with animated insertion gap
"""
import logging

from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle, QMenu
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QRect
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QIcon, QFont

from src.pdf_editor.pdf.pdf_manager import PDFManager
from pathlib import Path

logger = logging.getLogger(__name__)

TAG_H = 14          # pixels for the filename tag strip at the top of each canvas
TEXT_H = 14          # pixels for the "p.N" label strip at the bottom of each canvas
NUM_GUTTER_W = 28    # left margin column showing the page's position in the whole document
_PANEL_EXTRA = 24    # scrollbar + borders allowance


class _ThumbnailDelegate(QStyledItemDelegate):
    """Custom paint bypasses iconSize() so landscape pages don't get padded
    to the full portrait height — sizeHint() reads the actual stored canvas
    height per item instead.
    """
    def __init__(self, icon_w: int, icon_h: int, parent=None):
        super().__init__(parent)
        self.icon_w = icon_w
        self.icon_h = icon_h  # maximum canvas height (portrait page)

    def sizeHint(self, option, index):
        canvas_h = index.data(Qt.UserRole + 1)
        h = canvas_h if canvas_h else self.icon_h
        return QSize(NUM_GUTTER_W + self.icon_w + 2, h + 1)

    def paint(self, painter, option, index):
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        icon = index.data(Qt.DecorationRole)
        if icon and not icon.isNull():
            canvas_h = index.data(Qt.UserRole + 1) or self.icon_h
            pix = icon.pixmap(QSize(NUM_GUTTER_W + self.icon_w, canvas_h))
            if not pix.isNull():
                x = option.rect.x() + max(0, (option.rect.width() - pix.width()) // 2)
                y = option.rect.y()
                painter.drawPixmap(x, y, pix)


class ThumbnailPanel(QListWidget):
    page_reordered = Signal(list, list)  # (new_order, moved_old_indices)
    pdf_extract_requested = Signal(list)   # list of selected page indices for PDF cut-out
    image_extract_requested = Signal(list) # list of selected page indices for image export
    file_close_requested = Signal(Path)    # emit the source path of the file to close
    page_delete_requested = Signal(list)   # list of selected page indices to delete
    page_rotate_requested = Signal(list, int)  # (selected page indices, degrees)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setSelectionMode(QListWidget.ExtendedSelection)

        self.pdf_manager: PDFManager | None = None
        self._current_size = "medium"

        # Insertion row tracked during drag; the actual reorder is computed
        # from this (not from Qt's native post-drop list state — see dropEvent).
        self._insert_row = -1
        self._current_gap = 0
        self._target_gap = 0
        self._gap_timer = QTimer(self)
        self._gap_timer.timeout.connect(self._animate_gap)

        self._dragged_indices: list[int] = []
        self._delegate = None
        self._apply_size("medium")

        self.setUniformItemSizes(False)  # pages vary in canvas height by aspect ratio
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setStyleSheet("""
            QListWidget {
                outline: 0;
            }
            QListWidget::item {
                padding: 0px 1px;
                margin: 0px;
                border: none;
            }
            QListWidget::item:selected {
                background: #3a6ea5;
            }
        """)

        # Context menu for quick export etc.
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_pdf_manager(self, manager: PDFManager):
        self.pdf_manager = manager

    def set_thumbnail_size(self, size: str):
        if size not in ("small", "medium", "large"):
            size = "medium"
        if size == self._current_size:
            return
        self._current_size = size
        self._apply_size(size)
        self.refresh()

    def _apply_size(self, size: str):
        if size == "small":
            w, h = 80, 105
        elif size == "large":
            w, h = 200, 260
        else:
            w, h = 120, 155

        # Reserve space for the vertical scrollbar so the icon never gets clipped.
        self._panel_width = NUM_GUTTER_W + w + _PANEL_EXTRA

        self.setIconSize(QSize(NUM_GUTTER_W + w, h))
        self.setMinimumWidth(self._panel_width)

        self._delegate = _ThumbnailDelegate(w, h, self)
        self.setItemDelegate(self._delegate)

    def refresh(self):
        """Rebuild the flat page list."""
        self.clear()
        if not self.pdf_manager or not self.pdf_manager.page_infos:
            return

        total = len(self.pdf_manager.page_infos)
        for page_idx, info in enumerate(self.pdf_manager.page_infos):
            doc_page_no = page_idx + 1  # this page's position in the whole (merged) document
            pix = self._get_qpixmap_from_page(page_idx, info, doc_page_no)

            item = QListWidgetItem()
            if pix and not pix.isNull():
                item.setIcon(QIcon(pix))
                item.setData(Qt.UserRole + 1, pix.height())  # canvas_h for sizeHint/paint
            item.setData(Qt.UserRole, page_idx)
            item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
            self.addItem(item)

    def _get_qpixmap_from_page(self, idx: int, info, doc_page_no: int) -> QPixmap:
        """
        Render one row's canvas:
        - Left column (NUM_GUTTER_W wide): the page's position in the whole document.
        - Right column (icon_w wide), top to bottom: filename tag / page image / original page number.
        Height = actual_scaled_image_height + TAG_H + TEXT_H (landscape pages stay compact).
        """
        if not self.pdf_manager:
            return QPixmap()

        icon_size = self.iconSize()
        w = icon_size.width() - NUM_GUTTER_W
        h = icon_size.height()
        max_img_h = h - TAG_H - TEXT_H  # cap so portrait pages stay within icon height

        fitz_pix = self.pdf_manager.get_thumbnail_pixmap(idx, max_size=max(w, max_img_h) + 30)
        if fitz_pix is None:
            return QPixmap()

        try:
            img_data = fitz_pix.tobytes("png")
            qimage = QImage.fromData(img_data, "PNG")
            raw_pix = QPixmap.fromImage(qimage)

            # Scale preserving aspect ratio, fitting within ((w-2) × max_img_h).
            effective_w = w - 2
            scaled = raw_pix.scaled(QSize(effective_w, max_img_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)

            actual_img_h = scaled.height()
            canvas_h = TAG_H + actual_img_h + TEXT_H

            canvas = QPixmap(NUM_GUTTER_W + w, canvas_h)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)

            # Document-wide page number, vertically centered in the left gutter
            num_font = QFont()
            num_font.setPointSize(8)
            painter.setFont(num_font)
            painter.setPen(QColor("#777777"))
            painter.drawText(QRect(0, 0, NUM_GUTTER_W, canvas_h), Qt.AlignCenter, str(doc_page_no))

            # Filename tag (top strip)
            tag_font = QFont()
            tag_font.setPointSize(7)
            painter.setFont(tag_font)
            painter.setPen(QColor("#5b9bd5"))
            tag_metrics = painter.fontMetrics()
            tag_text = tag_metrics.elidedText(info.source_doc_path.name, Qt.ElideMiddle, w - 2)
            painter.drawText(QRect(NUM_GUTTER_W, 0, w, TAG_H), Qt.AlignCenter, tag_text)

            # Page image: top-aligned below the tag, 1px left margin, centered in remaining space
            x = NUM_GUTTER_W + 1 + (effective_w - scaled.width()) // 2
            y = TAG_H
            painter.drawPixmap(x, y, scaled)

            # Thin border around the page image
            painter.setPen(QPen(QColor("#888888"), 1))
            painter.drawRect(x, y, scaled.width() - 1, actual_img_h - 1)

            # Original page number (bottom strip)
            lbl_font = QFont()
            lbl_font.setPointSize(7)
            painter.setFont(lbl_font)
            painter.setPen(QColor("#999999"))
            label = f"p.{info.original_page_index + 1}"
            painter.drawText(QRect(NUM_GUTTER_W, TAG_H + actual_img_h, w, TEXT_H), Qt.AlignCenter, label)

            painter.end()
            return canvas
        except Exception:
            return QPixmap()

    # --- Drag & Drop ---
    #
    # The actual reorder is always computed by us, from `_insert_row` tracked
    # during dragMoveEvent — never by reading back Qt's own post-drop list
    # state. Letting Qt's native InternalMove actually move items was the root
    # cause of unreliable reordering in the previous (QTreeWidget) version. We
    # still call `super().dragMoveEvent()` for its native drop-indicator-line
    # visual, but deliberately do NOT call `super().dropEvent()`.

    def dragEnterEvent(self, event):
        # Drag whatever is currently selected (supports multi-select drags).
        self._dragged_indices = sorted(set(self.get_selected_page_indices()))
        if not self._dragged_indices:
            dragged = self.currentItem()
            if dragged is not None:
                self._dragged_indices = [dragged.data(Qt.UserRole)]

        if self._dragged_indices:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._dragged_indices:
            event.ignore()
            return

        super().dragMoveEvent(event)  # native drop-indicator-line visual only

        pos = event.position().toPoint()
        self._insert_row = self._get_insertion_row(pos)

        event.acceptProposedAction()

        self._target_gap = 22
        if not self._gap_timer.isActive():
            self._gap_timer.start(50)

        self.viewport().update()

    def dragLeaveEvent(self, event):
        self._reset_drag_state()
        super().dragLeaveEvent(event)

    def _animate_gap(self):
        if abs(self._current_gap - self._target_gap) < 1:
            self._current_gap = self._target_gap
            self._gap_timer.stop()
        else:
            self._current_gap += (self._target_gap - self._current_gap) * 0.35
        self.viewport().update()

    def dropEvent(self, event):
        if not self._dragged_indices or self._insert_row < 0:
            event.ignore()
            self._reset_drag_state()
            return

        new_order = self._compute_new_order(self._dragged_indices, self._insert_row)
        expected = self._get_total_page_count()
        if len(new_order) != expected:
            logger.warning("Computed reorder has unexpected length — falling back to no change")
            new_order = list(range(expected))

        dragged_indices = self._dragged_indices  # capture before _reset_drag_state clears it
        event.acceptProposedAction()
        self._reset_drag_state()

        # Defer emitting until after Qt's own drag-and-drop event processing has
        # fully unwound. MainWindow's handler calls refresh(), which clears and
        # rebuilds this entire list (destroying every QListWidgetItem) — doing
        # that SYNCHRONOUSLY from within dropEvent() mutates the view out from
        # under Qt's still-active internal DnD bookkeeping for this same event,
        # which produced erratic results (a seemingly random page missing from
        # view, different each time). Scheduling the emit for the next event
        # loop iteration lets the drop finish cleanly first.
        QTimer.singleShot(0, lambda: self.page_reordered.emit(new_order, dragged_indices))

    def _reset_drag_state(self):
        self._insert_row = -1
        self._target_gap = 0
        self._current_gap = 0
        self._gap_timer.stop()
        self._dragged_indices = []
        self.viewport().update()

    def _collect_flat_order(self) -> list[int]:
        """Read the current page order from the list (unmodified by us during
        drag, so this always matches pdf_manager.page_infos order).
        """
        order = []
        for i in range(self.count()):
            idx = self.item(i).data(Qt.UserRole)
            if idx is not None:
                order.append(idx)
        return order

    def _compute_new_order(self, dragged_indices: list[int], insert_row: int) -> list[int]:
        """Compute the new flat page order: move `dragged_indices` (old flat
        indices, in their original relative order) to the given row position.
        """
        current_order = self._collect_flat_order()
        dragged_set = set(dragged_indices)
        target_pos = min(insert_row, len(current_order))

        remaining = []
        removed_before_target = 0
        for i, page_idx in enumerate(current_order):
            if page_idx in dragged_set:
                if i < target_pos:
                    removed_before_target += 1
                continue
            remaining.append(page_idx)

        insert_at = target_pos - removed_before_target
        insert_at = max(0, min(insert_at, len(remaining)))

        dragged_in_order = [idx for idx in current_order if idx in dragged_set]
        return remaining[:insert_at] + dragged_in_order + remaining[insert_at:]

    # --- Compatibility helpers for MainWindow ---

    def currentRow(self):
        """The page index (not list row) of the current item, or -1.
        Overrides QListWidget.currentRow() — MainWindow only ever wants the
        page index, never the raw list position (the two coincide today since
        rows are 1:1 with pages, but callers should rely on this, not that).
        """
        item = self.currentItem()
        if item is not None:
            return item.data(Qt.UserRole)
        return -1

    def setCurrentRow(self, row):
        """Select the item with the given page index."""
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) == row:
                self.setCurrentItem(item)
                return

    def set_selected_page_indices(self, rows: list[int]):
        """Select (highlight) all items whose page index is in `rows`, in addition to
        setting the current item to the first one.
        """
        if not rows:
            return
        rows_set = set(rows)
        first_item = None
        for i in range(self.count()):
            item = self.item(i)
            idx = item.data(Qt.UserRole)
            if idx in rows_set:
                item.setSelected(True)
                if idx == rows[0]:
                    first_item = item
        if first_item is not None:
            self.setCurrentItem(first_item)

    def _get_total_page_count(self):
        if self.pdf_manager and self.pdf_manager.page_infos:
            return len(self.pdf_manager.page_infos)
        return self.count()

    def _get_insertion_row(self, pos) -> int:
        item = self.itemAt(pos)
        if item is None:
            return self.count()
        row = self.row(item)
        rect = self.visualItemRect(item)
        return row + 1 if pos.y() > rect.center().y() else row

    # --- Context menu & selection helpers for export etc. ---

    def _show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item or not self.pdf_manager or self.count() == 0:
            return

        page_idx = item.data(Qt.UserRole)
        if page_idx is None or not (0 <= page_idx < len(self.pdf_manager.page_infos)):
            return

        menu = QMenu(self)
        selected = self.get_selected_page_indices()

        pdf_label = f"PDFを切り出し... ({len(selected)}ページ)" if selected else "PDFを切り出し..."
        img_label = f"画像を切り出し (PNG/JPG)... ({len(selected)}ページ)" if selected else "画像を切り出し (PNG/JPG)..."
        pdf_act = menu.addAction(pdf_label)
        pdf_act.triggered.connect(lambda: self.pdf_extract_requested.emit(selected))
        img_act = menu.addAction(img_label)
        img_act.triggered.connect(lambda: self.image_extract_requested.emit(selected))

        menu.addSeparator()
        rotate_menu = menu.addMenu("回転")
        for rotate_label, degrees in (("右90°", 90), ("左90°", -90), ("180°", 180)):
            rotate_act = rotate_menu.addAction(rotate_label)
            rotate_act.triggered.connect(
                lambda checked=False, d=degrees: self.page_rotate_requested.emit(selected, d)
            )

        menu.addSeparator()
        del_label = f"ページを削除 ({len(selected)}ページ)" if selected else "ページを削除"
        del_act = menu.addAction(del_label)
        del_act.triggered.connect(lambda: self.page_delete_requested.emit(selected))

        menu.addSeparator()
        file_path = self.pdf_manager.page_infos[page_idx].source_doc_path
        close_label = f"「{file_path.name}」を閉じる"
        close_act = menu.addAction(close_label)
        close_act.triggered.connect(lambda checked=False, p=file_path: self.file_close_requested.emit(p))

        if menu.actions():
            menu.exec(self.viewport().mapToGlobal(pos))

    def get_selected_page_indices(self) -> list[int]:
        """Return currently selected page indices in visual (list) order. Supports multi-select."""
        selected = []
        for i in range(self.count()):
            item = self.item(i)
            if item.isSelected():
                idx = item.data(Qt.UserRole)
                if idx is not None:
                    selected.append(idx)
        return selected
