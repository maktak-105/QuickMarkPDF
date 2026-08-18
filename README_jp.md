# QuickMarkPDF

[English README.md](README.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-ja.png" alt="QuickMarkPDF 日本語GUI" width="720">
</p>

Windows向けのシンプルなデスクトップPDF編集ツールです。最終版はC++バックエンド＋WebView2 GUIで構成し、移行期間中はPython/PySide6版を動作仕様の比較対象として残します。

## 主な機能

- 複数PDFの読み込み・連結・分割
- ページのドラッグ＆ドロップによる並べ替え
- ページ単位の回転
- Markdown、Mermaid、数式のプレビューとPDF保存

## 開発環境

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python python/main.py
```

詳細は [`document/environment_jp.md`](document/environment_jp.md) と [`document/spec_jp.md`](document/spec_jp.md) を参照してください。

## ビルド

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

生成物は `dist/QuickMarkPDF/` に作成されます。`QuickMarkPDF.exe` と `_internal` フォルダは同じ場所に置いてください。

## C++版の開発

C++17のネイティブコアは `core/native/` にあります。MinGWとCMakeを使ってビルドできます。

```powershell
cmake -G "MinGW Makefiles" -S core/native -B core/native/build
cmake --build core/native/build --config Release
.\core\native\build\QuickMarkPDF_cli.exe demo
ctest --test-dir core/native/build --output-on-failure
```

現時点のCLIはPDFエンジンに依存しないページモデルの検証用です。PDF読み込み・保存とGUIは段階的に移植します。詳細は [`plans/2026-08-18_C++移植_v1.0.md`](plans/2026-08-18_C++移植_v1.0.md) を参照してください。

## WebView2版の開発

Visual Studio 2022 Build ToolsのC++ワークロードを導入し、[`document/environment_jp.md`](document/environment_jp.md)の手順でWebView2 SDKを取得してからビルドします。

```powershell
cmake -G "Visual Studio 17 2022" -A x64 -S core/webview2 -B core/webview2/build
cmake --build core/webview2/build --config Release
```

生成物は `core/webview2/build/Release/QuickMarkPDF_webview.exe` です。現在はHTML UIの表示とC++↔JavaScriptメッセージ連携まで実装済みで、PDF操作を順次接続します。

## ライセンス

MIT Licenseです。英語原文は [`LICENSE`](LICENSE)、配布用文書は [`dist/documents/LICENSE.txt`](dist/documents/LICENSE.txt) を参照してください。

## 設計思想

- ページ単位のPDF編集を、直接的で分かりやすい操作にする。
- Markdownプレビューの資産を同梱し、オフラインでも利用できるようにする。
- 複雑な文書統合環境ではなく、堅実なWindowsデスクトップツールを目指す。

## 注意事項

本ソフトウェアは現状有姿で提供されます。重要なPDFは必ずバックアップしてから操作してください。
