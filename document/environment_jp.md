# 開発環境

[English environment.md](environment.md)

`python/`（PySide6版）が本アプリの仕様の正です。C++/WebView2移植をなぜ中止したかは
[`../CPP_PORT_POSTMORTEM.md`](../CPP_PORT_POSTMORTEM.md) を参照してください。本文書は
Python版のソースからの実行・Windows実行ファイルのビルド、そして本題である
自動テストプログラムの実行方法をまとめたものです。

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
