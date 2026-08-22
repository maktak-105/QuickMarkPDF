"""
 QuickMarkPDF - Main Entry Point
"""
import logging
import sys
from pathlib import Path

# Add the Python source directory to the import path when running directly.
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QGuiApplication
from src.pdf_editor.ui.main_window import MainWindow
from src.pdf_editor.utils.resources import resource_path


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 高DPIディスプレイでのフォントぼやけ・かすれ対策
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)

    app = QApplication(sys.argv)
    app.setApplicationName("QuickMarkPDF")

    # ICO は複数サイズを含むため Windows タイトルバー・タスクバーとの相性が良い
    for icon_name in ("resources/app_icon.ico", "resources/app_icon.png"):
        icon_path = resource_path(icon_name)
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    window = MainWindow()
    window.show()

    # コマンドライン引数に対応ファイルがある場合、それを自動で開く
    if len(sys.argv) > 1:
        openable_files = []
        for arg in sys.argv[1:]:
            path = Path(arg)
            if path.exists() and path.suffix.lower() in {".pdf", ".md", ".markdown"}:
                openable_files.append(str(path))
        if openable_files:
            window.open_documents(openable_files)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
