# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for PDF Editor
One-folder mode (recommended for faster startup with PySide6 + PyMuPDF)

Build:
  .venv\Scripts\pyinstaller.exe pdf_editor.spec
  (or: python -m PyInstaller pdf_editor.spec)

Output:
  dist/PDF_Editor/PDF_Editor.exe  +  dist/PDF_Editor/_internal/...
"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('resources/icons/*.png', 'resources/icons'),
        ('resources/app_icon.png', 'resources'),
        ('resources/app_icon.ico', 'resources'),
    ],
    hiddenimports=[
        # PyMuPDF
        'fitz',
        'pymupdf',
        # PySide6 — よく抜け落ちるモジュール
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtPrintSupport',
        # src パッケージ
        'src.pdf_editor',
        'src.pdf_editor.pdf',
        'src.pdf_editor.pdf.pdf_manager',
        'src.pdf_editor.ui',
        'src.pdf_editor.ui.main_window',
        'src.pdf_editor.ui.thumbnail_panel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不要な大きなモジュールを除外してサイズ削減
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'PIL._tkinter_finder',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # One-folder モード用（起動高速化）
    name='PDF_Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX は PySide6 と相性が悪いことがあるので無効
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # GUIアプリなのでコンソールウィンドウを非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/app_icon.ico',
)

# One-folder 出力（dist/PDF_Editor/ の中に exe + _internal フォルダができる）
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PDF_Editor',
)
