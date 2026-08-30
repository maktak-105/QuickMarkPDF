# QuickMarkPDF バージョン情報

## バージョン

Ver. v3.0.0

## コンセプト

無料、広告無し、寄付無し、課金無し。シンプルなWindowsデスクトップ向けPDFページ編集ツールです。
分割・結合・並べ替え・回転・書き出しといった、必要最小限のページ単位の編集に絞っています。
おまけとして、Markdown（Mermaid図・数式（MathJax、TeX記法）対応）をPDFへ書き出す機能も備えています。

## 表示言語

画面は日本語のみです。アプリ内の言語切替はありません。

## 開発環境

- C++17（MinGW-w64 / g++、WinLibs MCF UCRT）
- WebView2（Microsoft Edge WebView2 Runtime）
- PDFium（ページ描画・編集）
- Windows Imaging Component（JPEGエンコード）
- Win32 API（`IFileDialog` / `GetOpenFileNameW` / `GetSaveFileNameW`、TaskDialog）

フロントエンド（HTML/CSS/JS）はフレームワーク非依存です。PDFium 以外の
サードパーティ C++ ライブラリ依存はありません。

## 現在の位置づけ

`core/native/`（C++17 + WebView2版）が製品として出荷される版です。
`python/prototype/`（PySide6版）は開発中の挙動評価に使う試作・評価用プロトタイプであり、
製品として配布されません。ビルド手順、一度目の移植の破棄、ページ編集挙動の比較 QA は
[`environment_jp.md`](environment_jp.md) を参照してください。

## 第三者ソフトウェア

GUI に同梱するもの:

- PDFium（`pdfium.dll`）
- Microsoft WebView2 Loader（`WebView2Loader.dll`）
- Mermaid.js（MIT）
- MathJax（Apache License 2.0）

WebView2 Runtime 自体は同梱しません。

## 制作者

GitHub: [maktak-105](https://github.com/maktak-105)

`Copyright (c) 2026 maktak-105 (GitHub: https://github.com/maktak-105)`

## 免責事項

QuickMarkPDFは独立したソフトウェアであり、Adobe・Microsoftその他いかなるサードパーティのソフトウェアベンダーとも提携・承認関係にありません。
