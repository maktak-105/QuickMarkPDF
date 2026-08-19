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

`WorkingDocument`(`core/native/engine.h`)はUndo履歴とdirtyフラグを持ちます。変更系メソッド(`append_page`・`reorder`・`rotate`・`erase`)は、確定直前にページ一覧をスナップショットし(例外を投げて失敗する呼び出しではスナップショットを積まない)、dirtyを立てます。`undo()`は最新のスナップショットを1件戻します。Python版の`push_undo_snapshot`と同じ上限20件です。`clear()`はハードリセット扱いで、それ自体はUndo対象にならずUndo履歴とdirtyフラグを両方消します(clear後は以前の`PageRef`を復元する意味がないため)。`mark_saved()`はdirtyを解除しますが、これは`PdfBackend::save()`が実際に成功した経路からのみ呼び出す想定です(catchブロックからは呼ばない)。保存失敗時はdirtyのままになります。

`inspect()`は各ページ自身の回転(`page_rotations`、`FPDFPage_GetRotation`)も返します。`WorkingDocument`の回転は絶対値として`FPDFPage_SetRotation`で反映する契約のため、新規`append_page`時の初期値は0ではなくソースページ自身の回転にする必要があります(でなければ保存/レンダリング時にすでに回転していたページを無回転へ戻してしまいます)。`render_page`と新設の`render_page_at_dpi`(同じレンダリング経路をピクセル幅ではなくDPI指定で使う、画像出力用)はどちらも、幅・高さを問い合わせる前に`FPDFPage_SetRotation`で回転を適用するため、90/270度回転時に出力アスペクト比が正しく入れ替わります。

### `host.cpp`と`WorkingDocument`の統合

`host.cpp`はセッション全体で1つの`WorkingDocument`(`g_document`)を保持するようになりました(以前の「直近に開いた1ファイルのパス」から変更)。加えて`source_path -> password`のマップを持ち、`PdfBackend::save`が暗号化ソースを再度パスワード入力なしで開けるようにしています。WebMessageプロトコル:

| JSから | 動作 |
|---|---|
| `open_pdf` | ネイティブの複数選択Openダイアログ(`OFN_ALLOWMULTISELECT`)。各ファイルを`inspect()`し、ページを`g_document`へ`append_page`。暗号化ファイルはネイティブのパスワード入力(後述)を最大3回リトライし、失敗したファイルはスキップして応答の`failed_files`へ列挙。応答`pdf_opened`に`loaded_files`・`failed_files`とドキュメント全体の状態(`page_count`・`dirty`・`can_undo`・`pages`)を含める |
| `render_page {page_index, width}` | `g_document.page(page_index)`(自身の回転込み)をレンダリングし`page_rendered`で応答。単一パス追跡から`g_document`参照へ変わった以外は従来通り |
| `reorder_pages {order}` / `rotate_page {page_index, degrees}` / `delete_pages {indices}` / `undo_edit` | 対応する`WorkingDocument`メソッドを呼び、`document_state`(`pdf_opened`と同形、読み込み専用フィールドを除く)で応答 |
| `save_pdf` | ネイティブSaveダイアログ後、`PdfBackend::save(g_document, path, g_source_passwords)`。`mark_saved()`は`save`が例外を投げずに完了した場合のみ呼ぶ |
| `export_images {indices, dpi}` | ネイティブのフォルダ選択後、`render_page_at_dpi`(デフォルト150DPI、Python版と同じ)+WICによるPNGエンコード(`IWICImagingFactory`/`IWICBitmapEncoder`、`GUID_ContainerFormatPng`)を対象ページ(`indices`が空なら全ページ)ごとに実行、`page_0001.png`等の名前で保存 |

パスワード入力は自作ダイアログではなく`CredUIPromptForCredentialsW`(`wincred.h`)を使用しました。ドキュメント化された1関数呼び出しの方が、実際に操作しないと気付けない細かい誤りが入り込みにくいためです。画像出力のフォルダ選択は、非推奨の`SHBrowseForFolder`ではなく、WebView2自体で既に使っている`ComPtr`/WRLスタイルに合わせた`IFileOpenDialog` + `FOS_PICKFOLDERS`(COM)を使用します。

`ui/app.js`も合わせて更新し、各ページ行に上へ移動・下へ移動・回転・削除ボタンを追加(`reorder_pages`/`rotate_page`/`delete_pages`を送信)、ツールバーにUndoと画像書き出しボタンを追加しました。ドラッグ&ドロップでの並べ替えとクリック拡大プレビューはまだ未着手のPhase 2項目のままです。

**まだ画面操作での確認はしていません**: 今回の`host.cpp`/`ui/`変更は`cmake --build`(クリーンビルド、警告ゼロ)でのみ確認しています。ネイティブの複数選択ダイアログ・パスワード入力・保存ダイアログ・フォルダ選択・新しいUIボタン類は、実際に操作しての確認がまだ必要です。

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
