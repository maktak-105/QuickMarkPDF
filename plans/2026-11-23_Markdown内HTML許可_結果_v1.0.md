# 結果: Markdown 内の安全な HTML の表示 (v1.0)

対応する計画書: `plans/2026-11-23_Markdown内HTML許可_v1.1.md` (承認済み。v1.0 は旧版)。

## 実施内容
- `src/ui/js/markdown.js` を書き直した。HTML は「通さずに作り直す」方式。自前の厳格なタグ解析 (開き・閉じ・コメント・不正な形) で、要素と属性を許可リストと照合し、出力は常にこちらが生成する。
  - 許可: 文字の装飾、`a`、`img`、`p`/`div`/`center`、見出し、`hr`、`blockquote`、`pre`、リスト、`dl`、`details`/`summary`、`figure`、表、ルビなど (計画書の表のとおり)。
  - 中身ごと破棄: `script` `style` `iframe` `object` `embed` `svg` `math` ほか (同じ段落内の対応する閉じタグまで。閉じタグがなければ開きタグだけ)。
  - タグだけ破棄: 上記以外の許可外の要素 (`font` `form` `input` など。中の文字は残る)。
  - 属性: 許可外の属性は破棄。`class` `style` `id` `name` `on*` `target` `rel` は一切通さない。`align` は固定クラス (`align-left|center|right`) に変換。
  - HTML コメント・`<!DOCTYPE>`・`<?…?>`・`<![CDATA[…]]>` は表示せずに削除。
  - コードブロック・インラインコード・`$…$` の中は、これまでどおり文字のまま。
  - 上限: 入れ子 20 段、1 テキストあたり 2000 タグ、1 タグ 2048 文字。閉じタグの探索にも予算を設けた。
- `src/ui/css/style.css`: `.align-*`、`details`/`summary`、`figure`、`dl`、`mark`、`kbd` などの画面用スタイルと、印刷用スタイルを追加。印刷では閉じた `details` の中身も出す (`details::details-content`)。
- テスト:
  - `tests/support/safe_html.js` (新規): 出力検証器。許可外の要素・属性・値が 1 つでも出たら失敗。
  - `tests/markdown_html_test.js` (新規): 11 項目。攻撃文字列 77 件、ランダム入力 30,000 件、巨大入力の速度。
  - `tests/markdown_render_test.js`: 検証器を共有版に置き換え。
  - `tests/e2e/security_regression.py`: 実機で「許可タグは表示され、script・イベント・style・class は消える」確認を追加 (16 項目になった)。
- `.github/workflows/ci.yml` / `release.yml`: Node のテスト 2 本を実行するようにした。`docs/environment.md` / `_jp.md`: テスト一覧を更新。
- `docs/spec.md` / `docs/spec_jp.md`: 「Markdown 内の HTML」の節を追加し、機能一覧の行を更新。CSP と WebView2 側 (C++) は変更していない。

## 検証結果 (実行して確認したもの)
| 検証 | 結果 |
|------|------|
| `node tests/markdown_render_test.js` | 11 項目すべて成功 |
| `node tests/markdown_html_test.js` | 11 項目すべて成功 (攻撃 77 件、ランダム 30,000 件、巨大入力) |
| 旧実装 (git HEAD の `markdown.js`) との比較 | リポジトリの `.md` 61 件のうち 59 件は出力が完全に同一。異なる 2 件は `README.md` / `README_jp.md` で、先頭の `<p align="center"><img src="assets/…png">` の扱いだけが違う (下記「制限事項」) |
| 実機 (テスト用ビルド) `tests/e2e/security_regression.py` | 16 項目すべて成功。MathJax・Mermaid が CSP 下で描画され CSP 違反 0 件、HTML の確認も成功 (`details` 1 件、summary 表示、script・イベント属性・本文由来の `style`・`class` は 0 件、`document.title` は書き換わらず) |
| 実機の Markdown → PDF 書き出し (中央寄せ・画像・表・`details`・攻撃文字列入りの文書) | 書き出し成功。PDF から抽出したテキストに、題名・中央寄せの文・表のセル・`details` の見出しと中身が含まれ、攻撃用の文字列 (`pwned`、`document.title`) は含まれなかった |
| ブラウザーでの表示確認 (CSP を付けた検証ページ) | 許可した HTML は表示され、攻撃文字列を含む文書でスクリプト実行は起きなかった |

## 計画からの差異と、判明した事実
1. **引用符のない属性値と、大文字小文字の混在は、拒否せず受け付ける**。計画書は「引用符のない値」を文法違反で丸ごと破棄するとしていたが、実装は `<IMG SRC="…" WIDTH=50>` や `<b class=x>` を受理し、許可した属性だけで作り直す。出力は検証器とファズで確認済みで、安全性への影響はない。
2. **相対パスの画像は破棄される**。`src` は http・https・base64 画像だけ許可するため、`<img src="assets/logo.png">` は消える。これにより `README.md` / `README_jp.md` の先頭のロゴは、旧版では `<p align="center"><img …>` の文字として見えていたものが、今回は何も表示されず、空の中央寄せ `<div>` が残る。ローカル画像の表示は今回の範囲外。
3. **タグに見える文字はタグとして読まれる**。`a<x>c` は `ac` になり、`a<b>c` は `<b>` が許可要素なので段落の残りが太字になる。`if a<b then c>d` のように `<…>` の中に文字があると、その部分 (`then c`) が消える。仕様書は当初 `a<b>c` が消えると書いていたため、実挙動に合わせて `spec.md` / `spec_jp.md` を直した。
4. **閉じタグが段落をまたぐ `<script>` は、中身の文字が残る**。例: `<script>alert(1)` (空行) `still visible?</script>` は、開きタグと閉じタグだけが消え、`alert(1)` と `still visible?` が文字として表示される。実行はされない (計画書の「閉じタグが見つからないときは開きタグだけを消す」どおり)。
5. **閉じた `details` の中身は PDF に印刷される**。印刷用に中身を展開する CSS を入れたため。実機の書き出しで確認済み。

## 未確認・残課題
- 実機の画面での見た目の細かい調整 (表の罫線・余白・`details` の開閉の見え方) は、人の目での確認が必要で、自動検証していない。
- 複雑な HTML (入れ子の表、リスト内のブロックなど) は、行単位の処理のため完全な CommonMark / ブラウザーの挙動にはならない。
- ローカルの相対パス画像の表示は未対応。
- この結果の時点でコミットはしていない。
