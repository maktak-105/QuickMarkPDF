# QuickMarkPDF

[English README.md](README.md)

<p align="center">
  <img src="assets/quickmarkpdf-gui-ja.png" alt="QuickMarkPDF 日本語GUI" width="720">
</p>

Windows向けのシンプルなデスクトップPDF編集ツールです。[`python/`](python/) 配下のPython/PySide6版が仕様の正です。以前試みたC++/WebView2バックエンドへの移植は中止しました。経緯は[`CPP_PORT_POSTMORTEM.md`](CPP_PORT_POSTMORTEM.md)、同じ失敗を繰り返さないための自動テストプログラム(ネイティブダイアログでテスト実行が止まらない仕組み)については[`document/environment_jp.md`](document/environment_jp.md)を参照してください。

**リポジトリ構成は共通テンプレート`___appli-template`(ワークスペース内の別リポジトリ、QuickFolderSize/QuickDiskBenchと同じ)に従います** — 正式なフォルダ構成ルールは[`01_フォルダ構成.md`](../___appli-template/01_フォルダ構成.md)を参照してください。本リポジトリは現在、同テンプレートの「Python版（PyInstaller配布）」構成に従っています。

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

詳細は [`document/environment_jp.md`](document/environment_jp.md) を参照してください。

## ビルド

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

生成物は `dist/QuickMarkPDF/` に作成されます。`QuickMarkPDF.exe` と `_internal` フォルダは同じ場所に置いてください。

## テスト

```powershell
python -m pip install -r requirements-dev.txt
python run_tests.py
```

自動テストプログラム一式(単体・結合・見た目・所要時間)を実行し、
`tests/reports/summary.md` にレポートを出力します。テストの階層構成、
ネイティブダイアログガードの仕組み、実画面階層(オプトイン)の実行方法は
[`document/environment_jp.md`](document/environment_jp.md#自動テスト) を参照してください。

## ライセンス

MIT Licenseです。英語原文は [`LICENSE`](LICENSE)、配布用文書は [`dist/documents/LICENSE.txt`](dist/documents/LICENSE.txt) を参照してください。

## 設計思想

- ページ単位のPDF編集を、直接的で分かりやすい操作にする。
- Markdownプレビューの資産を同梱し、オフラインでも利用できるようにする。
- 複雑な文書統合環境ではなく、堅実なWindowsデスクトップツールを目指す。

## 注意事項

本ソフトウェアは現状有姿で提供されます。重要なPDFは必ずバックアップしてから操作してください。
