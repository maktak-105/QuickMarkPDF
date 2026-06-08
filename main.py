"""
PDF Editor - Main Entry Point
"""
import sys
import logging
from pathlib import Path

# Add project root to path so src imports work when running main.py directly
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from src.pdf_editor.ui.main_window import MainWindow
from src.pdf_editor.utils.resources import resource_path

# シンプルなログ設定（開発時はコンソール、将来的にファイル出力も容易）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pdf_editor")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Editor")

    # ICO は複数サイズを含むため Windows タイトルバー・タスクバーとの相性が良い
    for icon_name in ("resources/app_icon.ico", "resources/app_icon.png"):
        icon_path = resource_path(icon_name)
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
