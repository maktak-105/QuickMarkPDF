# QuickMarkPDF プロジェクト仕様書

[English spec.md](spec.md)

## 概要

Windows向けのデスクトップPDF編集ツール。複数のPDFを読み込み、ページ単位で編集・並べ替え・保存します。

## 実装済み機能

- 複数PDFの読み込み、連結、分割保存
- ページのドラッグ＆ドロップによる並べ替えとファイル間移動
- ページ単位の回転
- サムネイルとプレビュー表示
- Markdown、Mermaid、MathJaxのオフラインプレビュー
- PNG/JPGへのページ画像エクスポート
- 未保存変更、Undo、バックグラウンド処理への対応

## 技術スタック

- Python 3.12+
- PySide6
- PyMuPDF
- Pillow
- PyInstaller
