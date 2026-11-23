# 計画書: Markdown 内の安全な HTML を表示できるようにする (v1.1)

## 改版履歴
- v1.0: 初版 (`plans/2026-11-23_Markdown内HTML許可_v1.0.md`、旧版として残す)。
- v1.1: ユーザー指示により、許可リストにない HTML の扱いを「文字として表示」から「**破棄**」に変更。それ以外は v1.0 のまま。破棄の具体的な規則 (中身ごと消すもの、タグだけ消すもの、文字のまま残すもの) を設計の節に追加し、検証とリスクと決定事項を更新した。

## 目的
Markdown ファイルに書かれた HTML のうち、脆弱性に関わらないもの (`<br>`、`<b>`、`<details>`、`<img width=…>`、HTML の表など) を、文字としてではなく HTML として表示する。危険なもの (スクリプト、イベント、スタイル、フォーム、フレームなど) は、これまでどおり絶対に実行・反映しない。

## 現状分析
- `src/ui/js/markdown.js` は、ソース中の `<` `>` `"` `'` `&` をすべてエスケープし、タグを文字として見せる。例外は、改ページ用の単独行 `<div style="page-break-…">` だけ。コードブロックとインラインコードは対象外 (そのままコード表示)。
- 実際に動かして確認済み (前回の会話): `<br>`、`<b>`、`<details>`、HTML コメントなどは、すべてタグの文字が見える。旧版 (v4.2.0) と同じ挙動。
- 画面で解釈される HTML は、すべて `markdown.js` が自分で生成した文字列だけ (属性は許可リスト、値はエスケープ済み)。この性質は崩さない。
- 参考にした許可リスト: GitHub が README に許可している HTML (`gjtorikian/html-pipeline` の `sanitization_filter.rb` で確認)。要素 66 個、`class` と `style` は属性に含まれない。今回はそれをさらに絞る。

## 許可する候補 (選定結果)
GitHub の許可リストを目安に、このアプリで安全に扱えるものだけを選んだ。

| 区分 | 要素 | 許可する属性 |
|------|------|--------------|
| 文字の装飾 (インライン) | `b` `strong` `i` `em` `u` `s` `strike` `del` `ins` `mark` `small` `sub` `sup` `kbd` `code` `tt` `samp` `var` `cite` `q` `dfn` `span` `wbr` `br` | なし |
| 略語・ルビ | `abbr` (`title`)、`ruby` `rt` `rp` (振り仮名) | `title` のみ |
| リンク・画像 | `a`、`img` | `a`: `href` (http・https・mailto・# のみ)、`title`。`img`: `src` (http・https・base64 の画像のみ)、`alt`、`width`・`height` (数字、`%` または `px`)、`title`、`align` |
| 文章の構造 | `p` `div` `center` `h1`〜`h6` `hr` `blockquote` `pre` `ul` `ol` `li` `dl` `dt` `dd` `details` `summary` `figure` `figcaption` | `align` (`left` `right` `center`)、`ol` の `start` (数字)、`details` の `open` |
| 表 | `table` `caption` `thead` `tbody` `tfoot` `tr` `th` `td` | `align`、`th`・`td` の `colspan`・`rowspan` (数字) |
| HTML コメント | `<!-- … -->` | 表示せずに取り除く (通常の Markdown と同じ) |

許可しないもの (**破棄される**。具体的な規則は設計の節のとおり):
- 要素: `script` `style` `link` `meta` `base` `iframe` `frame` `object` `embed` `applet` `form` `input` `button` `select` `textarea` `label` `svg` `math` `canvas` `video` `audio` `source` `picture` `dialog` `template` `noscript` `marquee` `title` `head` `body` `html` など、上の表にない要素すべて。
- 属性: `on…` (イベント)、`style`、`class`、`id`、`name`、`srcdoc`、`formaction`、`data-*`、`xlink:*`、`target`、`rel`、`longdesc`、`loading`、`srcset`、`accesskey`、`tabindex`、`aria-*`、`role` など、上の表にない属性すべて。
- 理由: `class` と `style` は、アプリの UI の見た目になりすます (画面全体を覆う、偽のダイアログを出す) ために使える。`id` と `name` は、ページ内の変数 (`window.MathJax` など) を上書きする攻撃 (DOM clobbering) に使える。`target` と `rel` は、こちらが固定値を付ける。

## 設計
- 方式: 自前の厳格な字句解析。ブラウザの HTML パーサーには通さない。タグを見つけたら、要素名と属性を許可リストと照合し、**出力はこちらが作り直す** (入力をそのまま通さない)。許可リストにない要素・属性は**破棄する**。規則は次のとおり。
  - **中身ごと破棄する要素**: `script` `style` `iframe` `frame` `frameset` `object` `embed` `applet` `template` `noscript` `noembed` `noframes` `textarea` `title` `head` `select` `svg` `math` `canvas` `audio` `video` `xmp`。開きタグから、同じ段落・同じ HTML ブロックの中にある対応する閉じタグまでを消す。閉じタグが見つからないときは、開きタグだけを消し、残りは通常の文字として扱う (文書の残りを巻き込んで消さないため)。
  - **タグだけ破棄する要素** (中の文字は残す): 上記以外の、許可リストにない要素 (`font` `form` `input` `button` `label` `marquee` `picture` `source` `link` `meta` `base` `html` `body` など)。
  - **属性だけ破棄**: 許可する要素に付いた、許可リストにない属性、または値が条件に合わない属性 (`<div class="x" onclick="…">` は `<div>` になる)。`<a>` は、`href` が許可されない場合はタグごと破棄して中の文字だけ残す。`<img>` は、`src` が許可されない場合は丸ごと破棄する。
  - **タグの形で、文法に合わないもの** (`<img/src=x/onerror=…>`、引用符のない値、制御文字を含むものなど。`<` の直後が英字・`/`・`!`・`?` で、同じ行に `>` があるもの): 丸ごと破棄する。コメント `<!-- … -->`、`<!DOCTYPE …>`、`<?…?>`、`<![CDATA[…]]>` も破棄する。
  - **そのまま文字として残すもの**: `<` の直後が空白・数字・`=` などで、タグの形でないもの (`1 < 2`、`a <= b`)。コードブロック・インラインコード・数式 `$…$` の中。
- 値の扱い: `href`・`src` は既存の `sanitizeLinkUrl`・`sanitizeImageUrl` を使う。`width`・`height`・`colspan`・`rowspan`・`start` は数字だけ。`align` は `left`・`right`・`center` のときだけ、固定のクラス (`align-left` 等) に変換して出す (`style` は出さない)。文字列の値はすべてエスケープする。
- 構造: 要素の開き・閉じを、スタックで対応づける。文書の終わりや、ブロックの切れ目で、閉じていない要素は自動で閉じる。対応のない閉じタグは捨てる。入れ子は 20 段まで。1 行あたり・文書あたりのタグ数に上限を設ける。
- ブロック要素: 行の先頭にある、ブロックの開き・閉じタグ (`<div align="center">`、`<details>`、`<summary>…</summary>`、`<table>` など) は、その場で出力し、間にある行は通常どおり Markdown として処理する。`p` と `center` は内部で `div` 相当に変換し、`<p>` の入れ子を避ける。単独行の改ページ用 `<div>` は、これまでどおり専用処理を優先する。
- インライン要素: 段落・リスト項目・表のセル・見出しの中のタグは、`renderInline` の中で処理する。コードスパンの中と、数式 `$…$` の中は対象外 (そのまま文字)。
- 変更するファイル: `src/ui/js/markdown.js`、`src/ui/css/style.css` (`align-*` と表・`details` の見た目)、`tests/markdown_render_test.js`、`docs/spec.md` と `docs/spec_jp.md` (許可する HTML の説明を追記)。CSP と WebView2 側 (C++) は変更しない。

## 検証方法
1. 出力検証器 (`assertSafeHtml`) を、新しく許可する要素・属性に合わせて広げる。許可リストの外の要素・属性、危険な値が 1 つでも出たら失敗する。
2. 攻撃文字列を追加する: `<a href="javascript:…">`、`<img/src=x/onerror=…>`、大文字小文字の混在、`<svg onload>`、`<math>`、`<noscript><p title="</noscript><img src=x onerror=…>">` のような入れ子の細工、属性値の中のエンティティ (`&#x6a;avascript:`)、`<style>`、`<form>`、閉じていない引用符、`class`・`style`・`id`・`name` を付けた要素、`<a>` や `<img>` の `target`・`rel`。すべて無害化されること (危険な要素は中身ごと、許可外の要素はタグだけが消え、危険な文字列が画面に残らないこと)。
3. ランダム入力のファズに、新しい要素名・属性名・記号の断片を加えて 30,000 件以上を流し、出力が検証器を通ること。
4. 通常の出力のテスト: `<br>`、`<b>`、`<details>`、`<img width=…>`、`<p align="center">` で囲んだ画像、HTML の表、ルビ、HTML コメントが、期待どおりの HTML になること。コードブロック・インラインコード・数式の中の HTML は、文字のままであること。
5. 旧実装 (v4.2.0) との比較: リポジトリの `.md` で、HTML を含まない文書の出力が変わらないこと。
6. 実際の WebView2 (テスト用ビルド): 安全な HTML の文書が表示され、攻撃文字列を含む文書では CSP 違反もスクリプト実行も起きないこと。`tests/e2e/security_regression.py` が全件成功のまま。Markdown → PDF の書き出しで、表・画像・`details` が崩れないこと。
7. 破棄の規則のテスト: 中身ごと消える要素 (`<script>alert(1)</script>` のコード文字が残らない、閉じタグがなければ開きタグだけが消える)、タグだけ消える要素 (`<font color=red>text</font>` が `text` になる)、属性だけ消える場合 (`<div class="x" onclick="…">` が `<div>`)、`1 < 2` と `a <= b` が文字のまま残ること、コード・数式の中の HTML が文字のままであること。
8. `python scripts/build.py all` で本番ビルドを作り、`dist` を更新する (起動中のインスタンスがあれば、終了をお願いします。こちらからは終了させません)。

自動化できず検証できない範囲 (結果文書に明記する): 画面での見た目の細かい調整 (表の罫線・余白など)。

## リスク
- 字句解析の抜け (文法の例外) で、危険なタグが通る恐れ。入力をそのまま通さず、出力を作り直す設計と、検証器・ファズで抑える。
- 閉じていない要素や大量のタグで、画面の構造が崩れる、または重くなる恐れ。自動で閉じる、段数とタグ数の上限、で抑える。
- HTML ブロックの中の Markdown は、完全な CommonMark の挙動にならない (行単位の処理のため)。複雑な入れ子の HTML は、意図どおりに並ばないことがある。
- 画像のタグで、外部サーバーへの通信 (読み込み) が起きる。これは Markdown の画像記法と同じで、CSP は https の画像を許可している。
- 画面の見た目: `details`、表、`align` の見た目を追加する CSS が、既存の UI に影響しないこと。Markdown 表示の中だけにかかるセレクターにする。
- 破棄は書いた内容を消す。文中に `a<b>c` のような「タグの形」の文字を書くと、タグとして扱われて消える。比較の `<` は、前後に空白を入れるか、`&lt;`、バッククォートで囲む必要がある。許可外の要素・属性が黙って消えるため、画面に見えない内容が出る。この性質は仕様書に明記する。
- 範囲が広い。計画外の変更が必要になったら、いったん止めて計画書を改版する。

## 決定事項 (ユーザー指示)
1. 許可リストにない HTML は**破棄する** (文字としては表示しない)。
2. HTML コメントは表示しない。
3. 表・`details`・`div` などのブロック要素も今回まとめて対応する。

上記以外は v1.0 の提案のまま。
