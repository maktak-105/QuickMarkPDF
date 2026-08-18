# -*- mode: python ; coding: utf-8 -*-
r"""
PyInstaller spec for QuickMarkPDF
One-folder mode (recommended for faster startup with PySide6 + PyMuPDF)

Build:
  .venv\Scripts\pyinstaller.exe quickmarkpdf.spec
  (or: python -m PyInstaller quickmarkpdf.spec)

Output:
  dist/QuickMarkPDF/QuickMarkPDF.exe  +  dist/QuickMarkPDF/_internal/...
"""

import sys
from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_all
except ImportError:
    collect_all = None

block_cipher = None

# 強制的に PySide6 と pymupdf を丸ごと収集（hiddenimportsだけでは足りない場合がある）
extra_datas = []
extra_binaries = []
extra_hiddenimports = []
if collect_all:
    try:
        pyside_datas, pyside_binaries, pyside_hiddens = collect_all('PySide6')
        extra_datas += pyside_datas
        extra_binaries += pyside_binaries
        extra_hiddenimports += pyside_hiddens
    except Exception:
        pass

    try:
        pymupdf_datas, pymupdf_binaries, pymupdf_hiddens = collect_all('pymupdf')
        extra_datas += pymupdf_datas
        extra_binaries += pymupdf_binaries
        extra_hiddenimports += pymupdf_hiddens
    except Exception:
        pass

a = Analysis(
    ['python/main.py'],
    pathex=['python', '.'],
    binaries=extra_binaries,
    datas=[
        ('resources/icons/*.png', 'resources/icons'),
        ('resources/app_icon.png', 'resources'),
        ('resources/app_icon.ico', 'resources'),
        ('resources/vendor/mermaid/*', 'resources/vendor/mermaid'),
        ('resources/vendor/mathjax/*', 'resources/vendor/mathjax'),
    ] + extra_datas,
    hiddenimports=[
        # PyMuPDF
        'fitz',
        'pymupdf',
        # PySide6 — よく抜け落ちるモジュール
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtPrintSupport',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        # src パッケージ
        'markdown',
        'src.pdf_editor',
        'src.pdf_editor.markdown',
        'src.pdf_editor.markdown.markdown_manager',
        'src.pdf_editor.pdf',
        'src.pdf_editor.pdf.pdf_manager',
        'src.pdf_editor.ui',
        'src.pdf_editor.ui.main_window',
        'src.pdf_editor.ui.thumbnail_panel',
    ] + extra_hiddenimports,
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
    name='QuickMarkPDF',
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

# One-folder 出力（dist/QuickMarkPDF/ の中に exe + _internal フォルダができる）
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='QuickMarkPDF',
)
