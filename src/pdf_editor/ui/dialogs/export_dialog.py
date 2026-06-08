"""
Export pages as images (PNG / JPEG) dialog.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton,
    QLabel, QComboBox, QSpinBox, QSlider, QLineEdit, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt


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
        fmt = self.fmt_combo.currentData() or "png"
        return {
            "scope": scope,
            "format": fmt,
            "dpi": self._get_dpi(),
            "jpeg_quality": self.quality_slider.value(),
            "output_dir": self.dir_edit.text().strip() or str(Path.cwd()),
            "prefix": self.prefix_edit.text().strip() or "page",
        }
