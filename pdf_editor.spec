# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for PDF Editor
Run:  .venv\Scripts\pyinstaller.exe pdf_editor.spec
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDF_Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX は PySide6 と相性が悪いことがあるので無効
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # GUIアプリなのでコンソールウィンドウを非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/app_icon.ico',
)
