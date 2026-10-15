# dist のバイナリが古いバージョンのまま

- 日付: 2026-10-15
- 報告: dist にあるバイナリが古いバージョンのままに見える。確認してからビルドしてほしい。
- 目的: `dist` の実行ファイルの版と、ソースが宣言している版を突き合わせ、古いなら現行ソースでビルドし直す。
- 計画: バージョンリソースとファイル時刻を確認し、差分があれば `python scripts/build.py build` で再ビルドする。ビルド後に成果物の版を再確認する。
- 実装: 確認結果を下に記録する。About の表示だけ古いので直してから再ビルドする。
- 評価: ビルド成否と、再ビルド後の FileVersion / ProductVersion、埋め込み HTML の版表示を記録する。

## 確認結果（ビルド前）

- 対象: `dist/QuickMarkPDF.exe`（2026-10-14 14:12:01、9,733,523 bytes）、`dist/QuickMarkPDF_cli.exe`（同時刻前後）。QuickMarkPDF プロセスは動いていなかった。
- Windows のバージョンリソースは FileVersion / ProductVersion とも `4.2.0.0`。ソースの `src/app/QuickMarkPDF.rc` と一致する。CLI にはバージョンリソースが無い。
- v4.2.0 の改ページ実装（`isPageBreakLine`、`class="page-break"`、印刷用 `hr` の色）は exe 内の埋め込み UI に含まれている。機能コード自体は古いバイナリではない。
- 画面に出る版だけが古い。`src/ui/index.html` の About が `Ver. 4.1.0` のままで、同じ文字列が exe にも埋め込まれている。ドキュメントとリソース版数は v4.2.0。
- 対応: About の表示を `Ver. 4.2.0` に直し、`python scripts/build.py build` で再ビルドする。

## 実装

- `src/ui/index.html` の About を `Ver. 4.1.0` から `Ver. 4.2.0` に変更した。
- `python scripts/build.py build` は成功。GUI と CLI を `dist` に出力した。エンジンテストは今回の対象外（`build` のみ）。

## 評価

- `dist/QuickMarkPDF.exe`: 2026-10-15 12:51:12、9,733,523 bytes。FileVersion / ProductVersion は `4.2.0.0`。
- 埋め込み UI は `Ver. 4.2.0` が 1 件、`Ver. 4.1.0` は 0 件。`isPageBreakLine` と `class="page-break"` も含まれる。
- `dist/QuickMarkPDF_cli.exe`: 2026-10-15 12:51:24、3,247,401 bytes。バージョンリソースは元から無い。
- `pdfium.dll` と `WebView2Loader.dll` は再コピー済み。時刻は元ファイルのまま。
- GUI の起動確認はしていない。
