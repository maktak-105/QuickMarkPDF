"""
PDF Editor - Main Entry Point
"""
import sys
from pathlib import Path

# Add project root to path so src imports work when running main.py directly
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from src.pdf_editor.ui.main_window import MainWindow


def resource_path(relative: str) -> Path:
    """Return absolute path to a bundled resource.
    Works both in dev (relative to project root) and in a PyInstaller EXE
    (relative to sys._MEIPASS, the temp-extraction directory).
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / relative


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
