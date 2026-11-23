# QuickMarkPDF 脆弱性診断 (2026-11-23)

対象: C++17 + WebView2 現行アプリ (`src/`、`scripts/`、`.github/workflows/`、`dist/` のビルド成果物)。
対象外: `proto/` の PySide6 試作版、WebView2 Runtime 本体、pdfium 本体の内部実装。
方法: ソース全読 + 実バイナリ (`dist/QuickMarkPDF.exe`、offscreen・隔離した WebView2 データフォルダ・テスト用 TCP API) と、exe に埋め込まれる HTML (`build/intermediate/generated_index.html`) を使った再現。
コードの変更は行っていない (本書のみ追加)。

## 結論

最大の問題は **Markdown レンダラーの XSS** で、これが **ネイティブ橋渡しに無検証で届く** 構造になっている。
信頼できない `.md` を開くだけで、アプリ内で任意スクリプトが動き、その後に開いた PDF の内容を読み取れる。ネイティブ側へ任意のコマンドも送れる。

| ID | 重大度 | 内容 | 検証 |
|----|--------|------|------|
| V-1 | 高 | Markdown 経由の XSS (3 経路 + Mermaid loose) と、防御層 (CSP・送信元検証・ナビゲーション制限) の欠如 | 実バイナリで再現 |
| V-2 | 中〜高 | 画像出力の `prefix` / `output_dir` が無検証で、出力先フォルダ外へ書き込める | 実バイナリで再現 |
| V-3 | 中 | 暗号化 PDF を保存・上書きすると暗号化が黙って外れる | 実バイナリで再現 |
| V-4 | 低〜中 | WebView2 の本番向け絞り込みなし (DevTools・右クリック・アクセラレータキー) | コード確認 |
| S-1 | 低〜中 | `render_page` の width と書き出し dpi に上限なし (メモリ枯渇) | コード確認のみ |
| S-2 | 低 | テスト用 TCP API が製品ビルドに含まれる (認証なし・ループバックのみ) | 動作確認済 |
| S-3 | 低 | `pdfium.dll` を名前だけで `LoadLibraryW` (検索順序ハイジャック余地) | コード確認 |
| S-4 | 低 | 上書き保存の一時ファイルが固定名・非アトミック | コード確認 |
| S-5 | 低 | PDF パスワードがメモリに平文で残る (ゼロクリアなし) | コード確認 |
| S-6 | 低 | WebView2 データフォルダが `%TEMP%` 直下の固定名 | コード確認 |
| B-1 | 中 | 依存バイナリ (pdfium・WebView2 SDK) をハッシュ検証なしで取得 | コード確認 |
| B-2 | 中 | CodeQL が JavaScript を解析していない (V-1 の発生源が対象外) | コード確認 |
| B-3 | 低 | 配布物が未署名、ビルドの堅牢化フラグなし、CI の依存が未固定 | PE ヘッダ確認 |
| B-4 | 中 | 同梱ライブラリが最新ではない (pdfium 12 リリース遅れ、WebView2 SDK 約 2 年、Mermaid 11.15.0 に該当する公開勧告 5 件)。**初版で「pdfium は新しい」と書いたのは確認不足の誤りで、訂正済み** | 上流 (GitHub・NuGet・npm) で確認 |

問題なしと確認できた点:
- ASLR / DEP / HighEntropyVA は有効 (PE ヘッダ確認)。
- ファイル名・ステータス表示は `textContent` で、ファイル名経由の XSS はない (`app.js:583-585`、`app.js:845`)。
- UI は `WebResourceRequested` で exe 内蔵リソースを返し、仮想ホストのフォルダマッピングは使っていない。ローカルファイルは公開されない。
- テスト用 TCP サーバーは 127.0.0.1 のみ待ち受け、環境変数 `QUICKMARKPDF_TEST_PORT` 指定時のみ起動する。
- `WebView2Loader.dll` はフルパスで読み込んでいる。
- 追跡ファイルに秘密情報・証明書・バイナリの混入はない。

## V-1 Markdown XSS (高)

### 原因 (`src/ui/js/app.js`)

1. **`$…$` / `$$…$$` の中身が生 HTML のまま戻る** (`restoreMathTokens`、168-177 行)。
   `protectMath` が数式を退避し、変換後に `value.content` をエスケープなしで `innerHTML` へ戻す。
   例: `$<img src=x onerror=...>$` → スクリプト実行。
2. **`escapeHtml` が `"` を処理しない** (205-207 行)。画像 `![alt](src)` とリンク `[t](href)` (211-212 行) が属性値へ展開されるため、属性注入が成立する。
   例: `![x" onerror="...](a.png)`。
3. **リンクの URL スキーム検証なし** (212 行)。`javascript:` が `href` に残る (属性として残ることまで確認、クリック実行は未確認)。
4. **Mermaid が `securityLevel: 'loose'`** (195 行)。`click B href "javascript:..."` がクリックで実行された (HTML ラベル内の `onerror` は Mermaid 側のサニタイズで除去された)。
5. 138-141 行のコメント「生 HTML はリテラル表示になるので安全」は事実と異なる。

### 被害が拡大する構造 (防御層の欠如)

- `index.html` と、ネイティブが返すレスポンスヘッダ (`main_gui.cpp:2082`、Content-Type と Cache-Control のみ) に **CSP がない**。外部への送信 (fetch・img) と外部スクリプト読み込みを止められない。
- `WebMessageReceived` が **送信元を検証しない** (`main_gui.cpp:2099-2116`)。
- `NavigationStarting` / `NewWindowRequested` のハンドラがない。
- ネイティブへ届くコマンドは `export_images` (任意フォルダ・任意 prefix へ書き込み)、`close_document`、`set_language` など。

### 再現結果

- ブラウザで、exe に埋め込まれる実 HTML を使用 (仮ブリッジ付き):
  - 数式経路、画像 alt 経路: スクリプト実行を確認。
  - リンク: `onmouseover` 属性の注入と `javascript:` href の保持を確認。
  - Mermaid: `javascript:` リンクのクリック実行を確認。
  - 悪意ある `.md` を開いたあとに `pdf_opened` / `text_layout` が届くと、注入スクリプトのリスナーが機密 PDF のパスと本文テキストを受信した。(この盗聴は仮ブリッジでの確認。本物の WebView2 でも複数リスナーが使えるはずだが、未確認。)
- **実バイナリで端から端まで再現**: 悪意ある `.md` を開く → 注入スクリプトが `export_images` を 500ms 周期で送信 → PDF が開かれた瞬間、ダイアログなしで選択フォルダ外 (`../xss_escaped_0001.png`) へ画像が書き込まれた。PDF を開く前は何も書かれない。

### 修正案

- Markdown 出力に許可リスト方式のサニタイズ (DOMPurify 等) を最終段に必ず通す。最小修正なら次の 3 点:
  - `escapeHtml` に `"` と `'` を追加。
  - 数式の `value.content` を `escapeHtml` してから戻す。MathJax は DOM のテキストを読むので、エスケープしても数式として扱われる。
  - リンク・画像の URL を `https:` / `http:` / `mailto:` (と必要なら相対パス) に限定する。
- Mermaid は `securityLevel: 'strict'` にする。
- CSP を `WebResourceRequested` のレスポンスヘッダで付与する。最低限: `connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'; img-src 'self' data:`。インライン script があるため `script-src` はハッシュまたは nonce が必要で、Mermaid・MathJax との動作確認が要る。
- `WebMessageReceived` で `get_Source()` が `kAppOrigin` と一致することを確認する。
- `NavigationStarting` で `kAppOrigin` 以外を拒否する。`NewWindowRequested` は `Handled=TRUE` にして、外部リンクはユーザー確認のうえ既定ブラウザで開く。

## V-2 画像出力の出力先検証なし (中〜高)

`engine.cpp:499` が `fs::u8path(output_dir) / fs::u8path(prefix + suffix + extension)` でパスを組み立てる。
`prefix` は UI の自由入力 (メッセージ値) で、`..` や区切り文字、絶対パスを検証していない。
`operator/` は右辺が絶対パスなら左辺を置き換える。

- 再現: `prefix = "../escaped"` と `prefix = <絶対パス>/abs_target` で、どちらも `output_dir` の外にファイルが作られた。
- 書き込みは `ofstream(..., trunc)` で、**既存ファイルは確認なしで上書き**される (コード確認、上書き自体は未テスト)。拡張子は `.png` / `.jpg` に限られ、内容は PDF ページのレンダリング結果。
- `handle_export_images` (`main_gui.cpp:1672-1696`) は `output_dir` もメッセージ値をそのまま使う。V-1 と合わせると、無確認で任意フォルダへ書き込める。

修正案:
- `prefix` は `[A-Za-z0-9._-]` 等に限定し、`filename()` が元の文字列と一致しなければ拒否する。
- 結果パスが `output_dir` の配下か (`weakly_canonical` + 前方一致) を確認する。
- 既存ファイルは上書き確認を出す。
- `output_dir` は、ネイティブのフォルダ選択で得たものか、その直前に確認したものだけを受け付ける。

## V-3 暗号化 PDF の保存で暗号化が外れる (中)

`PdfBackend::save` は `FPDF_CreateNewDocument` + `ImportPages` + `FPDF_SaveAsCopy` で書き出す。これは暗号化を引き継がない。

- 再現 (AES-128 のテスト用 PDF、パスワード `secret123`):
  - 「名前を付けて保存」した複製に `/Encrypt` が **ない**。
  - **「上書き保存」で元の暗号化ファイルが非暗号化に置き換わり**、パスワードなしで開けるようになった。
- UI・README・HISTORY のどこにも注意書きがない。

修正案: 暗号化 PDF を開いている場合は、上書き・保存時に「暗号化は保持されません」と確認を出す。上書きは無効化するのが安全。pdfium は暗号化書き込みに対応していない。

## V-4 WebView2 の絞り込みなし (低〜中)

`main_gui.cpp:2045-2050` で設定しているのは `IsZoomControlEnabled(FALSE)` のみ。
製品ビルドでも F12 / Ctrl+Shift+I の DevTools、標準の右クリックメニュー、ブラウザアクセラレータキーが有効なまま。
DevTools は本人の操作なので単体では脆弱性ではないが、V-1 を含め、橋渡しに到達する経路を増やす。

修正案: 製品ビルドで `put_AreDevToolsEnabled(FALSE)`、`put_AreDefaultContextMenusEnabled(FALSE)`、`put_AreBrowserAcceleratorKeysEnabled(FALSE)`、`put_IsStatusBarEnabled(FALSE)`。

## 静的確認のみの項目 (未再現)

- **S-1 メモリ枯渇**: `render_page` の `width` (`main_gui.cpp:1302`、`pdf_backend.cpp:284` は 1 未満のみ拒否) と書き出しの `dpi` (`pdf_backend.cpp:342`) に上限がない。UI の 50〜1200 は画面側の制限のみ。巨大 MediaBox の PDF と高 dpi の組み合わせで数 GB 確保しうる。`extract_int` (`main_gui.cpp:586-592`) は符号付き整数のオーバーフロー (未定義動作)。
  修正案: width・dpi・出力ピクセル数に上限を設ける。
- **S-2 テスト用 TCP API**: `test_api_server.cpp` が製品 exe に含まれる。`QUICKMARKPDF_TEST_PORT` 設定時に `save_as`、`export_pages_to_images`、`extract_text_to_file`、`save_markdown_pdf`、任意パスのオープンが認証なしで使える。環境変数を設定できる攻撃者は既にプロセスを制御できるため低リスクだが、受信バッファに上限がなく、`SO_EXCLUSIVEADDRUSE` も未設定。
  修正案: 製品ビルドから `#ifdef` で除外する。
- **S-3 DLL 検索**: `pdf_backend.cpp:100` の `LoadLibraryW(L"pdfium.dll")` は名前のみで、`SetDefaultDllDirectories` の呼び出しもない。アプリフォルダに DLL が無いとカレントフォルダへ探しに行く。
  修正案: `GetModuleFileNameW` から作ったフルパスで読み込む。
- **S-4 上書き保存**: `engine.cpp:386-413` の一時ファイル名が `<元ファイル>.tmp_quickmarkpdf` で固定。`rename` 失敗時の `copy_file` フォールバックは、コピー失敗時に元ファイルを壊しうる。
  修正案: `ReplaceFileW` / `MoveFileExW(MOVEFILE_REPLACE_EXISTING)` を使う。
- **S-5 パスワード**: `known_passwords_` と pdfium キャッシュ (`pdf_backend.cpp:187-190`) に平文で保持し、CredUI のバッファ (`main_gui.cpp:1000-1012`) もゼロクリアしない。
  修正案: `SecureZeroMemory`、不要になった時点での破棄。
- **S-6 データフォルダ**: `main_gui.cpp:2001-2004` が `%TEMP%\QuickMarkPDF_WVData` を固定で使う。描画内容のキャッシュも Temp に残る。
  修正案: `%LOCALAPPDATA%\QuickMarkPDF` 配下に移す。

## ビルド・供給網

- **B-1**: `scripts/fetch_pdfium.ps1` は GitHub (`bblanchon/pdfium-binaries`、`chromium/8009`)、`scripts/fetch_webview2_sdk.ps1` は NuGet から、ハッシュ検証なしで取得する。`pdfium.dll` はそのまま配布物に入る。
  修正案: SHA-256 を固定して検証する。
- **B-2**: `.github/workflows/codeql.yml` の対象言語は python と cpp のみ。XSS の発生源である `app.js` は解析されない。
  修正案: `javascript-typescript` を追加する。
- **B-3**: `QuickMarkPDF.exe` と `pdfium.dll` は未署名 (`Get-AuthenticodeSignature` が NotSigned)。`SHA256SUMS.txt` は同じリリースに同梱されるため、独立した信頼の根拠にならない。CFG は無効。`scripts/build.py:84` に `-fstack-protector-strong` / `_FORTIFY_SOURCE` がない。`release.yml` の `choco install mingw python` はバージョン未固定で、Actions はタグ固定 (コミット SHA 固定ではない)。
  修正案: コード署名 (`docs/code_signing_policy.md` の方針に沿う)、ツールチェーンと Actions の固定。

## B-4 同梱・依存ライブラリが最新ではない (追記・訂正)

当初の診断書は「問題なしと確認できた点」に「pdfium は 153.0.8009 で新しい」と書いていた。**これは上流の最新版を確認せずに書いた誤り**で、削除した。固定された版数が使われていることは、最新であることの根拠にならない。2026-11-23 に上流で確認し直した結果は次のとおり。

| 部品 | 使用中 | 最新 (確認元) | 差 |
|------|--------|---------------|-----|
| pdfium (pdfium-binaries) | `chromium/8009` (PDFium 153.0.8009.0、2026-08-17) | `chromium/8165` (2026-11-16、GitHub Releases) | 12 リリース、約 3 か月 |
| WebView2 SDK (NuGet) | 1.0.2903.40 (2024-11-18) | 1.0.4370.26 (2026-11-21、安定版、NuGet) | 安定版 24 本、約 2 年 |
| WebView2 Runtime (PC 側、Microsoft が自動更新) | この PC は 157.0.4341.60 | 157 系 (Microsoft の Runtime 157.0.4341.42 は 2026-11-06 の公開) | 最新相当 |
| Mermaid | 11.15.0 | 12.3.0 (2026-11-03、npm)。11 系の修正版は 11.16.1 | 安定版 9 本 |
| MathJax | 3.2.2 (2022-08) | 4.1.3 (2026-07-03、npm) | メジャー更新 |

- pdfium: 8009 から 8165 までのコミットには、`float-cast-overflow` の修正、循環検出の反復化、FaxDecoder の状態リセット修正などが含まれる。リリースノートに CVE・security の記載はなく、特定の脆弱性に該当するかは判断できない。固定していた SHA-256 は、GitHub が公開するダイジェストと一致した (独立した確認)。
- Mermaid 11.15.0 に該当する公開勧告が 5 件ある (2026-08-04 公開、修正版は 11.16.1): アーキテクチャ図のプロトタイプ汚染 (中)、レーダー図の DoS (中)、XY チャートの無限ループ DoS (中)、設定 API のプロトタイプ汚染 (低)、図の外への CSS 注入 (中)。DoS は、悪意ある `.md` で画面を固まらせられる可能性があり、`securityLevel: 'strict'` では防げない。MathJax 3.2.2 に該当する、GitHub で公開された勧告は見つからなかった。
- WebView2 SDK は、ヘッダーと同梱の `WebView2Loader.dll` の元になる。ブラウザ本体は Runtime (利用者の PC) 側なので、SDK が古いこと自体は直接の脆弱性ではない。ただし Runtime の更新で追加される API を使えない。
- 固定の理由: 元のスクリプトが版を固定していた (再現できるビルドのため)。更新の仕組みがなく、そのまま古くなった。今回追加した SHA-256 検証は改ざんの検知であり、版の新しさは保証しない。
- 状況 (2026-11-23 更新): pdfium は `chromium/8165` (PDFium 160.0.8165.0)、WebView2 SDK は 1.0.4370.26、Mermaid は 11.17.2 に更新した。MathJax は 3.2.2 で据え置き (4.x はフォントが別配布のようで、オフラインかつ CSP のもとで描画できるかの評価が先)。Mermaid 12 系も未対応 (メジャー更新)。版が古くなることを防ぐため、`scripts/check_dependency_updates.py` と週次ワークフローを追加した。詳細は `plans/2026-11-23_同梱ライブラリ更新_結果_v1.0.md`。

## 推奨する対応順

1. V-1 のレンダラー修正 (最小 3 点) と Mermaid の `strict` 化。
2. V-2 の `prefix` / `output_dir` 検証。
3. V-1 の防御層 (CSP、送信元検証、ナビゲーション制限) と V-4。
4. V-3 の警告ダイアログ。
5. B-2 (CodeQL に JavaScript 追加)。以後の回帰を CI で拾えるようにする。
6. その他 (S-1〜S-6、B-1、B-3)。

## 検証環境メモ

- 再現スクリプトと中間物は作業用の一時フォルダにのみ作成し、リポジトリへは追加していない。
- 起動した `QuickMarkPDF.exe` は自分が起動した PID のみを `taskkill /PID /T /F` で終了した。`msedgewebview2.exe` を名前で終了していない。終了後に残存プロセスがないことも確認した。
