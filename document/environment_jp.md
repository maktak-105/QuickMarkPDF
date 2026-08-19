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

PDFエンジンはPDFium（BSD-3、`bblanchon/pdfium-binaries`のビルド済みDLL）を使用します。MuPDFはAGPL/商用デュアルライセンスでMIT配布のEXEモデルと非互換のため不採用（詳細は `plans/2026-08-19_PDFエンジン選定_v1.0.md`）。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch_pdfium.ps1
```

```powershell
cmake -G "Visual Studio 17 2022" -A x64 -S core/webview2 -B core/webview2/build
cmake --build core/webview2/build --config Release
```

生成物は `core/webview2/build/Release/QuickMarkPDF_webview.exe` です。`pdfium.dll` は実行ファイルと同じフォルダへビルド時にコピーされ、`LoadLibraryW` で実行時に動的ロードされます。

`PdfBackend::inspect` は `FPDF_LoadMemDocument64` + `FPDF_GetPageCount` でページ数を取得します。`PdfBackend::save` は `WorkingDocument`(並べ替え・ファイル間移動・回転・削除)から `FPDF_ImportPagesByIndex` + `FPDFPage_SetRotation` + `FPDF_SaveAsCopy` で新規PDFを書き出します。パスワード付きソースで正しいパスワードがない場合は `PdfPasswordRequiredError` を送出します。`PdfBackend::render_page` はページを左上原点のRGBA8ピクセルへラスタライズします(`FPDFBitmap_Create` + `FPDF_RenderPageBitmap`、pdfium標準のBGRAからRGBAへ変換)。`host.cpp` は `render_page` WebMessageに対し、ピクセルをBase64化(`CryptBinaryToStringA`)した `page_rendered` を返し、`ui/app.js` が `atob` でデコードして `canvas` へ `ImageData` として描画します(ページ一覧のサムネイル)。クリックして拡大するプレビューペインはまだなく、サムネイル一覧のみ配線済みです。

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
