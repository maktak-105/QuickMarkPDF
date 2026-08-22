"""
Application preferences dialog.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton, QPushButton
)


class PreferencesDialog(QDialog):
    """Dialog for app-wide preferences, persisted via QSettings by the caller."""

    def __init__(self, parent=None, wheel_mode: str = "zoom"):
        super().__init__(parent)
        self.setWindowTitle("環境設定")
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)

        # ── マウスホイール操作 ─────────────────────────
        wheel_box = QGroupBox("プレビューでのマウスホイール操作")
        wl = QVBoxLayout(wheel_box)
        self.wheel_zoom = QRadioButton("拡大・縮小（既定）　※右ドラッグでパン")
        self.wheel_scroll = QRadioButton("縦スクロール　※右ドラッグで拡大・縮小（下=拡大／上=縮小）")
        if wheel_mode == "scroll":
            self.wheel_scroll.setChecked(True)
        else:
            self.wheel_zoom.setChecked(True)
        wl.addWidget(self.wheel_zoom)
        wl.addWidget(self.wheel_scroll)
        root.addWidget(wheel_box)

        # ── Buttons ─────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def get_settings(self) -> dict:
        return {"wheel_mode": "scroll" if self.wheel_scroll.isChecked() else "zoom"}
