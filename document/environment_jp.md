# 開発環境

[English environment.md](environment.md)

## C++ WebView2版（最終構成）

- Windows 10/11（64-bit）
- Visual Studio 2022 Build Tools
- C++によるデスクトップ開発ワークロード
- Windows 10/11 SDK
- CMake 3.20以上
- WebView2 Runtime
- WebView2 SDK（NuGet: `Microsoft.Web.WebView2`）

SDKは `third_party/webview2/` に展開します。このフォルダはGit管理対象外です。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch_webview2_sdk.ps1
```

```powershell
cmake -G "Visual Studio 17 2022" -A x64 -S core/webview2 -B core/webview2/build
cmake --build core/webview2/build --config Release
```

生成物は `core/webview2/build/Release/QuickMarkPDF_webview.exe` です。

## 移行期間のPython版

- Windows 10/11（64-bit）

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
