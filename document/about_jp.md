# QuickMarkPDF バージョン情報

[English about.md](about.md)

## バージョン

Ver. v1.1.0

## コンセプト

広告も寄付要求もない、シンプルなWindowsデスクトップ向けPDFページ編集ツールです。
分割・結合・並べ替え・回転・書き出しといった、必要最小限のページ単位の編集に絞っています。
おまけとして、Markdown（Mermaid図・数式（MathJax、TeX記法）対応）をPDFへ書き出す機能も備えています。

## 開発環境

- C++17（MinGW-w64 / g++、WinLibs MCF UCRT）
- WebView2（Microsoft Edge WebView2 Runtime）
- PDFium（ページ描画・編集）、Windows Imaging Component（JPEGエンコード）

PDFium以外のサードパーティC++ライブラリ依存なし。フロントエンド（HTML/CSS/JS）もフレームワーク非依存です。

## 現在の位置づけ

`python/`（PySide6版）は開発中の挙動評価に使う試作・評価用プロトタイプであり、製品として配布されるものではありません。
`core/native/`（C++17 + WebView2版）が製品として出荷される版です。両者のパリティを数値で検証するQAの仕組みも含め、
詳細は[`environment_jp.md`](environment_jp.md)を参照してください。

## 制作者

GitHub: [maktak-105](https://github.com/maktak-105)

## 免責事項

QuickMarkPDFは独立したソフトウェアであり、Adobe・Microsoftその他いかなるサードパーティのソフトウェアベンダーとも提携・承認関係にありません。
