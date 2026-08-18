# 開発環境

## 現行の採用技術スタック

### 移行後のネイティブ版

- **言語**: C++17
- **GUI**: Microsoft WebView2（HTML/CSS/JavaScript）
- **バックエンド**: C++ PDFエンジンアダプター（選定中）
- **ビルド**: CMake + Visual Studio 2022 Build Tools + Windows SDK
- **UIとC++の連携**: WebView2 WebMessage API（JSONメッセージ）

WebView2 SDKはNuGetパッケージ `Microsoft.Web.WebView2` から取得します。SDK本体はリポジトリへコミットせず、`.gitignore`対象の `third_party/webview2/` に展開します。

現在の `PdfBackend::inspect` は移植初期の暫定検査実装です。PDFエンジン統合後はこのAPIをMuPDFまたはPDFiumの実装へ置き換え、圧縮・暗号化・保存・画像化を正式対応します。

### 移行期間のPython版（比較基準）

- **言語**: Python 3.12 以上
- **GUIフレームワーク**: PySide6 (Qt 6)
- **PDF操作ライブラリ**: PyMuPDF (fitz)
- **画像処理補助**: Pillow
- **配布ツール**: PyInstaller（または Nuitka）

## 主要ライブラリ一覧

| ライブラリ     | 用途                     | バージョン目安 |
|----------------|--------------------------|----------------|
| PyMuPDF        | PDFの読み込み・編集・変換 | 1.24+         |
| PySide6        | デスクトップGUI          | 6.7+          |
| Pillow         | サムネイル生成・画像処理 | 10.0+         |
| PyInstaller    | Windows向けexe化         | 6.0+          |

## 選定理由

- PDF操作の機能性・速度・安定性で **PyMuPDF** が現時点で最も優れている
- サムネイル一覧表示、ドラッグ＆ドロップによるページ並び替え、プレビュー表示など、複雑なUIを比較的作りやすい
- Windowsで実用的なサイズの単一exeにしやすい
- Pythonのため開発速度が速く、ライブラリのエコシステムが成熟している
- 「シンプルなUI」を目指す上で、Qtは十分なコントロールが可能

## Python版の開発環境セットアップ手順

```bash
# 1. Python仮想環境の作成
python -m venv .venv
.venv\Scripts\activate   # Windowsの場合

# 2. 主要ライブラリのインストール
pip install PyMuPDF PySide6 Pillow

# 3. 開発時のみ必要（任意）
pip install PyInstaller

# 4. アプリ起動
python python/main.py
```

## C++ WebView2版のセットアップ

1. Visual Studio 2022 Build Toolsの「C++によるデスクトップ開発」とWindows 10/11 SDKを導入する。
2. `powershell -ExecutionPolicy Bypass -File scripts/fetch_webview2_sdk.ps1` でWebView2 SDKを `third_party/webview2/` に展開する。
3. CMakeでx64のWebView2ホストをビルドする。

```powershell
cmake -G "Visual Studio 17 2022" -A x64 -S core/webview2 -B core/webview2/build
cmake --build core/webview2/build --config Release
```

実行ファイルは `core/webview2/build/Release/QuickMarkPDF_webview.exe`。WebView2 RuntimeがインストールされたWindows 10/11環境で起動します。

## プロジェクト構成

```
QuickMarkPDF/
├── core/
│   ├── native/                    # PDFエンジン非依存のC++モデル
│   └── webview2/                  # WebView2ホスト
├── ui/                            # WebView2で表示するHTML/CSS/JavaScript
├── python/
│   ├── main.py                    # エントリーポイント
│   └── src/                       # Pythonソース
├── requirements.txt
├── document/
│   ├── spec.md                    # 仕様書
│   └── environment.md             # 本ファイル
├── resources/
│   └── icons/                     # ツールバー用PNGアイコン（Pillowで自動生成）
│   └── src/pdf_editor/
│       ├── pdf/
│       │   └── pdf_manager.py     # PDF読み込み・編集・保存・キャッシュ
│       └── ui/
│           ├── main_window.py     # メインウィンドウ・ツールバー・プレビュー
│           └── thumbnail_panel.py # サムネイルツリー（QTreeWidget）
└── tests/
```

## UIアーキテクチャ概要

- **QMainWindow** → 上部ツールバー + 中央ウィジェット
- **中央ウィジェット** → QSplitter（水平）で左右分割
  - 左: `ThumbnailPanel`（QTreeWidget サブクラス）
  - 右: QScrollArea + QLabel（プレビュー）
- **ThumbnailPanel** のカスタム要素:
  - `_ThumbnailDelegate`: ファイルヘッダーと各ページ行で異なる行高さを管理。ページ行は独自 `paint()` で描画（`iconSize()` に依存しない）
  - サムネキャンバスは `(icon_w × 実際の画像高さ + TEXT_H)` の可変高さ。横長ページも余白なし
  - `Qt.UserRole` = ページインデックス、`Qt.UserRole + 1` = キャンバス高さ（デリゲートが参照）
  - パネル幅 = `icon_w + 2 × indent + scrollbar_margin`（Qt の rootIsDecorated=True により子アイテムは 2×indent ぶん右にオフセットされるため）

## PDFManagerの主要な設計

| メソッド | 役割 |
|---------|------|
| `load_pdfs` | 複数PDFを開き、`all_pages` / `page_infos` を構築 |
| `reorder_pages` | ページ順序をリストで指定して並び替え |
| `rotate_page` | 指定ページを回転（キャッシュ無効化付き） |
| `get_thumbnail_pixmap` | サムネ生成（スケール1回・キャッシュ利用） |
| `get_preview_pixmap` | プレビュー用高解像度レンダリング |
| `save_as` | 全ページを新しいPDFとして出力 |
| `save_selected_pages` | 選択ページのみを新しいPDFとして出力 |

## サムネイルキャッシュ設計

- キー: `(id(page), max_size, page.rotation)`
- 無効化タイミング: 回転・全ページ閉じ
- 並び替えはページオブジェクトの参照を並び替えるだけなので `id()` が変わらずキャッシュはそのまま有効

## 配布方法（予定）

- PyInstallerを使ってWindows向け単一exeファイルを作成
- 必要に応じてNuitkaへの移行も検討

## 備考

- 現時点ではWindowsを最優先ターゲットとする
- 将来的にmacOS/Linux対応が必要になった場合は、PySide6のクロスプラットフォーム性を活かして対応可能
