# QuickMarkPDF

[English README.md](README.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-ja.png" alt="QuickMarkPDF 日本語GUI" width="720">
</p>

Windows向けのシンプルなデスクトップPDF編集ツールです。最終版はC++バックエンド＋WebView2 GUIで構成し、移行期間中はPython/PySide6版を動作仕様の比較対象として残します。

**リポジトリ構成は共通テンプレート`___appli-template`(ワークスペース内の別リポジトリ、QuickFolderSize/QuickDiskBenchと同じ)に従います** — 正式なフォルダ構成ルールは[`01_フォルダ構成.md`](../___appli-template/01_フォルダ構成.md)を参照してください(`core/native/`にWebView2ホスト含む全ネイティブコードを配置、`templates/`+`static/`が開発用UIソースで`bundle_html.py`がバンドル、`dist/binary/`がGit管理外のビルド出力、`build_native.py`+`build.bat`でビルド)。本プロジェクトはこの構成への移行途中です。まだ準拠していない箇所(CMakeビルドの残存など)は既知のギャップであり、目標構成ではありません。

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

## C++/WebView2版の開発

C++17のネイティブコアは `core/native/` にあります(WebView2ホストも同じフォルダ)。MinGW-w64のg++でビルドします(MSVC/Visual Studioは不要)。[`document/environment_jp.md`](document/environment_jp.md)の手順でWebView2 SDKとPDFiumを`third_party/`へ取得してからビルドします。

```powershell
python build_native.py
# または: build.bat
```

`templates/`+`static/`を自己完結HTML(`dist/binary/index.html`)へバンドルし、`dist/binary/QuickMarkPDF.exe`と`QuickMarkPDF_cli.exe`をビルド、必要なDLLをコピーし、最後に`core/native/engine_tests.cpp`をコンパイル・実行してビルド時チェックとします。`dist/binary/`はそのまま実行できるフラット構成になります。詳細は [`plans/2026-08-18_C++移植_v1.0.md`](plans/2026-08-18_C++移植_v1.0.md) を参照してください。

## ライセンス

MIT Licenseです。英語原文は [`LICENSE`](LICENSE)、配布用文書は [`dist/documents/LICENSE.txt`](dist/documents/LICENSE.txt) を参照してください。

## 設計思想

- ページ単位のPDF編集を、直接的で分かりやすい操作にする。
- Markdownプレビューの資産を同梱し、オフラインでも利用できるようにする。
- 複雑な文書統合環境ではなく、堅実なWindowsデスクトップツールを目指す。

## 注意事項

本ソフトウェアは現状有姿で提供されます。重要なPDFは必ずバックアップしてから操作してください。
