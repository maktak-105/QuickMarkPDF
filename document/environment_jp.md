# 開発環境

[English environment.md](environment.md)

## 必要なもの

- Windows 10/11（64-bit）
- Python 3.12以上
- PySide6 6.7以上
- PyMuPDF 1.24以上
- Pillow 10.0以上
- PyInstaller 6.0以上

## セットアップ

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## 起動

```powershell
python python/main.py
```

PDF、Markdown、またはMarkdown PDFを引数に渡すと、起動時に開けます。

## 配布ビルド

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

出力先は `dist/QuickMarkPDF/` です。
