# C++ QA全項目パリティ確認とengine_tests修正 実施結果 v1.0

実施日: 2026-08-21
対応する計画書: なし（QAダッシュボード整備（`agent/cpp-core-bootstrap`ブランチのpull分）を受けての検証・修正）

## 1. 実施内容

1. pull直後、新規追加されたUI層QAチェッカー`qa/check_ui_behaviors_cpp.py`（WebDriver経由でexeを直接操作し、TCP APIでは検証不可なDOM/JS層の挙動を確認するスクリプト）を初回実行。結果は9項目中6項目PASSだったが、うち3項目（`preview_crop_area_selection`・`page_number_labels_distinct_from_position`・`markdown_mode_switch`）がFAIL。
2. ユーザーから「別環境では100%成功していた」との指摘を受け原因調査。`dist/binary/QuickMarkPDF.exe`のタイムスタンプ（8/20 18:44）が、pullで取り込まれた最新コミット（8/20 23:41、`webview_main.cpp`/`app.js`に大幅変更）より古いことを特定。**実行していたexeがpull前の古いビルドのままだった**ことが原因。
3. `python build_native.py`で再ビルド後、`check_ui_behaviors_cpp.py`を再実行 → 9項目全PASSに変化。別環境の結果と一致することを確認。
4. 残っていた1件のFAIL`mixed_pdf_markdown_open_rejected`（PDF+Markdown混在オープン時の警告）を調査。`webview_main.cpp`の`open_document_paths()`（863〜924行目）に既に実装済み（`has_markdown && has_pdf`時に情報ダイアログを出し`RejectedMixed`を返す処理）であることが判明し、コード追加は不要だった。`check_behaviors_cpp.py`（TCP API経由）を再実行しPASSを確認。
5. `engine_tests.exe`が実行時にDLLエラー（exit code 3221225785 = 0xC0000135 = DLL not found）で落ちる件を調査。`objdump -p`で依存DLLを確認したところ`libgcc_s_seh-1.dll`・`libstdc++-6.dll`への動的リンクが原因と特定。GUI/CLIビルドは`-static`で静的リンクしているが、`build_native.py`の`build_tests()`のコンパイルコマンドだけ`-static`が抜けていた。
6. 修正案1として`-static`をテストビルドにも追加 → この環境ではビルド後の`subprocess.run([out_exe])`が`PermissionError: [WinError 5] アクセスが拒否されました`で失敗し、生成された`.exe`自体も直後に消失（セキュリティソフトによる検疫の疑いが濃厚、`Get-MpThreatDetection`には記録なし、`Get-MpPreference`は権限不足で確認不可）。再現性ありのため不採用。
7. 修正案2として、GUI/CLIと同じ動的リンクのまま、`pdfium.dll`と同様にコンパイラ隣接の`libgcc_s_seh-1.dll`・`libstdc++-6.dll`・`libwinpthread-1.dll`を`core/native/`へコピーする処理を`build_tests()`に追加。再ビルド後`engine_tests`が全件PASSすることを確認。
8. `check_behaviors_cpp.py`と`check_ui_behaviors_cpp.py`は互いに`qa/behaviors_cpp.json`の該当エントリだけを上書きする設計のため、**先にTCP API側→後からUI層側の順で実行しないと、UI層の結果がTCP API側のstub（未実装扱い）で消される**ことが実行中に判明。正しい順序で両方を再実行し直した。

## 2. 検証結果（実際に確認した内容）

- `qa/behaviors_cpp.json`: **27/27件PASS**（Python版`qa/behaviors.json`の26件 + `page_number_labels_distinct_from_position`の追加1件、すべて一致）。
- `engine_tests.exe`: 全件PASS（`All engine_tests assertions passed.`）。

## 3. 発見事項（重要な学び）

- **QAスクリプトの結果はビルド済みexeの鮮度に強く依存する。** `git pull`後にビルドし直さず検証すると、実装済みの機能が「未実装」として誤ってFAIL判定される。今後この種のQAは実行前に`build_native.py`の再ビルドを徹底する。
- `behaviors_cpp.json`の「C++未実装」というFAILラベルは、実装が本当に無いことを必ずしも意味しない。`check_ui_behaviors_cpp.py`のdocstringにある通り、検証手段（TCP APIでは届かないDOM/JS層）が無かっただけで、機能自体は実装済みのケースが複数あった。

## 4. 変更ファイル

- `build_native.py`: `build_tests()`のテストビルドに、GUI/CLIと同じランタイムDLL（`libgcc_s_seh-1.dll`・`libstdc++-6.dll`・`libwinpthread-1.dll`）をコンパイラの場所から`core/native/`へコピーする処理を追加。`-static`化は本環境での実行時エラーのため不採用。

## 5. 残課題

- 前回のplan（`2026-08-20_C++PDF切り出しと残検証_結果_v1.0.md`）で挙がっていたJPEG画像出力・環境設定・右クリックメニュー・キーボードショートカットは、今回のQA項目（27件）には含まれておらず未検証のまま。
- Python版とのピクセル単位の見た目比較は引き続き未実施。
