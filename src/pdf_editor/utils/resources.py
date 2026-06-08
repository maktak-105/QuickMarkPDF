"""
Resource path utilities for dev and PyInstaller frozen builds.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def get_project_root() -> Path:
    """Return the absolute path to the project root.

    Works in:
    - Development: running python main.py from project root
    - Frozen (PyInstaller one-folder): sys._MEIPASS points to the temp extraction dir
    """
    if getattr(sys, "_MEIPASS", None):
        # PyInstaller one-folder mode: resources are placed at the root of the bundle
        return Path(sys._MEIPASS)

    # Running from source.
    # This file lives at: <root>/src/pdf_editor/utils/resources.py
    # parents[0]=resources.py dir, [1]=utils, [2]=pdf_editor, [3]=src, [4]=project root
    current = Path(__file__).resolve()
    root = current.parents[3]

    # Sanity check: prefer the layout that has resources/ or main.py
    if (root / "resources").exists() or (root / "main.py").exists():
        return root

    # Last resort fallback
    return Path.cwd()


def resource_path(relative: str) -> Path:
    """Return absolute path to a resource relative to the project root.

    Example:
        resource_path("resources/app_icon.ico")
        resource_path("resources/icons/open.png")
    """
    return get_project_root() / relative


def get_icon(name: str) -> QIcon:
    """Load a toolbar / action icon from resources/icons/.

    Returns an empty QIcon if the file does not exist (graceful fallback).
    """
    icon_file = resource_path(f"resources/icons/{name}.png")
    if icon_file.exists():
        return QIcon(str(icon_file))
    return QIcon()
