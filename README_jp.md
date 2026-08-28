# QuickMarkPDF

<p align="center">
  <img src="assets/quickmarkpdf-gui-ja.png" alt="QuickMarkPDF 日本語GUI" width="720">
</p>

無料、広告無し、寄付無し、課金無し。シンプルなWindowsデスクトップ向けPDFページ編集ツールです。分割・結合・並べ替え・回転・書き出しといった、必要最小限の編集に絞っています。おまけとして、Markdown（Mermaid図・数式（MathJax）対応）のプレビュー・PDF書き出しも備えています。

**現在のバージョンは v1.2.1 です。** `core/native/`（C++17 + WebView2版）が製品として出荷される版です。`python/prototype/`（PySide6版）は開発中の挙動評価に使う試作・評価用プロトタイプであり、配布はされません。詳細は[`document/about_jp.md`](document/about_jp.md)・[`document/environment_jp.md`](document/environment_jp.md)を参照してください。

画面は日本語／Englishを切替可能です（メニューバー右端のボタン）。英語版 README のスクリーンショットは同じウィンドウの日本語表示時のものです。

## 主な機能

- 複数PDFの読み込み・連結・分割・並べ替え・回転
- サムネイルのドラッグ&ドロップによる並べ替え（複数ファイルをまたいだ移動も可）
- プレビュー上のテキスト選択・コピー（既定で有効。右クリックメニューから画像切り出し用の範囲選択に切り替え可能）
- 選択/全ページをPDF切り出し、またはPNG/JPEG画像として書き出し（DPI・画質・クロップ範囲を指定可能）
- 元に戻す、未保存変更の確認保護
- Markdownプレビュー（Mermaid図・数式対応）、PDFへの書き出し

## 配布版を使う

実行だけなら GitHub Releases の ZIP を使います。`v*` タグで GitHub Actions が `QuickMarkPDF-binary.zip` を作ります。ZIP はリポジトリには置きません。

- [最新版の配布ページ](https://github.com/maktak-105/QuickMarkPDF/releases)
- [QuickMarkPDF v1.2.1](https://github.com/maktak-105/QuickMarkPDF/releases/tag/v1.2.1)
- [QuickMarkPDF-binary.zipを直接ダウンロード](https://github.com/maktak-105/QuickMarkPDF/releases/download/v1.2.1/QuickMarkPDF-binary.zip)

ZIPを展開すると、すべての配布ファイルが同じフォルダに入ります（`vendor/` は `index.html` の隣に置きます）。

- `QuickMarkPDF.exe` - GUI版（製品本体）
- `QuickMarkPDF_cli.exe` - 軽量な非GUIデモバイナリ（製品CLIではありません）
- `pdfium.dll` - PDF描画・編集エンジン
- `WebView2Loader.dll` - WebView2接続用ローダー
- `index.html` - GUI本体
- `vendor/` - Markdownプレビュー用の Mermaid.js と MathJax
- `readme.txt` / `readme_jp.txt` - 使用説明書
- `history.txt` / `history_jp.txt` - 更新履歴
- `LICENSE.txt` / `LICENSE_jp.txt` - MIT License

配布バイナリとチェックサムは GitHub Releases に掲載します。このリポジトリには置きません。

GUI版は`QuickMarkPDF.exe`を実行します。`QuickMarkPDF.exe`、`pdfium.dll`、`WebView2Loader.dll`、`index.html`、`vendor/` は必ず同じフォルダに置いてください。WebView2 Runtimeがない場合は、Microsoft Edge WebView2 Runtime (Evergreen)をインストールしてください。Windows 11には通常含まれていますが、Windows 10の古い環境、LTSC、Server、管理端末では追加導入が必要な場合があります。

## GUIの使い方

1. **開く**から、1つ以上のPDF、または単一の Markdown（`.md`）ファイルを選びます。1回の選択でPDFとMarkdownを混在させることはできません。
2. 左のサムネイルパネルでページを選択します（クリック / Ctrl+クリック / Shift+クリック）。ドラッグで並べ替えでき、ファイルをまたいだ移動もできます。
3. 回転・削除・PDF切り出し・画像出力はツールバーまたは右クリックメニューから行います。
4. PDFを1つだけ開いているときの**保存**は、上書きか名前を付けて保存かを選べます。複数PDFを開いているときは常に名前を付けて保存になり、開いている全ページが1つの新規PDFへ連結されます（元ファイルは変更されません）。これがPDFの結合方法でもあります。
5. `.md` を開くと Markdown プレビューに切り替わります（Mermaid / MathJax はオフラインで動作）。このモードの保存はプレビューをPDFへ書き出します。
6. **ヘルプ**に使い方とショートカット、**設定**にプレビューのホイール操作モードがあります。

キーボードショートカット: `Ctrl+O` 開く、`Delete` 選択ページを削除、`Ctrl+Z` 元に戻す、`Ctrl+S` 保存。

パスワード保護PDFや画像出力の詳細は[`dist/documents/readme_jp.txt`](dist/documents/readme_jp.txt)を参照してください。

## CLI

`QuickMarkPDF_cli.exe` はネイティブエンジンのページモデルを動かすデモであり、製品としてのコマンドライン版ではありません。

```powershell
.\QuickMarkPDF_cli.exe --help
.\QuickMarkPDF_cli.exe demo
```

## ネイティブ版のビルド

ネイティブ版はMinGW-w64のC++ツールチェーンを使用します。WinLibs（MCF threads、UCRT runtime）のWinGetパッケージで確認しています。

```powershell
winget install --id BrechtSanders.WinLibs.MCF.UCRT --exact --source winget
```

`build_native.py`は標準的なWinGetパッケージの場所を自動検索し、検出したコンパイラと同じフォルダの`windres.exe`も使うため、プロジェクトのビルドだけならPATH登録は不要です。

WebView2 SDKとPDFiumは`third_party/`（Git管理外）へ取得します。

```powershell
powershell -File scripts\fetch_webview2_sdk.ps1
powershell -File scripts\fetch_pdfium.ps1
python build_native.py
```

生成物（`dist/binary/`）: `QuickMarkPDF.exe`、`QuickMarkPDF_cli.exe`、`pdfium.dll`、`WebView2Loader.dll`、バンドル済み`index.html`、`vendor/`。

開発環境・テスト・QAの詳細は[`document/environment_jp.md`](document/environment_jp.md)、仕様は[`document/spec_jp.md`](document/spec_jp.md)を参照してください。

## 評価用プロトタイプ（Python）

PySide6版は製品ではありません。開発中にページ編集の挙動を比較するために残しています。

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python python/prototype/main.py
```

## ライセンス

MIT Licenseです。

`Copyright (c) 2026 maktak-105 (GitHub: https://github.com/maktak-105)`

英語原文は[`dist/documents/LICENSE.txt`](dist/documents/LICENSE.txt)、日本語参考訳は[`dist/documents/LICENSE_jp.txt`](dist/documents/LICENSE_jp.txt)を確認してください。

## 第三者ソフトウェア

出荷するGUIには次を同梱します。

- **PDFium**（`pdfium.dll`）— `third_party/pdfium/LICENSE` と `third_party/pdfium/licenses/`
- **Microsoft WebView2 Loader**（`WebView2Loader.dll`）— `third_party/webview2/LICENSE.txt`
- **Mermaid.js** — MIT（`resources/vendor/mermaid/LICENSE`）
- **MathJax** — Apache License 2.0（`resources/vendor/mathjax/LICENSE`）

WebView2 Runtime 自体は同梱しません。Windows 11（および多くの Windows 10）に含まれるか、別途インストールします。

## 注意事項

本ソフトウェアは現状有姿で提供されます。本ソフトウェアの使用、データ消失、システム障害、ハードウェア故障などについて作者は責任を負いません。重要なPDFは必ずバックアップしてから編集・書き出ししてください。

QuickMarkPDFは独立したソフトウェアであり、Adobe・Microsoftその他いかなるサードパーティのソフトウェアベンダーとも提携・承認関係にありません。

## 設計思想

世の中のPDFツールの多くは、広告収益前提の閲覧ソフト（有料版への誘導つき）か、逆に「数ページ切り出して1枚だけ回転したい」程度の作業には過剰な、機能てんこ盛りの文書統合スイートのどちらかに寄りがちです。QuickMarkPDFは、その中間を埋める小さく堅実なツールを目指しています。

- **ページ編集を直接的で分かりやすい操作にする**: 選択してドラッグで並べ替え、回転、切り出し——2クリックで済む作業に隠しプロジェクトファイルや多段ウィザードは要りません。
- **無料、広告無し、寄付無し、課金無し。テレメトリも無し**: やるべきことをやって、余計な自己主張はしません。
- **おまけでMD→PDF化もできます**: Mermaid/MathJaxを同梱することで、図や数式を含むメモも別ツールを用意せずそのままPDF化できます。
