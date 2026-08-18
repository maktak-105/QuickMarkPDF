# PDF Editor 改善実装プラン (ヘッダー/フッター仕様厳守)

## 1. Context（背景・目的）

以前のコード解析で指摘した主な改善点のうち、**1〜7**を対象としたリファクタリング/改善の実施プランを作成する。

ユーザーの指示:
- **ヘッダー/フッターの仕様は完全にそのまま**とする。
  - PDFページ内容への直接的な文字列挿入（`insert_text` + `add_header_footer`）
  - 削除時は元PDFファイルからの再読込 + 回転の再適用（`remove_header_footer`）
  - ダイアログのUI仕様、適用タイミング、結果の見た目
- これにより `PDFManager.add_header_footer` / `remove_header_footer` の公開インターフェースと**セマンティクスは一切変更しない**。
- その他の領域（アーキテクチャ、保守性、堅牢性、開発体験）を改善し、長期的なメンテナンス性を高める。

対象改善点（前の解析より）:
1. Architecture & Separation of Concerns
2. State & Undo（最小限のdirty状態 + 終了時確認。HFの「undo」は現状のremoveロジックのまま）
3. Resource & Path Handling
4. Error Handling & Observability
5. Drag & Drop & Selection Complexity（複雑さの整理）
6. Performance & Memory（スレッド化・明示化中心）
7. Testing & Maintainability

## 2. 推奨アプローチ（全体方針）

- **インクリメンタル（段階的）**：各フェーズを小さくし、ビルド・手動テスト・HF機能の回帰確認を挟みながら進める。
- **HF厳守**：HF関連の処理フローはブラックボックスとして扱い、呼び出し側（MainWindow）と実装側（PDFManager）の契約を維持。
- **Qtイディオムを尊重**：シグナル/スロット、イベントフィルタは基本維持。無理なMVC化はせず、実用的なレイヤー分割。
- **最小変更原則**：既存の公開API（PDFManagerのメソッド、ThumbnailPanelのシグナル/メソッド）をできる限り変えない。
- **ログとエラー**：`print` を廃止し、`logging` モジュールへ移行。将来的にファイル出力も容易に。
- **リソース一元化**：main.py の `resource_path` を基盤にし、UI側からも安全に使える形に。

**フェーズの優先順**:
Phase 1（基盤・低リスク）→ Phase 2（構造整理）→ Phase 3（状態管理）→ Phase 4（並列化）→ Phase 5（その他整理 + テスト）

## 3. フェーズ別詳細

### Phase 1: 基盤整備（Resource / Logging / Error Handling）
**目的**: すぐに死ぬ脆い部分と、運用時の可観測性を最優先で直す。

- **Resource Path の一元化**
  - `main.py` の `resource_path` を `src/pdf_editor/utils/resources.py`（または `core/resources.py`）に移動・一般化。
  - `main_window.py` の `_load_icon` をこの新ユーティリティ経由に置き換え（相対パス地獄を撲滅）。
  - アプリ起動時のアイコン設定も統一。
  - `generate_icon.py` をクロスプラットフォーム対応（Windowsフォントパスをフォールバック付きに）。

- **Logging の導入**
  - プロジェクト全体で `logging.getLogger(__name__)` を使用。
  - PDFManager / MainWindow / ThumbnailPanel のエラー・情報ログを `print` から置き換え。
  - 現時点ではコンソール出力で十分（後で RotatingFileHandler 追加可能）。

- **Error Handling の改善**
  - 裸の `except Exception` にログ + 可能ならユーザ向けメッセージを追加。
  - 保存・エクスポート失敗時に詳細をステータスバーやダイアログに反映（現在はほとんどprintのみ）。

**影響ファイル**:
- 新規: `src/pdf_editor/utils/resources.py`
- `main.py`
- `src/pdf_editor/ui/main_window.py`
- `src/pdf_editor/pdf/pdf_manager.py`
- `src/pdf_editor/ui/thumbnail_panel.py`
- `generate_icon.py`
- `pdf_editor.spec`（必要に応じて hiddenimports 追加）

**再利用する既存コード**:
- `main.py:15` の `resource_path` 関数（ロジックを移す）
- `PDFManager` 内の各メソッドのエラーハンドリング箇所（print部分を logger に）

### Phase 2: UI構造の整理（ダイアログ分離 + MainWindow肥大化対策）
**目的**: 1. Architecture & Separation of Concerns の第一歩。テストしやすく、読みやすく。

- `HeaderFooterDialog` と `ExportDialog` を `src/pdf_editor/ui/dialogs/` ディレクトリに移動（独立ファイル化）。
  - クラス名はそのまま、インポートパスを更新。
  - `main_window.py` から削除し、`from .dialogs.header_footer_dialog import HeaderFooterDialog` の形に。
- `main_window.py` 内のプライベートメソッド整理（_refresh_after_hf などはそのままでも可だが、大きなハンドラはコメントで役割を明確に）。
- 将来的にツールバー生成部分を別クラス（例: `MainToolBar`）に抽出する余地を残す（このフェーズでは最小限）。

**HF制約**:
- `edit_header_footer` メソッドの呼び出しフロー、`HeaderFooterDialog` の結果処理（`_RESULT_DELETE` を含む）、`add_header_footer` / `remove_header_footer` への引数渡しは**完全に同一**に保つ。

**影響ファイル**:
- 新規ディレクトリ + ファイル:
  - `src/pdf_editor/ui/dialogs/__init__.py`
  - `src/pdf_editor/ui/dialogs/header_footer_dialog.py`
  - `src/pdf_editor/ui/dialogs/export_dialog.py`
- `src/pdf_editor/ui/main_window.py`（大幅に短くなる）
- `pdf_editor.spec`（hiddenimports に新しいモジュール追加）

**再利用する既存コード**:
- `main_window.py:23-138` の `HeaderFooterDialog` 全体（ほぼそのまま移動）
- `main_window.py:140-324` の `ExportDialog` 全体（ほぼそのまま移動）
- `main_window.py:822-854` の `edit_header_footer` および `_refresh_after_hf`（呼び出し側は変更最小）

### Phase 3: 状態管理の最小改善（Dirty Flag + 終了時確認）
**目的**: 2. State & Undo に対応。HFの「元に戻す」ロジックは現状の `remove_header_footer` に任せ、アプリレベルの「未保存」保護を追加。

- `MainWindow` に `self._is_dirty = False` を導入。
- 以下の操作で dirty を立てる：
  - `load_pdfs` 成功後
  - `reorder_pages` 後
  - `rotate_page` 後
  - `add_header_footer` / `remove_header_footer` 後（HF変更もdirty対象）
  - `save_pdf` / `save_selected` 成功後 はクリア
- `closeEvent` をオーバーライドし、dirty かつ 未保存なら `QMessageBox.question` で確認。
- 現状の `save_pdf` が「名前を付けて保存」専用である点を考慮（「上書き保存」概念はないので、保存成功 = dirtyクリアで問題なし）。

**HF制約**:
- HF適用・削除の内部処理は一切変えない。ただ「dirtyを立てる」呼び出しを追加するだけ。
- `remove_header_footer` 後も dirty のまま（またはユーザが「変更した」とみなす）で良い。ユーザの意図に合わせる。

**影響ファイル**:
- `src/pdf_editor/ui/main_window.py`（主に `__init__`、各種操作ハンドラ、closeEvent 新規追加）

**再利用する既存コード**:
- 既存の save 成功時のステータス更新ロジック
- `pdf_manager.get_page_count()` などによるガード

### Phase 4: 長時間処理のスレッド化（Performance & ユーザ体験）
**目的**: 4. Error Handling / 6. Performance に対応。大きなPDFや画像エクスポートでUIが固まる問題を解消。

対象処理:
- `open_pdfs` 内の `pdf_manager.load_pdfs`
- `export_images` / `_on_image_extract_requested` 内の `export_pages_to_images`
- `save_pdf` / `_export_selected_as_pdf` 内の save 系

アプローチ:
- `QThread` + `QObject` worker パターン（または `QRunnable` + `QThreadPool`）。
- 各ワーカーが進捗シグナルを発行 → `QProgressDialog` またはステータスバー + キャンセル対応（初版はキャンセルなしでも可）。
- 完了時に MainWindow 側のスロットで refresh / ダイアログ表示 / dirty 更新を行う。
- エラーはワーカーからシグナルで伝播し、ログ + ユーザメッセージ。

**HF制約**:
- HF適用（`add_header_footer`）は現在同期でページに直接書き込むため、Phase 4 では対象外とする（短時間）。
- ただし `remove_header_footer`（全ページ再オープン）は重くなる可能性があるので、将来的にはスレッド化候補としてコメントを残す。

**影響ファイル**:
- 新規: `src/pdf_editor/ui/workers.py` または `src/pdf_editor/core/workers/` 配下に LoadWorker, ExportWorker, SaveWorker など。
- `src/pdf_editor/ui/main_window.py`（呼び出しを worker に委譲）
- `src/pdf_editor/pdf/pdf_manager.py`（必要に応じてスレッドセーフな注意書き）

**再利用する既存コード**:
- `pdf_manager.export_pages_to_images` の戻り値（success, attempted, errors）
- 既存の成功/失敗時の QMessageBox + statusBar 更新ロジックをワーカー完了スロットに移動

### Phase 5: その他整理 + テスト基盤（5, 7, 残りの保守性）
- **ThumbnailPanel のドラッグ&ドロップ**
  - 複雑な `dragMoveEvent` / `_animate_gap` / `_collect_flat_order` 周りに詳細コメントを追加。
  - 可能なら小さなヘルパーメソッド抽出（このフェーズでは可読性向上中心、大きなロジック変更は避ける）。

- **PDFManager の内部整理**
  - HF以外の部分で明らかな重複やマジックナンバー（line_gap など）に軽いコメント/定数化。
  - サムネイルキャッシュのキーと無効化タイミングを docstring で明文化（現状の設計意図を残す）。

- **Testing**
  - `tests/` に `test_pdf_manager.py` を新規作成。
  - 最初にカバーすべき: `load_pdfs`, `reorder_pages`, `rotate_page`, `save_as`, `save_selected_pages`, `export_pages_to_images` の基本パス。
  - HFの `add_header_footer` / `remove_header_footer` の**回帰テスト**を必ず含める（テキストが正しく入るか、remove で消えるか、回転が維持されるか）。これが「HF仕様を守れているか」の最も重要な検証になる。

- **Build / その他**
  - `pdf_editor.spec` の hiddenimports を新しいモジュール追加時に更新する手順をコメントに記載。
  - `document/spec.md` または新しい `document/architecture.md` に「HFは破壊的である」という設計決定を明記（将来の開発者向け）。

## 4. 変更対象ファイル一覧（優先度順）

**既存ファイル（修正）**:
- `main.py`
- `src/pdf_editor/ui/main_window.py`
- `src/pdf_editor/pdf/pdf_manager.py`（最小限）
- `src/pdf_editor/ui/thumbnail_panel.py`（軽微 + コメント）
- `generate_icon.py`
- `pdf_editor.spec`
- `requirements.txt`（logging は標準なので不要）

**新規ファイル / ディレクトリ**:
- `src/pdf_editor/utils/resources.py`
- `src/pdf_editor/ui/dialogs/__init__.py`
- `src/pdf_editor/ui/dialogs/header_footer_dialog.py`
- `src/pdf_editor/ui/dialogs/export_dialog.py`
- `src/pdf_editor/ui/workers.py`（またはディレクトリ構成）
- `tests/test_pdf_manager.py`
- （任意）`src/pdf_editor/utils/__init__.py`

**ドキュメント**:
- `document/spec.md`（HF設計決定の追記推奨）
- 本プラン自体（実装後に更新）

## 5. 再利用する既存の重要コード（ファイル:行 または 機能）

- `main.py:15-22`: `resource_path`（移管元）
- `src/pdf_editor/pdf/pdf_manager.py:144-196`: `add_header_footer`（**シグネチャ・ロジック完全維持**）
- `src/pdf_editor/pdf/pdf_manager.py:197-223`: `remove_header_footer`（**同上**）
- `src/pdf_editor/pdf/pdf_manager.py:278-341`: `export_pages_to_images`（worker でラップ）
- `src/pdf_editor/ui/main_window.py:23-138` & `140-324`: 2つのDialogクラス（移動）
- `src/pdf_editor/ui/main_window.py:348-352`: ThumbnailPanel とのシグナル接続パターン
- `src/pdf_editor/ui/thumbnail_panel.py:307`: `page_reordered.emit` など既存シグナル
- `PDFManager` の `PageInfo`, `PDFDocument` 内部クラス（現状のまま）

## 6. 検証方法（Verification）

**必須の回帰確認（特にHF）**:
1. 複数PDFを開く → ページ並び替え + 回転 + ヘッダー/フッター適用 → 「名前を付けて保存」 → 生成PDFを開いてヘッダー/フッターが正しく入っていることを目視確認。
2. 上記状態からヘッダー/フッター「削除」→ 再度保存 → 元のページ内容（ヘッダーなし、回転は維持）に戻っていることを確認。
3. 削除後にさらに回転や並び替えをして保存しても正しく反映されること。

**その他のE2E**:
- 画像エクスポート（全ページ / 選択ページ、PNG/JPG、異なるDPI）
- PDF切り出し（選択ページ）
- サムネイルサイズ切替 + ドラッグ&ドロップでのファイル間移動
- プレビューでのズーム/パン
- アプリ終了時の未保存確認ダイアログ（Phase 3後）

**技術的確認**:
- `python main.py` で正常起動・全操作。
- PyInstaller でビルド（`pyinstaller pdf_editor.spec`）し、生成EXEで上記操作がすべて通ること（リソースパスが壊れていないことの最終確認）。
- `tests/test_pdf_manager.py` を実行してHF回帰テストが緑になる。
- ログがコンソールに出力される（エラー時・情報時）。

**リスク低減策**:
- 各フェーズ終了後にHF機能のフル手動テストを実施。
- 大きな変更（Phase 2のダイアログ移動後、Phase 4のスレッド化後）は必ずEXEビルド確認。

## 7. スコープ外（今回のプランでは行わない）

- 完全なUndo/Redoスタック（HFの非破壊化含む）
- プレビューをQGraphicsViewやQPdfViewへ置き換え
- 国際化（文字列の外部化）
- 大規模なThumbnailPanelドラッグロジックの完全書き換え
- Nuitka などビルドツールの変更
- パスワード付きPDF対応、アノテーション対応など新機能

## 8. 次のステップ（プラン承認後）

1. ユーザーがこのプランを承認（`[Plan approved]` またはコメント付き）。
2. 承認されたら Phase 1 から実装開始（search_replace などを使って順次）。
3. 各フェーズでユーザーに動作確認を依頼。
4. 実装完了後に本プランを更新（完了チェック）。

---

**注意**: このプランはHFのPDFレベルでの振る舞いを**不変**とすることを最優先に設計されている。実装中にHF関連の挙動が変わりそうになった場合は即座にストップして相談すること。
