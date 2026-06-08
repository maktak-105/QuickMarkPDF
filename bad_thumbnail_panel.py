"""
ThumbnailPanel (QTreeWidget version)
- Grouped by original PDF file (collapsible top-level items)
- Drag & drop reordering with animated insertion gap
"""
import logging
from pathlib import Path

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QStyledItemDelegate, QHeaderView, QStyle, QMenu
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QRect
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QIcon, QFont
from collections import defaultdict

from src.pdf_editor.pdf.pdf_manager import PDFManager

logger = logging.getLogger(__name__)

TEXT_H = 14        # pixels for page label strip at the bottom of each canvas
_INDENT = 20       # indentation (= expand button area width)
_PANEL_EXTRA = 24  # scrollbar + borders allowance


class _ThumbnailDelegate(QStyledItemDelegate):
    """
    Per-row sizing:
    - File headers: compact single line with 0.5-line padding
    - Page items:   exact canvas height (varies by page aspect ratio)
    Custom paint for page items bypasses iconSize() so landscape pages
    don't get padded to the full portrait height.
    """
    def __init__(self, icon_w: int, icon_h: int, parent=None):
        super().__init__(parent)
        self.icon_w = icon_w
        self.icon_h = icon_h  # maximum canvas height (portrait page)

    def sizeHint(self, option, index):
        if not index.parent().isValid():
            # File header: text height × 2  (0.5-line top pad + text + 0.5-line bottom pad)
            fh = option.fontMetrics.height()
            return QSize(self.icon_w + _INDENT + 2, fh * 2)
        # Page item: read the actual canvas height stored during refresh()
        canvas_h = index.data(Qt.UserRole + 1)
        h = canvas_h if canvas_h else self.icon_h
        return QSize(self.icon_w + _INDENT + 2, h + 1)

    def paint(self, painter, option, index):
        if not index.parent().isValid():
            # File headers use the default styled rendering (expand arrow + text)
            super().paint(painter, option, index)
            return

        # Selection highlight
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Draw the icon pixmap at its actual stored size (not stretched to iconSize)
        icon = index.data(Qt.DecorationRole)
        if icon and not icon.isNull():
            canvas_h = index.data(Qt.UserRole + 1) or self.icon_h
            pix = icon.pixmap(QSize(self.icon_w, canvas_h))
            if not pix.isNull():
                # Center horizontally within the item content rect
                x = option.rect.x() + max(0, (option.rect.width() - pix.width()) // 2)
                y = option.rect.y()
                painter.drawPixmap(x, y, pix)


class ThumbnailPanel(QTreeWidget):
    page_reordered = Signal(list)
    pdf_extract_requested = Signal(list)   # list of selected page indices for PDF cut-out
    image_extract_requested = Signal(list) # list of selected page indices for image export
    file_close_requested = Signal(Path)    # emit the source path of the file to close

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragDropMode(QTreeWidget.InternalMove)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setExpandsOnDoubleClick(True)
        self.setAnimated(False)

        self.pdf_manager: PDFManager | None = None
        self._current_size = "medium"

        # Insertion gap animation
        self._insert_parent = None
        self._insert_child_index = -1
        self._current_gap = 0
        self._target_gap = 0
        self._gap_timer = QTimer(self)
        self._gap_timer.timeout.connect(self._animate_gap)

        self._dragged_page_idx = -1
        self._delegate = None
        self._apply_size("medium")

        self.setUniformRowHeights(False)  # page items and file headers have different heights
        self.setVerticalScrollMode(QTreeWidget.ScrollPerPixel)
        self.setStyleSheet("""
            QTreeWidget {
                outline: 0;
            }
            QTreeWidget::item {
                padding: 0px 1px;
                margin: 0px;
                border: none;
            }
            QTreeWidget::item:selected {
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

        # rootIsDecorated=True (Qt default) makes child items indent by 2 × _INDENT.
        # Also reserve space for the vertical scrollbar so the icon never gets clipped.
        self._panel_width = w + 2 * _INDENT + 24  # child_indent(40) + scrollbar(17) + margin(7)

        self.setIconSize(QSize(w, h))
        self.setMinimumWidth(self._panel_width)

        self._delegate = _ThumbnailDelegate(w, h, self)
        self.setItemDelegate(self._delegate)

        self.setIndentation(_INDENT)
        # Ensure the single column always fills the viewport
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)

    def refresh(self):
        """Rebuild tree grouped by source file, preserving each file's expanded/collapsed state."""
        # Save expanded states keyed by file-path string
        expanded_states: dict[str, bool] = {
            self.topLevelItem(i).data(0, Qt.UserRole): self.topLevelItem(i).isExpanded()
            for i in range(self.topLevelItemCount())
            if self.topLevelItem(i).data(0, Qt.UserRole)
        }

        self.clear()
        if not self.pdf_manager or not self.pdf_manager.page_infos:
            return

        groups = defaultdict(list)
        for idx, info in enumerate(self.pdf_manager.page_infos):
            groups[info.source_doc_path].append((idx, info))

        for file_path, pages in groups.items():
            file_item = QTreeWidgetItem(self)
            file_item.setText(0, file_path.name)
            file_item.setData(0, Qt.UserRole, str(file_path))
            file_item.setFlags(file_item.flags() | Qt.ItemIsDropEnabled)

            for page_idx, info in pages:
                label = f"p.{info.original_page_index + 1}"
                pix = self._get_qpixmap_from_page(page_idx, label)

                child = QTreeWidgetItem(file_item)
                if pix and not pix.isNull():
                    child.setIcon(0, QIcon(pix))
                    child.setData(0, Qt.UserRole + 1, pix.height())  # canvas_h for sizeHint/paint
                child.setText(0, "")  # label is embedded in the thumbnail image
                child.setData(0, Qt.UserRole, page_idx)
                child.setFlags(child.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)

            # Restore expanded state; new files default to expanded
            file_item.setExpanded(expanded_states.get(str(file_path), True))

        self.setDragDropMode(QTreeWidget.InternalMove)

    def _get_qpixmap_from_page(self, idx: int, label: str = "") -> QPixmap:
        """
        Render a canvas for a single page:
        - Width  = icon_w (always)
        - Height = actual_scaled_image_height + TEXT_H  (portrait is taller, landscape is shorter)
        This ensures landscape pages don't have excess vertical whitespace.
        """
        if not self.pdf_manager:
            return QPixmap()

        w = self.iconSize().width()
        h = self.iconSize().height()
        max_img_h = h - TEXT_H  # cap so portrait pages stay within icon height

        fitz_pix = self.pdf_manager.get_thumbnail_pixmap(idx, max_size=max(w, max_img_h) + 30)
        if fitz_pix is None:
            return QPixmap()

        try:
            img_data = fitz_pix.tobytes("png")
            qimage = QImage.fromData(img_data, "PNG")
            raw_pix = QPixmap.fromImage(qimage)

            # Scale preserving aspect ratio, fitting within ((w-2) × max_img_h).
            # The -2 reserves 1px margin on each side so the border never touches
            # the canvas edge (landscape pages fill the full width otherwise).
            effective_w = w - 2
            scaled = raw_pix.scaled(QSize(effective_w, max_img_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)

            actual_img_h = scaled.height()
            canvas_h = actual_img_h + TEXT_H  # landscape pages → shorter canvas

            canvas = QPixmap(w, canvas_h)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)

            # Page image: top-aligned, 1px left margin, centered in remaining space
            x = 1 + (effective_w - scaled.width()) // 2
            painter.drawPixmap(x, 0, scaled)

            # Thin border around the page image (always within canvas bounds)
            painter.setPen(QPen(QColor("#888888"), 1))
            painter.drawRect(x, 0, scaled.width() - 1, actual_img_h - 1)

            # Page label in the bottom strip
            if label:
                lbl_font = QFont()
                lbl_font.setPointSize(7)
                painter.setFont(lbl_font)
                painter.setPen(QColor("#999999"))
                painter.drawText(QRect(0, actual_img_h, w, TEXT_H), Qt.AlignCenter, label)

            painter.end()
            return canvas
        except Exception:
            return QPixmap()

    # --- Drag & Drop with animated gap ---

    def dragEnterEvent(self, event):
        dragged = self.currentItem()
        if dragged and dragged.parent() is not None:
            self._dragged_page_idx = dragged.data(0, Qt.UserRole)
        else:
            self._dragged_page_idx = -1
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)

        pos = event.position().toPoint()
        target_item = self.itemAt(pos)

        if target_item is not None and target_item.parent() is not None:
            parent = target_item.parent()
            row = parent.indexOfChild(target_item)
            rect = self.visualItemRect(target_item)
            insert_idx = row + 1 if pos.y() > rect.center().y() else row
            self._insert_parent = parent
            self._insert_child_index = insert_idx
        else:
            parent, insert_idx = self._get_insertion_point(pos)
            self._insert_parent = parent
            self._insert_child_index = insert_idx

        self._target_gap = 22
        if not self._gap_timer.isActive():
            self._gap_timer.start(50)

        self.viewport().update()

    def dragLeaveEvent(self, event):
        self._insert_parent = None
        self._insert_child_index = -1
        self._target_gap = 0
        self._gap_timer.stop()
        self.viewport().update()
        super().dragLeaveEvent(event)

    def _animate_gap(self):
        if abs(self._current_gap - self._target_gap) < 1:
            self._current_gap = self._target_gap
            self._gap_timer.stop()
        else:
            self._current_gap += (self._target_gap - self._current_gap) * 0.35

        if self._insert_parent is not None:
            rect = self.visualItemRect(self._insert_parent)
            self.viewport().update(rect.adjusted(-10, -40, 10, 40))
        else:
            self.viewport().update()

    def dropEvent(self, event):
        super().dropEvent(event)

        # After Qt's InternalMove, we reconstruct the flat visual order from the tree.
        # This is fragile when files are collapsed or multi-file drag happens;
        # we have a safety fallback below.
        new_order = self._collect_flat_order()
        expected = self._get_total_page_count()

        if len(new_order) != expected:
            logger.warning("Drop produced inconsistent order length — falling back to no change")
            new_order = list(range(expected))

        self.page_reordered.emit(new_order)

        self._insert_parent = None
        self._insert_child_index = -1
        self._target_gap = 0
        self._current_gap = 0
        self.viewport().update()
        self._dragged_page_idx = -1

    def _collect_flat_order(self):
        order = []
        for i in range(self.topLevelItemCount()):
            file_item = self.topLevelItem(i)
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                idx = child.data(0, Qt.UserRole)
                if idx is not None:
                    order.append(idx)
        return order

    # --- Compatibility helpers for MainWindow ---

    def currentRow(self):
        item = self.currentItem()
        if item and item.parent() is not None:
            return item.data(0, Qt.UserRole)
        return -1

    def setCurrentRow(self, row):
        """Select the item with the given page index. Skips collapsed parents (no auto-expand)."""
        for i in range(self.topLevelItemCount()):
            f = self.topLevelItem(i)
            for j in range(f.childCount()):
                c = f.child(j)
                if c.data(0, Qt.UserRole) == row:
                    if f.isExpanded():
                        self.setCurrentItem(c)
                    return

    def count(self):
        total = 0
        for i in range(self.topLevelItemCount()):
            total += self.topLevelItem(i).childCount()
        return total

    def _get_total_page_count(self):
        if self.pdf_manager and self.pdf_manager.page_infos:
            return len(self.pdf_manager.page_infos)
        return self.count()

    def _get_insertion_point(self, pos):
        item = self.itemAt(pos)
        if item is None:
            if self.topLevelItemCount() > 0:
                last_file = self.topLevelItem(self.topLevelItemCount() - 1)
                return last_file, last_file.childCount()
            return None, 0

        if item.parent() is None:
            header_rect = self.visualItemRect(item)
            if pos.y() < header_rect.center().y():
                return item, 0
            else:
                return item, item.childCount()

        file_item = item.parent()
        row = file_item.indexOfChild(item)
        rect = self.visualItemRect(item)
        return file_item, row + 1 if pos.y() > rect.center().y() else row

    # --- Context menu & selection helpers for export etc. ---

    def _show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item or not self.pdf_manager or self.topLevelItemCount() == 0:
            return

        menu = QMenu(self)

        if item.parent() is None:
            # Right-clicked on a file header (top-level item)
            path_str = item.data(0, Qt.UserRole)
            if path_str:
                file_path = Path(path_str).resolve()
                close_label = f"「{item.text(0)}」を閉じる"
                close_act = menu.addAction(close_label)
                close_act.triggered.connect(lambda checked=False, p=file_path: self.file_close_requested.emit(p))
        else:
            # Right-clicked on a page item
            selected = self.get_selected_page_indices()
            # Two choices as requested: PDF cut-out or Image cut-out
            pdf_label = f"PDFを切り出し... ({len(selected)}ページ)" if selected else "PDFを切り出し..."
            img_label = f"画像を切り出し (PNG/JPG)... ({len(selected)}ページ)" if selected else "画像を切り出し (PNG/JPG)..."
            pdf_act = menu.addAction(pdf_label)
            pdf_act.triggered.connect(lambda: self.pdf_extract_requested.emit(selected))
            img_act = menu.addAction(img_label)
            img_act.triggered.connect(lambda: self.image_extract_requested.emit(selected))

        if menu.actions():
            menu.exec(self.viewport().mapToGlobal(pos))

    def get_selected_page_indices(self) -> list[int]:
        """Return currently selected page indices in visual (tree) order. Supports multi-select."""
        selected = []
        for i in range(self.topLevelItemCount()):
            file_item = self.topLevelItem(i)
            for j in range(file_item.childCount()):
                child = file_item.child(j)
                if child.isSelected():
                    idx = child.data(0, Qt.UserRole)
                    if idx is not None:
                        selected.append(idx)
        return selected
