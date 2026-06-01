"""
PDF Editor - Main Entry Point
"""
import sys
from pathlib import Path

# Add project root to path so src imports work when running main.py directly
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from src.pdf_editor.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Editor")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
