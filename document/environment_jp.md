# 開発環境

[English environment.md](environment.md)

## 現状(まずここを読む)

`python/`（PySide6版）は**仕様の正**です。移植が満たすべき正しい挙動・UI・機能一覧を定義するもので、
それ自体がユーザーに配布するものではありません。

`core/native/`（C++17 + WebView2）が**現在ビルド・配布する対象**です。C++/WebView2への移植は
一度目は完全に失敗して破棄されています(理由は
[`../CPP_PORT_POSTMORTEM.md`](../CPP_PORT_POSTMORTEM.md) を参照 — 「ビルドが通り
テストが通れば完了」という基準で進め、実機で確認せず、Python版の仕様から乖離した)。
二度目の移植(commit `3cb33f1` 以降、2026-08-19開始)はこのpostmortemの教訓に従い、
ビルド・テストPASSだけでなく実機でのUI操作確認と独立したファイルレベル検証(PyMuPDF/Pillow)を
行っており、ツールバー機能の大部分でPython版と同等の水準に達しています。
詳細な機能別の検証記録・残課題(Mermaid/MathJax、GFMテーブル、ExportDialog相当など)は
`plans/2026-08-20_*` を参照してください。

**要点**: Python版とC++版の挙動が食い違う場合、Python版が正しく、C++版側のバグです。
単に「ビルドして」と言われた場合はC++版をビルドします(後述) — ユーザーが実際に使うのはこちらです。

---

本文書は、まずPython版のソースからの実行・Windows実行ファイルのビルド、そして本題である
自動テストプログラムの実行方法をまとめたものです。C++版のビルド方法は後半の
「C++/WebView2版のビルド」を参照してください。

## 実行環境

- Windows 10 / 11 (64-bit)
- Python 3.11以上（3.14で開発）

## セットアップ

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` はアプリ本体が必要とするもの、`requirements-dev.txt` は
テストツールチェイン（pytest / pytest-qt / pytest-timeout / pytest-cov）です。

## ソースからの実行

```powershell
python python/main.py
python python/main.py path\to\file.pdf    # ファイルダイアログを経由せず直接開く
```

## Windows実行ファイルのビルド

```powershell
.venv\Scripts\pyinstaller.exe quickmarkpdf.spec --noconfirm
```

生成物は `dist/QuickMarkPDF/` に作成されます。`QuickMarkPDF.exe` と
`_internal` フォルダは同じ場所に置いてください。

## 自動テスト

以下の1コマンドですべて実行できます。

```powershell
.venv\Scripts\python.exe run_tests.py
```

pytestで既定のテスト一式を実行し、`tests/reports/summary.md`（pass率・失敗一覧・
所要時間表）とJUnit XML、HTMLカバレッジレポートを `tests/reports/` 配下に出力します。
終了コードはpytestのものをそのまま返すので、スクリプトからの利用も安全です。
`tests/reports/` は生成物のため `.gitignore` 対象で、コミット対象ではありません。

### ダイアログガードが存在する理由

C++移植のポストモーテムは、丸一日を無駄にした原因を2つ挙げています。
「ビルドが通る・自動テストが通る」を実操作確認なしに完了の根拠にしてしまったこと、
そしてネイティブのファイル選択ダイアログを自動化で検証しようとして何度も安定しなかったことです。

`tests/conftest.py` のオートユースフィクスチャ `dialog_guard` は後者に直接対処します。
アプリが使うネイティブダイアログの呼び出し箇所（`QFileDialog.*`、`QMessageBox.*`、
`QInputDialog.getText`、`QDialog.exec`）をすべてパッチし、テストが明示的に応答を
用意していない限り、呼び出した瞬間に例外を送出します。実際のダイアログを待って
永久にブロックすることはありません。`pytest-timeout` によるテスト単位60秒の
タイムアウトと合わせて、このスイートのどのテストも実行全体を止めることはありません。

実際にダイアログを経由するフローを検証したい場合は、テスト側で応答を登録します。

```python
def test_something(main_window, dialog_responses):
    dialog_responses.push("QFileDialog.getSaveFileName", (str(out_path), "PDF Files (*.pdf)"))
    dialog_responses.allow("QMessageBox.information")  # 成功時の通知ポップアップを何回でも許可
    main_window.save_pdf()
```

`ExportDialog`・`PreferencesDialog`・手組みの `QMessageBox` のような実際の
`QDialog` サブクラスの場合は、応答としてコーラブル（関数）を渡すことで、
既に構築済みのダイアログインスタンスを「閉じる」前に設定できます。

```python
def configure(dialog):
    dialog.dir_edit.setText(str(out_dir))
    dialog.scope_all.setChecked(True)
    return QDialog.DialogCode.Accepted

dialog_responses.push("QDialog.exec:ExportDialog", configure)
```

未登録のダイアログ呼び出しは、呼び出し箇所名を含む明確な `UnexpectedDialog` で
即座に失敗します。ガード自体のテストは `tests/test_dialog_guard.py` を参照してください。

### テストの階層

| 場所 | 検証内容 | 既定実行に含む？ |
| --- | --- | --- |
| `tests/test_*.py` | 単体テスト（`PDFManager`、`MarkdownManager`）と、実際の`MainWindow`を開く/回転/削除/並べ替え/元に戻す/保存/エクスポートまで一通り操作する結合テスト | はい |
| `tests/visual/` | スクリーンショットによる見た目回帰（`QWidget.grab()` と基準PNGの比較） | はい |
| `tests/perf/` | 読み込み/回転/並べ替え/元に戻す/エクスポートの所要時間計測、`tests/reports/perf.json` に記録 | はい |
| `tests/real_screen/` | 実際に表示したウィンドウを`QTest`の合成マウス/キーボード入力で操作し、スクリーンショットを保存（人間による目視確認用） | いいえ（明示指定時のみ） |

`QUICKMARKPDF_REAL_SCREEN=1` を事前に設定しない限り、すべてオフスクリーンの
Qtプラットフォーム（`tests/conftest.py` 冒頭で設定する `QT_QPA_PLATFORM=offscreen`）で実行されます。

### 見た目回帰テスト

基準画像は `tests/visual_baselines/` に置き、gitで管理します。新しい基準名に
対する初回実行では画像を作成するだけで（比較対象がまだ無いため）スキップとして
報告されます。比較は完全一致ではなく、わずかな平均ピクセル差の許容値で行い、
描画のわずかな揺らぎを吸収します。

**既知の制限**: この開発環境のオフスクリーンQtプラットフォームには日本語フォントが
インストールされておらず、スクリーンショット中の日本語UIテキストは豆腐（□）として
描画されます。レイアウト崩れ・要素の欠落などの構造的な回帰検知には引き続き有効ですが、
ユーザーが実際に目にする日本語表示そのものを表しては**いません**。実際の見た目確認には
通常のWindowsセッションでの `real_screen` 階層の実行、またはアプリを直接起動しての
目視確認を使ってください。

意図的なUI変更の後に基準画像を更新する場合:

```powershell
.venv\Scripts\python.exe run_tests.py --update-visual-baselines
```

### 実画面階層

実際に表示・操作可能なWindowsデスクトップセッションが必要で、明示的なオプトインが
2箇所必要です（pytest起動前に1つ: `QT_QPA_PLATFORM` をPySide6インポート前に
強制offscreen化させないため。マーカー選択に1つ）。

```powershell
.venv\Scripts\python.exe run_tests.py --real-screen
# 上記は以下と同等:
$env:QUICKMARKPDF_REAL_SCREEN = "1"
.venv\Scripts\python.exe -m pytest -m real_screen tests/real_screen -v
```

これらのテストは実際の`MainWindow`を表示し、`QTest.mouseClick`（OSレベルの自動化
ツールではなく、実ウィンドウを通して配信される）でクリックし、`tests/reports/real_screen/`
にスクリーンショットを保存して人間が後から確認できるようにします。自動化された
スクリーンショット比較では構造的に確認できないこと ── 実際に人が見たときに
アプリが正しく見え、動作すること ── を確認するための最終手段です。

### 一部だけ実行する

```powershell
.venv\Scripts\python.exe -m pytest tests/test_pdf_manager.py -v
.venv\Scripts\python.exe run_tests.py -- tests/test_pdf_manager.py -v
```

## QAダッシュボード(Python版/C++版のパリティ測定)

上記pytestスイートとは別に、`qa/`配下はC++移植が実際にPython仕様と一致しているか
(サイズ・HSV色・実際の挙動)を**数値で**測定します。計画書の自己申告「見た目は合ってる」
に頼りません。詳細設計は `plans/2026-08-20_C++版Python完全一致化_v1.3.md` を参照。概要:

```powershell
.venv\Scripts\python.exe qa\extract_python.py          # -> qa/baseline.json
.venv\Scripts\python.exe qa\check_behaviors_python.py  # -> qa/behaviors.json
.venv\Scripts\python.exe qa\dashboard.py                # -> qa/dashboard.html
```

- `extract_python.py` は実際の`MainWindow`を実Windowsデスクトップ上で構築します
  (意図的に`QT_QPA_PLATFORM=offscreen`を使いません — この環境のoffscreenプラットフォームには
  日本語フォントが無く、日本語テキストが豆腐になりスクリーンショットが無意味になるためです)。
  `findChildren`で全ウィジェットを走査し、ウィンドウ全体のスクリーンショットを1枚取得して、
  各ウィジェットの矩形と代表色(HSV)をそこから測定します。全`QAction`はテキスト・ショートカット・
  有効状態・`isSeparator()`まで含めて列挙します。
- `check_behaviors_python.py` はアプリの実際のメソッドと実際のQtイベント(ドラッグ並べ替えは
  下流ハンドラを直接叩くのではなく、実際の`QDragEnterEvent`/`QDropEvent`を発行)を実行します。
  OSレベルのマウス自動化は一切使わず、ダイアログは値を直接注入して応答します
  (`unittest.mock.patch`、クリック操作ではない)。現状26/26件PASS。サムネイルサイズの
  チェックは内部のサイズ名文字列ではなく、パネルが実際に設定する`iconSize()`のピクセル値
  そのものを測定します(小→108×105、中→148×155、大→228×260)。
- `dashboard.py` は両方の結果を`qa/dashboard.html`にまとめます。人が直接読むための成果物で、
  各チェックに観察内容をプロースで記述し(「3枚目のサムネイルをドラッグして先頭にドロップした
  ところ、ページ順が実際に[...]に入れ替わった」)、単なる✓/✗では済ませません。全テーブルに
  Python列とC++列を横並びで持ち、`qa/baseline_cpp.json`・`qa/behaviors_cpp.json`があれば
  読み込み(無ければ灰色で「未計測」)、`qa/part_mapping.yaml`経由でPython側パーツと対応付けます。

C++側の測定は、測定対象が違うため意図的に2つの独立したツールに分かれており、
同じ通信経路を共有していません。

- `qa/check_behaviors_cpp.py` → `qa/behaviors_cpp.json`。`PdfManager`を
  ループバック限定のTCP制御チャネル(`core/native/test_api_server.{h,cpp}`、
  `QUICKMARKPDF_TEST_PORT`環境変数で有効化。未設定時はno-opなので通常のユーザー起動には
  影響しない)経由で直接操作します。WebView2/JS層を完全にバイパスし、TCPスレッドが
  `WM_APP_TEST_COMMAND`をメインUIスレッドへpostして`condition_variable`で結果を待つため、
  各コマンドは実UIスレッド上で実`PdfManager`に対して直列実行されます。現状**15/26件PASS**。
  残りはUI層のみの挙動で`PdfManager`からは観測できないもの(プレビューのズーム/パン、
  サムネイルサイズボタン、環境設定ダイアログ)か、C++側が実際に未実装の機能(クロップ書き出し、
  PDF/Markdown混在時の警告、未保存変更の確認)です。各チェックの理由は`qa/behaviors_cpp.json`参照。
- `qa/extract_cpp.py` → `qa/baseline_cpp.json`。`extract_python.py`がQtウィジェットを
  測定するのと同様に、実際にレンダリングされたDOMの座標・色を測定するため、TCP APIでは
  ピクセルレイアウトの概念自体が無く、WebView2の実Chromiumレンダラーを経由せざるを得ません。
  実行中のWebView2インスタンスへMicrosoft Edge WebDriver(`msedgedriver.exe`、インストール
  済みWebView2 Runtimeのバージョンと一致必須、Git管理外なので別途取得)を
  `EdgeOptions.use_webview`/`debugger_address`で
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`にアタッチし、
  `execute_script`でDOMを走査します。**既知の不安定要因**: `execute_script`/`Runtime.evaluate`を
  1秒に1回より高頻度でポーリングするとWebView2レンダラーのメインスレッドが飢餓状態になり、
  C++↔JSの`postMessage`ブリッジが完全に応答しなくなります — `qa/selenium_client.py`はポーリング
  ループの代わりに単発の固定`time.sleep()`で回避していますが、`connect()`のWebDriverアタッチ自体は
  依然として断続的に`SessionNotCreatedException`を投げ、根本原因は未特定です。新しい
  `qa/baseline_cpp.json`・見た目の一致率数値は、この問題が直るまで**安定再現できないもの**として
  扱ってください。

`check_behaviors_cpp.py`・`extract_cpp.py`ともexeを`QUICKMARKPDF_OFFSCREEN=1`付きで起動します。
これにより`webview_main.cpp`はメインウィンドウを`WS_EX_LAYERED`+
`SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)`で完全透明化して作成します(画面外座標への
移動ではありません — 以前試した画面外座標配置はWebView2メッセージバスを不安定にしました。
可視デスクトップ外に置かれたウィンドウに対してDWMが合成・描画最適化を止める可能性があります)。
**QA目的でexeを起動する際、このフラグを外して画面に表示させてはいけません。**

## C++/WebView2版のビルド

こちらが現在の配布対象です(上記「現状」参照)。ソースは `core/native/`、`templates/`、`static/`。

```powershell
# 初回のみ: third_party/ へSDKを取得(gitignore対象、コミット不要)
powershell -File scripts\fetch_webview2_sdk.ps1
powershell -File scripts\fetch_pdfium.ps1

# ビルド
python build_native.py            # core/native/engine_tests.cpp の実行も含む
python build_native.py --skip-tests
```

MinGW-w64の `g++`/`clang++` がPATH上(または `build_native.py` が探索するフォールバックパス、
WinGetでインストールしたWinLibs UCRTツールチェイン含む)に必要です。C++17。配布物は
コンパイラのランタイムDLLをユーザー環境に要求しないよう `-static` でリンクしていますが、
単体ビルドの `engine_tests.cpp` だけは `-static` を付けていないため、実行時に
`libgcc_s_seh-1.dll`/`libstdc++-6.dll` が同じフォルダかPATH上に必要です。

成果物: `dist/binary/QuickMarkPDF.exe`(+ `pdfium.dll`、`WebView2Loader.dll`、
バンドル済み `index.html`)がユーザーに渡す本体です。`QuickMarkPDF_cli.exe` はGUIを持たない
軽量な検証用デモバイナリで、配布対象には含みません。

**既知の環境上の癖**: CrowdStrike Falcon Sensorが動いている環境(この開発機で確認済み。
「悪意のある振る舞いが検知されたため、プロセスはブロックされました」の通知が1回のビルドで
13件以上発生)では、ビルド直後の未署名exeが書き込み・実行直後にブロックされることがあります。
実例として、ビルド成功直後に `QuickMarkPDF_cli.exe` が `dist/binary/` から消滅し、
`engine_tests.exe` の初回実行が `STATUS_ENTRYPOINT_NOT_FOUND`(終了コード `3221225785`)で
失敗した後、クリーンな再実行では成功しました。ビルド直後のテストがこの終了コードで失敗した場合、
実回帰と決めつける前に再実行し、まずバイナリ自体が残っているか確認してください。
`QuickMarkPDF.exe` 本体はこの時は無事でしたが、もし配布用GUI本体までブロックされるように
なった場合は、コードの問題ではなくIT部門にビルド出力先の除外設定を依頼する話になります。

## トラブルシューティング

| 症状 | 原因・対処 |
| --- | --- |
| `ModuleNotFoundError: No module named 'src'` | リポジトリ直下以外の`cwd`から`unittest`/`pytest`を直接実行しない。`pytest`は`pyproject.toml`の`pythonpath = ["python"]`で自動解決される。素のスクリプトなら`PYTHONPATH=python`を設定する |
| テストが返ってこずハングする | 本来起きないはず。発生した場合は`dialog_guard`/`pytest-timeout`側の問題として報告してほしい。`QApplication`生成前に`QWidget`を構築するコードパスが無いか確認する（このQt/Windowsの組み合わせでは例外ではなくハングすることを確認済み）。`tests/conftest.py`のオートユースフィクスチャ`_ensure_qapp`はこれを防ぐために存在する |
| 意図的なUI変更後に見た目テストが失敗する | `--update-visual-baselines` で再実行し、`tests/visual_baselines/` 配下の新しいPNGを確認してコミットする |
| Markdownテストで `QtWebEngine not available` としてスキップされる | 環境によっては想定内。`PySide6-Addons` が提供する。テスト失敗ではない |

## 依存関係

サードパーティのC++ライブラリ依存なし。`requirements.txt`（実行時: PyMuPDF、
PySide6、Pillow、Markdown、PyInstaller）と `requirements-dev.txt`
（テスト専用: pytest、pytest-qt、pytest-timeout、pytest-cov）を参照してください。
