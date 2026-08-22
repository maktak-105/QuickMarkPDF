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
    - Development: running python python/prototype/main.py from the project root
    - Frozen (PyInstaller one-folder): sys._MEIPASS points to the temp extraction dir
    """
    if getattr(sys, "_MEIPASS", None):
        # PyInstaller one-folder mode: resources are placed at the root of the bundle
        return Path(sys._MEIPASS)

    # Running from source.
    # This file lives at: <root>/python/prototype/src/pdf_editor/utils/resources.py
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "resources").exists() and (parent / "requirements.txt").exists():
            return parent

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
