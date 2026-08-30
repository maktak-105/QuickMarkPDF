# 開発環境

## 現状（まずここを読む）

`core/native/`（C++17 + WebView2）が**製品として出荷される版**です。単に
「ビルドして」と言われた場合は、この版をビルドします。

`python/prototype/`（PySide6）は**開発中の挙動評価用プロトタイプ**であり、配布しません。
ページ編集の挙動比較のためにリポジトリへ残しています。Python 版 UI との見た目一致は
**目標ではありません**。ネイティブ GUI は意図して Modern Dark テーマです。

C++/WebView2 への移植は一度目を完全破棄しています。理由は
[`../CPP_PORT_POSTMORTEM.md`](../CPP_PORT_POSTMORTEM.md)
（「ビルドとテストが通れば完了」として実機を動かさなかった）です。
2026-08-19 開始の二度目が、現在の v3.0.0 出荷版です。

**要点**: ユーザーが使うのは C++ GUI です。Python は試作であり、出荷 UI の仕様の正ではありません。
ページ編集の挙動が食い違う場合は両方を調べますが、ユーザー向けに正しい必要があるのは C++ 版です。

---

## 実行環境

- Windows 10 / 11（64-bit）
- Microsoft Edge WebView2 Runtime（GUI 実行時）
- Python 3.11+（ビルドスクリプト。3.14 で開発）
- MinGW-w64 C++17 コンパイラと `windres`（WinLibs MCF UCRT）

## セットアップ

### MinGW ツールチェイン

```powershell
winget install --id BrechtSanders.WinLibs.MCF.UCRT --exact --source winget
```

標準的なインストール先:

```text
%LOCALAPPDATA%\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.MCF.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin
```

`build_native.py` はこの場所を自動検索し、検出したコンパイラと同じフォルダの
`windres.exe` も使うため、プロジェクトのビルドだけなら PATH 登録は不要です。
`g++` / `windres` を直接叩きたい場合のみ、`mingw64\bin` を**ユーザー環境変数**の
PATH に追加してください（追加後はターミナル/IDE の再起動が必要）。

### WebView2 SDK と PDFium

どちらも `third_party/`（Git 管理外）へ取得します。

```powershell
powershell -File scripts\fetch_webview2_sdk.ps1
powershell -File scripts\fetch_pdfium.ps1
```

既定の探索先（必要なら環境変数で上書き）:

| コンポーネント | 既定 | 環境変数 |
| --- | --- | --- |
| WebView2 ヘッダー | `third_party/webview2/build/native/include` | `WEBVIEW2_INCLUDE` |
| PDFium ヘッダー | `third_party/pdfium/include` | `PDFIUM_INCLUDE` |

## 出荷するネイティブ版のビルド

```powershell
python build_native.py            # core/native/engine_tests.cpp も実行
python build_native.py --skip-tests
```

### `build_native.py` の内訳

1. `g++` または `clang++` を検出（PATH → WinGet の WinLibs → いくつかの予備パス）。
2. `bundle_html.py` で CSS/JS/画像を `dist/binary/index.html` にインライン化。Mermaid/MathJax は `vendor/` の script 参照のまま。
3. `.rc`（アイコン・バージョン情報）を `windres` / `llvm-windres` でコンパイル。
4. `webview_main.cpp` とエンジンを `-static` でリンクし `QuickMarkPDF.exe` を生成。
5. CLI デモを `-static` で `QuickMarkPDF_cli.exe` にリンク。
6. `pdfium.dll`、`WebView2Loader.dll`、`resources/vendor/` を `dist/binary/` へコピー。
7. `--skip-tests` が無ければ `engine_tests.cpp` をビルドして実行（このテスト exe は `-static` ではないため、MinGW ランタイム DLL を隣へコピーする）。

### ビルド成果物

| ファイル | 説明 |
| --- | --- |
| `dist/binary/QuickMarkPDF.exe` | GUI（製品本体） |
| `dist/binary/QuickMarkPDF_cli.exe` | 非 GUI のページモデルデモ |
| `dist/binary/pdfium.dll` | PDFium |
| `dist/binary/WebView2Loader.dll` | WebView2 ローダー |
| `dist/binary/index.html` | バンドル済み GUI |
| `dist/binary/vendor/` | Mermaid.js と MathJax |
| `core/native/QuickMarkPDF_native_tests.exe` | エンジンテスト（配布しない） |

`QuickMarkPDF.exe`、`pdfium.dll`、`WebView2Loader.dll`、`index.html`、`vendor/` は
同じフォルダに置きます。

**既知の環境上の癖**: CrowdStrike Falcon Sensor が動いている環境（この開発機で確認済み）では、
ビルド直後の未署名 exe がブロックされることがあります。実例として、ビルド成功直後に
`QuickMarkPDF_cli.exe` が `dist/binary/` から消え、`engine_tests.exe` の初回が
`STATUS_ENTRYPOINT_NOT_FOUND`（終了コード `3221225785`）で失敗したあと、再実行では成功しました。
この終了コードで失敗した場合、実回帰と決めつける前に再実行し、バイナリが残っているか確認してください。
GUI 本体までブロックされる場合は、コードの問題ではなくビルド出力先の除外設定の話です。

WebView2 プロセスをイメージ名だけで終了しないでください。`msedgewebview2.exe` は
Teams・Windows 検索などと共有されます。終了するのは `QuickMarkPDF.exe` の PID だけです
（`taskkill /PID <pid> /T /F`）。

## トラブルシューティング

| 症状 | 原因と対処 |
| --- | --- |
| WebView2 ヘッダーが見つからない | `scripts\fetch_webview2_sdk.ps1` を実行するか `WEBVIEW2_INCLUDE` を設定 |
| PDFium ヘッダー/DLL が見つからない | `scripts\fetch_pdfium.ps1` を実行 |
| `windres` が見つからない | コンパイラと同じフォルダにある。PATH 変更後はターミナル再起動 |
| 起動時に白画面 | `index.html` を再バンドルし、隣に `vendor/` があるか確認 |
| 起動できない（Runtime） | Microsoft Edge WebView2 Runtime (Evergreen) をインストール |
| `g++` / `windres` を直接叩けない | WinLibs の `mingw64\bin` をユーザー PATH へ。`build_native.py` 自体には不要 |
| 未署名 exe が消える、または終了コード `3221225785` | 上記 Falcon の癖。回帰と決めつける前に再実行 |
| `ModuleNotFoundError: No module named 'src'` | Python テストはリポジトリ直下を cwd にする（`pyproject.toml` の `pythonpath = ["python/prototype"]`） |

## 評価用プロトタイプ（Python）

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python python/prototype/main.py
python python/prototype/main.py path\to\file.pdf
```

PyInstaller onedir（配布しない）:

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

生成物: `dist/QuickMarkPDF/`（`QuickMarkPDF.exe` と `_internal`）。

### Python 自動テスト

```powershell
.venv\Scripts\python.exe python/tests/run_tests.py
```

既定の pytest 一式を実行し、`python/tests/reports/summary.md` と JUnit XML・HTML カバレッジを
`python/tests/reports/` へ書きます（Git 管理外）。

`python/tests/conftest.py` のオートユース `dialog_guard` が `QFileDialog` / `QMessageBox` /
`QInputDialog` / `QDialog.exec` をパッチします。未登録のダイアログはハングせず即失敗します。
テストあたり 60 秒のタイムアウトと合わせ、クリック待ちで止まらないようにしています。

| 場所 | 内容 | 既定で実行 |
| --- | --- | --- |
| `python/tests/test_*.py` | 単体 + `MainWindow` の開く/回転/削除/並べ替え/Undo/保存/書き出し | する |
| `python/tests/visual/` | `python/tests/visual_baselines/` とのスクリーンショット回帰 | する |
| `python/tests/perf/` | 読み込み/回転/並べ替え/Undo/書き出しの所要時間 | する |
| `python/tests/real_screen/` | 実ウィンドウ + `QTest` 入力 | しない（`--real-screen`） |

`QUICKMARKPDF_REAL_SCREEN=1` が無い限り offscreen Qt（`QT_QPA_PLATFORM=offscreen`）です。
この環境の offscreen Qt には CJK フォントが無く、見た目テストの日本語は豆腐になります。
レイアウト回帰の検出用であり、実機の日本語表示そのものではありません。

```powershell
.venv\Scripts\python.exe python/tests/run_tests.py --update-visual-baselines
.venv\Scripts\python.exe python/tests/run_tests.py --real-screen
.venv\Scripts\python.exe -m pytest python/tests/test_pdf_manager.py -v
```

TCP 制御チャネル（`core/native/test_api_server.cpp`）は `QUICKMARKPDF_TEST_PORT` が
無いと何もしません。ここのコマンド名（`load_pdfs`、`undo`、`save_as` など）は
テスト専用であり、[`spec_jp.md`](spec_jp.md) の GUI WebMessage とは別物です。

## 依存関係

出荷する C++ バイナリ: PDFium（`pdfium.dll`）、Windows の WebView2 Runtime、WIC。
フロントエンドはフレームワーク非依存。Markdown プレビュー用に Mermaid.js と MathJax を
`vendor/` へ同梱します。

Python 試作 / テスト: `requirements.txt`（PyMuPDF、PySide6、Pillow、Markdown、PyInstaller）と
`requirements-dev.txt`（pytest、pytest-qt、pytest-timeout、pytest-cov）。

## ファイル構成（出荷レイアウト）

```text
QuickMarkPDF/
├── .github/workflows/     ci.yml, release.yml（v* タグでネイティブ ZIP）
├── core/native/           C++ エンジン、WebView2 ホスト、CLI デモ、リソース
├── templates/             開発用 HTML
├── static/                開発用 CSS/JS
├── python/prototype/      評価用プロトタイプ（配布しない）
├── python/tests/          Python 試作のテスト
├── python/tools/          補助スクリプト
├── scripts/               fetch_webview2_sdk.ps1, fetch_pdfium.ps1
├── resources/vendor/      dist/binary/vendor/ へコピーする Mermaid / MathJax
├── assets/                README 用スクリーンショット（ZIP には入れない）
├── document/              開発者向け文書（英語 + _jp）
├── plans/                 日付付き計画書・実施結果
├── dist/binary/           ネイティブ成果物（フォルダ以外は Git 管理外）
├── dist/documents/        配布する txt（readme / history / LICENSE）
├── build_native.py
├── bundle_html.py
├── README.md / README_jp.md
└── HISTORY.md / HISTORY_jp.md
```

## 残課題（ビルド/CI。アプリ本体ではない）

- `QuickMarkPDF_cli.exe` に製品級の `--option` インタフェースは無い。
- Markdown のネストしたリストは未実装。
- ネイティブ版のページ描画・書き出しは同期処理（大量ページの並列レンダリングは無い）。
