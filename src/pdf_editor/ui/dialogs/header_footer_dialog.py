"""
Header / Footer configuration dialog.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
    QLineEdit, QLabel, QRadioButton, QButtonGroup, QPushButton
)


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
