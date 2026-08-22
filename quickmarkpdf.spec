# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for QuickMarkPDF (python/ = spec-of-record PySide6 implementation).
One-folder mode (recommended for faster startup with PySide6 + PyMuPDF + QtWebEngine).

Recreated 2026-08-20: the original pdf_editor.spec (project name "PDF_Editor") was
deleted in commit 315b8a1 ("bootstrap C++ core migration") and never replaced, even
though document/environment.md still documents building via this file. This version
is updated for the current layout (entry point moved to python/main.py, package
gained ui/dialogs/).

Build:
  .venv\\Scripts\\pyinstaller.exe quickmarkpdf.spec --noconfirm

Output:
  dist/QuickMarkPDF/QuickMarkPDF.exe  +  dist/QuickMarkPDF/_internal/...
"""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# PySide6 / pymupdf pull in binaries/data files that hiddenimports alone won't catch.
extra_datas = []
extra_binaries = []
extra_hiddenimports = []
for _pkg in ("PySide6", "pymupdf"):
    try:
        _datas, _binaries, _hiddens = collect_all(_pkg)
        extra_datas += _datas
        extra_binaries += _binaries
        extra_hiddenimports += _hiddens
    except Exception:
        pass

a = Analysis(
    ["python/main.py"],
    pathex=["python"],
    binaries=extra_binaries,
    datas=[
        ("resources/icons/*.png", "resources/icons"),
        ("resources/app_icon.png", "resources"),
        ("resources/app_icon.ico", "resources"),
        ("resources/vendor/mermaid/*", "resources/vendor/mermaid"),
        ("resources/vendor/mathjax/*", "resources/vendor/mathjax"),
    ] + extra_datas,
    hiddenimports=[
        # PyMuPDF
        "fitz",
        "pymupdf",
        # PySide6 -- modules that sometimes get missed
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtPrintSupport",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "markdown",
        # src package (current layout as of 2026-08-20)
        "src.pdf_editor",
        "src.pdf_editor.markdown",
        "src.pdf_editor.markdown.markdown_manager",
        "src.pdf_editor.pdf",
        "src.pdf_editor.pdf.pdf_manager",
        "src.pdf_editor.ui",
        "src.pdf_editor.ui.main_window",
        "src.pdf_editor.ui.thumbnail_panel",
        "src.pdf_editor.ui.workers",
        "src.pdf_editor.ui.dialogs",
        "src.pdf_editor.ui.dialogs.export_dialog",
        "src.pdf_editor.ui.dialogs.preferences_dialog",
        "src.pdf_editor.utils",
        "src.pdf_editor.utils.resources",
    ] + extra_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unrelated heavy modules PyInstaller sometimes pulls in transitively.
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "IPython",
        "jupyter",
        "PIL._tkinter_finder",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # one-folder mode
    name="QuickMarkPDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX can conflict with PySide6/Qt binaries
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="resources/app_icon.ico",
)

# One-folder output: dist/QuickMarkPDF/QuickMarkPDF.exe + dist/QuickMarkPDF/_internal/
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="QuickMarkPDF",
)
