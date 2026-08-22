# C++ Markdownモード 実施結果 v1.0

実施日: 2026-08-20
対応する計画書: なし（残課題の継続対応。Python版で最後まで残っていた大きな機能領域）

## 1. 実施内容

Python版が持つ「PDF編集」と「Markdownプレビュー」の2モードのうち、Markdown表示モードをC++版に追加した。

1. `webview_main.cpp`:
   - `json_string()` に制御文字（改行・タブ等）のエスケープを追加（Markdown本文は複数行の任意テキストであり、既存の実装はバックスラッシュとダブルクォートしかエスケープしておらず、JSONとして壊れる状態だった）。
   - `prompt_open_pdfs()` を `prompt_open_documents()` に改名し、ファイルダイアログのフィルタにMarkdown（`*.md`/`*.markdown`）を追加。
   - `open_pdf_paths()` を `open_document_paths()` でラップし、渡されたパスにMarkdownファイルが含まれる場合は最初の1件を優先してMarkdownとして開く（Python版の「PDF/Markdown混在はエラー」という厳密な挙動は簡略化し、未実装）。
   - `open_markdown_path()` を新規実装: ファイルをUTF-8として読み込み、`{"type":"markdown_opened","path":...,"content":...}` をフロントエンドへ送信。
   - コマンドライン引数の起動時オープンも `.md`/`.markdown` に対応。
2. `templates/index.html`: `#markdown-workspace`（`#markdown-content`）を新規追加。既存のPDFワークスペースと排他的に表示する。
3. `static/js/app.js`:
   - `markdownToHtml()` を新規実装: 見出し・段落・太字/斜体・インラインコード・コードブロック・引用（再帰対応）・単純な箇条書き/番号付きリスト・リンク・画像・水平線に対応した、自作の簡易Markdown→HTML変換器。CommonMark完全準拠ではない。本文は先にHTMLエスケープしてから変換するため、Markdown内の生HTMLはそのまま実行されずリテラル表示される（Python版の`Markdown`パッケージは生HTMLを許容するため、ここは意図的な簡略化かつ安全側の判断）。
   - `setMode('pdf'|'markdown')` を新規実装し、PDFツールバー項目（回転・削除・元に戻す・PDF切り出し・画像出力・保存）をMarkdownモード中は無効化。
4. **実装中に見つけた実バグを1件修正**: `[hidden]`属性と`.workspace`/`.markdown-workspace`の`display`宣言が同じ詳細度(0,1,0)を持つため、後から書かれた作者スタイルの`display:grid`/`flex`が`[hidden]`の既定`display:none`を上書きしてしまい、モード切り替え時に両方のワークスペースが重なって表示される不具合があった。`.workspace[hidden], .markdown-workspace[hidden] { display: none; }` を明示的に追加して修正。

## 2. 検証結果（実際に見た内容）

- CLI引数で`.md`ファイルを渡して起動→ダイアログを経由せず自動的にMarkdownモードで表示されることを確認。見出し（下線付きh1/h2）・太字と斜体の組み合わせ・インラインコード（背景色付き）・リンク（青下線、実際にクリック可能なスタイル）・コードブロック（等幅フォント＋背景）・引用（背景色ボックス）・箇条書きリストが、いずれも意図通りにレンダリングされることをスクリーンショットで確認。
- 上記確認の過程で `[hidden]` のCSS不具合（PDFワークスペースがMarkdown表示の背後に残って表示される）を発見し、修正後に再確認して解消したことを確認。
- Markdown表示中、PDF専用のツールバーボタン（回転・削除・元に戻す・PDF切り出し・画像出力・保存）がすべて無効化（グレーアウト）されることを確認。
- Markdown表示中に「開く」ボタンからPDFファイルを選択→自動的にPDFワークスペースに切り替わり、サムネイル一覧・プレビュー・全ツールバーボタンが正常に復帰することを確認（双方向の切り替えを確認）。

## 3. 残課題

- **Mermaid・MathJaxのレンダリングは未実装。** Python版は`resources/vendor/mermaid/mermaid.min.js`・`resources/vendor/mathjax/tex-svg.js`をベンダリングして使用している。C++版でも同じJSライブラリをWebView2側に組み込むことで対応可能と考えられるが、今回は着手していない。
- **MarkdownからのPDF書き出しは未実装。** Python版はQtWebEngineの`printToPdf`相当機能を使用しており、C++版ではWebView2の`ICoreWebView2_7::PrintToPdf` APIで対応可能と考えられるが未着手。
- テーブル（GFM形式）の変換は未対応（CSSは用意済みだがパーサ未対応）。
- ネストしたリスト（リストの中にリスト）は非対応。
- 複数のMarkdownファイル・PDF/Markdown混在時のPython版の厳密な挙動（エラーメッセージ）は簡略化されている。
