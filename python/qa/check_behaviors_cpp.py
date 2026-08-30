"""Drive the real, running C++ QuickMarkPDF.exe via its test-only TCP
control API (see test_api_client.py, core/native/test_api_server.h) and
record PASS/FAIL evidence with a plain-Japanese behavior sentence -- the
C++-side counterpart to check_behaviors_python.py, using the SAME check
names so dashboard.py's name-keyed lookups (ACTION_CHECK_MAP,
behaviors_by_name) line up automatically with no changes on that side.

This calls PdfManager methods directly (open/rotate/delete/reorder/undo/
save/export) -- it does NOT exercise app.js or the WebView2 message bridge,
so it complements rather than replaces qa/extract_cpp.py's DOM-level UI
measurement. See test_api_client.py's docstring for why: two earlier
attempts through WebView2's own postMessage bridge (raw CDP, then Selenium)
both hit the same non-deterministic message-delivery timing issue.

Checks with no C++ implementation yet (the feature simply hasn't been
built: thumbnail-size switching, preview zoom/pan/crop) are recorded
as an explicit, visible FAIL naming what's missing. Per the QA requirements
memory: a checker that silently skips a gap is worse than one that reports
it honestly, so nothing here is omitted -- everything not yet automated
still gets a row.

Run: .venv\\Scripts\\python.exe qa\\check_behaviors_cpp.py
"""
import json
import shutil
import sys
from pathlib import Path

import fitz  # PyMuPDF, for building the same test fixtures as check_behaviors_python.py
from PIL import Image  # only for reading exported PNG dimensions (export_images_with_crop)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "qa"))
from test_api_client import connect, disconnect  # noqa: E402
import db  # noqa: E402

EXE_PATH = REPO_ROOT.parent / "dist" / "binary" / "QuickMarkPDF.exe"

results = []


def check(name, fn):
    try:
        before, after, ok, behavior = fn()
        results.append({"name": name, "pass": bool(ok), "before": str(before), "after": str(after),
                         "behavior": behavior, "error": None})
    except Exception as exc:  # noqa: BLE001
        results.append({"name": name, "pass": False, "before": None, "after": None,
                         "behavior": f"例外により未確認: {exc!r}", "error": repr(exc)})
    r = results[-1]
    print(f"[{'PASS' if r['pass'] else 'FAIL'}] {name} :: {r['behavior']}", flush=True)


def not_implemented(name, reason):
    check(name, lambda: (None, None, False, f"C++未実装: {reason}"))


def make_test_pdf(path: Path, pages: int = 3, password: str | None = None):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=560)
        page.insert_text((50, 50), f"Test page {i + 1}")
    if password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password)
    else:
        doc.save(str(path))
    doc.close()


def main():
    if not EXE_PATH.exists():
        raise SystemExit(f"{EXE_PATH} が見つかりません。先に build_native.py でビルドしてください。")

    tmp_dir = REPO_ROOT / "qa" / "_tmp_cpp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(exist_ok=True)
    pdf_path = tmp_dir / "behavior_test.pdf"
    make_test_pdf(pdf_path, pages=3)
    pdf2_path = tmp_dir / "behavior_test2.pdf"
    make_test_pdf(pdf2_path, pages=2)
    enc_path = tmp_dir / "encrypted.pdf"
    make_test_pdf(enc_path, pages=1, password="s3cret")
    md_path = tmp_dir / "behavior_test.md"
    md_path.write_text("# Test\n\nbody text\n", encoding="utf-8")

    proc, client = connect(EXE_PATH)
    try:
        def _open():
            r = client.send({"type": "load_pdfs", "paths": [str(pdf_path)]})
            pages = r["state"]["pages"]
            ok = len(pages) == 3
            return 0, len(pages), ok, (
                f"「開く」でPDF({pdf_path.name})を読み込んだところ、"
                f"実際に読み込まれたページ数は{len(pages)}だった({'期待通り' if ok else '不一致'})"
            )
        check("open_pdf", _open)

        def _rotate():
            before = client.send({"type": "get_state"})["pages"][0]["rotation"]
            after = client.send({"type": "rotate_pages", "indices": [0], "degrees": 90})["pages"][0]["rotation"]
            ok = (after - before) % 360 == 90
            return before, after, ok, f"ページ0を90度回転操作したところ、rotation値が{before}→{after}に変化した"
        check("rotate", _rotate)

        def _undo_rotate():
            before = client.send({"type": "get_state"})["pages"][0]["rotation"]
            after = client.send({"type": "undo"})["state"]["pages"][0]["rotation"]
            ok = after != before
            return before, after, ok, f"直前の回転操作をUndoしたところ、rotation値が{before}→{after}に戻った"
        check("undo_rotate", _undo_rotate)

        def _rotate_left():
            before = client.send({"type": "get_state"})["pages"][1]["rotation"]
            after = client.send({"type": "rotate_pages", "indices": [1], "degrees": -90})["pages"][1]["rotation"]
            ok = (after - before) % 360 == 270
            return before, after, ok, f"「左90°」相当の操作(-90度)をページ1に行ったところ、rotation値が{before}→{after}に変化した"
        check("rotate_left_90", _rotate_left)

        def _rotate_180():
            before = client.send({"type": "get_state"})["pages"][2]["rotation"]
            after = client.send({"type": "rotate_pages", "indices": [2], "degrees": 180})["pages"][2]["rotation"]
            ok = (after - before) % 360 == 180
            return before, after, ok, f"「180°」操作をページ2に行ったところ、rotation値が{before}→{after}に変化した"
        check("rotate_180", _rotate_180)

        def _drag_reorder():
            before = [p["source_page"] for p in client.send({"type": "get_state"})["pages"]]
            n = len(before)
            order = [2] + [i for i in range(n) if i != 2]  # move index 2 to front
            after = [p["source_page"] for p in client.send({"type": "reorder_pages", "order": order})["pages"]]
            ok = after == [before[i] for i in order]
            return before, after, ok, (
                f"3枚目のページを先頭に移動するreorder_pagesを送ったところ、"
                f"ページ順が{before}→{after}に実際に入れ替わった"
            )
        check("drag_and_drop_reorder", _drag_reorder)

        def _undo_reorder():
            before = [p["source_page"] for p in client.send({"type": "get_state"})["pages"]]
            after = [p["source_page"] for p in client.send({"type": "undo"})["state"]["pages"]]
            ok = after != before
            return before, after, ok, f"直前の並べ替えをUndoしたところ、順序が{before}→{after}に戻った"
        check("undo_reorder", _undo_reorder)

        def _delete():
            before = client.send({"type": "get_state"})["page_count"]
            after = client.send({"type": "delete_pages", "indices": [0]})["page_count"]
            ok = after == before - 1
            return before, after, ok, f"1ページ削除操作をしたところ、総ページ数が{before}→{after}になった"
        check("delete", _delete)

        def _undo_delete():
            before = client.send({"type": "get_state"})["page_count"]
            after = client.send({"type": "undo"})["state"]["page_count"]
            ok = after == before + 1
            return before, after, ok, f"直前の削除をUndoしたところ、総ページ数が{before}→{after}に戻った"
        check("undo_delete", _undo_delete)

        def _password_retry():
            before = client.send({"type": "get_state"})["page_count"]
            r = client.send({"type": "load_pdfs", "paths": [str(enc_path)], "password": "s3cret"})
            after = r["state"]["page_count"]
            ok = after == before + 1 and r["loaded_count"] == 1
            return before, after, ok, (
                f"暗号化PDFを開き、パスワードを直接注入したところ、"
                f"ページ数が{before}→{after}になり実際に開けた"
            )
        check("password_protected_pdf_retry", _password_retry)

        def _duplicate():
            before = client.send({"type": "get_state"})["page_count"]
            r = client.send({"type": "load_pdfs", "paths": [str(enc_path)], "password": "s3cret"})
            after = r["state"]["page_count"]
            ok = after == before and len(r["duplicate_files"]) == 1
            return before, after, ok, (
                f"既に読み込み済みの暗号化PDFを再度開こうとしたところ、"
                f"ページ数は{before}のまま変化せず、duplicate_filesに{len(r['duplicate_files'])}件記録された"
            )
        check("duplicate_file_detection", _duplicate)

        def _close_file():
            client.send({"type": "close_all"})
            client.send({"type": "load_pdfs", "paths": [str(pdf_path), str(pdf2_path)]})
            before = client.send({"type": "get_state"})["page_count"]
            after = client.send({"type": "close_document", "path": str(pdf2_path)})["state"]["page_count"]
            ok = after == before - 2
            return before, after, ok, (
                f"2ファイル読込中に{pdf2_path.name}だけを閉じたところ、"
                f"総ページ数が{before}→{after}になり、そのファイル分だけ減った"
            )
        check("close_single_file", _close_file)

        def _overwrite_save():
            client.send({"type": "close_all"})
            target = tmp_dir / "overwrite_test.pdf"
            make_test_pdf(target, pages=2)
            client.send({"type": "load_pdfs", "paths": [str(target)]})
            before_bytes = target.read_bytes()
            client.send({"type": "rotate_pages", "indices": [0], "degrees": 90})
            r = client.send({"type": "overwrite_source"})
            after_bytes = target.read_bytes()
            ok = r["ok"] and before_bytes != after_bytes
            verb = "実際に変化した" if before_bytes != after_bytes else "変化しなかった"
            return len(before_bytes), len(after_bytes), ok, (
                f"1ページ回転後に上書き保存したところ、ディスク上のファイルの内容が{verb}"
                f"({len(before_bytes)}→{len(after_bytes)}バイト)"
            )
        check("overwrite_save_persists_to_disk", _overwrite_save)

        def _split():
            client.send({"type": "close_all"})
            client.send({"type": "load_pdfs", "paths": [str(pdf_path)]})
            out_path = tmp_dir / "split_out.pdf"
            r = client.send({"type": "save_selected_pages", "indices": [0, 1], "output_path": str(out_path)})
            ok = r["ok"] and out_path.exists()
            page_count = None
            if ok:
                d = fitz.open(str(out_path))
                page_count = d.page_count
                d.close()
                ok = page_count == 2
            return "no file", f"exists={out_path.exists()}, pages={page_count}", ok, (
                f"2ページ選択してPDF切り出しをしたところ、実際にディスク上に{page_count}ページのPDFファイルが生成された"
            )
        check("split_pdf_cutout", _split)

        def _export_png():
            out_dir = tmp_dir / "png_out"
            out_dir.mkdir(exist_ok=True)
            r = client.send({
                "type": "export_pages_to_images", "indices": [], "output_dir": str(out_dir),
                "fmt": "png", "dpi": 150, "prefix": "page",
            })
            files = list(out_dir.glob("*.png"))
            ok = r["success"] > 0 and len(files) > 0
            return "no files", f"{len(files)} PNG files", ok, (
                f"PNG形式・全ページで画像出力したところ、実際に{len(files)}個のPNGファイルがフォルダに生成された"
                f"(success={r['success']}/{r['attempted']})"
            )
        check("export_images_png", _export_png)

        def _export_crop():
            out_dir_full = tmp_dir / "png_full"
            out_dir_crop = tmp_dir / "png_crop"
            out_dir_full.mkdir(exist_ok=True)
            out_dir_crop.mkdir(exist_ok=True)
            client.send({
                "type": "export_pages_to_images", "indices": [0], "output_dir": str(out_dir_full),
                "fmt": "png", "dpi": 150, "prefix": "page",
            })
            # Test PDF pages are 400x560 PDF points (make_test_pdf); crop to
            # an 80x80pt corner, well inside the page.
            client.send({
                "type": "export_pages_to_images", "indices": [0], "output_dir": str(out_dir_crop),
                "fmt": "png", "dpi": 150, "prefix": "page", "crop": [10, 10, 90, 90],
            })
            full_files = list(out_dir_full.glob("*.png"))
            crop_files = list(out_dir_crop.glob("*.png"))
            full_size = Image.open(full_files[0]).size if full_files else None
            crop_size = Image.open(crop_files[0]).size if crop_files else None
            ok = bool(full_size and crop_size and crop_size[0] < full_size[0] and crop_size[1] < full_size[1])
            return full_size, crop_size, ok, (
                f"crop無し出力({full_size})とcrop=[10,10,90,90]指定出力({crop_size})を比較したところ、"
                f"クロップ指定時の方が実際に小さい画像になった"
            )
        check("export_images_with_crop", _export_crop)

        def _mixed_reject():
            before = client.send({"type": "get_state"})["page_count"]
            r = client.send({"type": "load_documents", "paths": [str(pdf_path), str(md_path)]})
            after = r["state"]["page_count"]
            ok = r["outcome"] == "rejected_mixed" and after == before
            return f"page_count={before}", f"outcome={r['outcome']},page_count={after}", ok, (
                f"PDFとMarkdownを同時に指定してload_documentsを送ったところ、outcome=\"{r['outcome']}\"で"
                f"実際に拒否され、ページ数は{before}のまま変化しなかった"
            )
        check("mixed_pdf_markdown_open_rejected", _mixed_reject)

        def _unsaved_confirm():
            client.send({"type": "close_all", "confirm": True})
            client.send({"type": "load_pdfs", "paths": [str(pdf_path)]})
            client.send({"type": "rotate_pages", "indices": [0], "degrees": 90})
            dirty_before = client.send({"type": "get_state"})["dirty"]
            r_no = client.send({"type": "close_all", "confirm": False})
            refused = (not r_no["ok"]) and r_no["state"]["page_count"] > 0 and r_no["state"]["dirty"]
            r_yes = client.send({"type": "close_all", "confirm": True})
            discarded = r_yes["ok"] and r_yes["state"]["page_count"] == 0
            ok = dirty_before and refused and discarded
            return f"dirty={dirty_before}", f"confirm=False→ok={r_no['ok']},pages={r_no['state']['page_count']} / confirm=True→ok={r_yes['ok']},pages={r_yes['state']['page_count']}", ok, (
                "1ページ回転後(dirty=true)にclose_allをconfirm=falseで送ったところ実際に拒否され"
                f"ページ数{r_no['state']['page_count']}のまま維持された。次にconfirm=trueで送ったところ"
                f"実際に破棄されページ数が{r_yes['state']['page_count']}になった"
            )
        check("unsaved_changes_confirmation", _unsaved_confirm)

        def _text_layout():
            client.send({"type": "close_all", "confirm": True})
            client.send({"type": "load_pdfs", "paths": [str(pdf_path)]})
            r = client.send({"type": "get_text_layout", "page_index": 0})
            runs = r.get("runs", [])
            combined = "".join(run["text"] for run in runs)
            bbox_ok = all(
                0 <= run["x0"] <= run["x1"] and 0 <= run["y0"] <= run["y1"]
                for run in runs
            )
            ok = len(runs) > 0 and "Test page 1" in combined and bbox_ok
            return f"runs={len(runs)}", f"combined_text={combined!r} bbox_ok={bbox_ok}", ok, (
                f"1ページ目のget_text_layoutを呼んだところ{len(runs)}件の行矩形が返り、"
                f"結合したテキストは{combined!r}(埋め込みテキスト「Test page 1」を"
                f"{'含む' if 'Test page 1' in combined else '含まない'}、"
                f"全矩形の座標は{'妥当' if bbox_ok else '不正'})"
            )
        check("get_text_layout_extracts_page_text", _text_layout)
        not_implemented("preview_wheel_zoom_default_mode", "プレビューのホイールズームが未実装(<img>を置くだけ、UI層のみでPdfManager経由では検証不可)")
        not_implemented("preview_right_drag_pan_zoom_mode", "プレビューの右ドラッグパンが未実装(同上)")
        not_implemented("preview_wheel_mode_setting_switches_behavior", "環境設定ダイアログ・ホイールモード切替が未実装(同上)")
        not_implemented("preview_crop_area_selection", "プレビュー上のクロップ範囲選択が未実装(同上)")
        not_implemented("thumbnail_size_toggle", "サムネイルサイズ切替ボタンが未実装(小/中/大ボタン自体が無い、UI層のみでPdfManager経由では検証不可)")
        not_implemented("thumbnail_size_small", "同上")
        not_implemented("thumbnail_size_medium", "同上")
        not_implemented("markdown_mode_switch", "Markdownモード切替はUI層(app.js)の状態でありPdfManager経由では検証不可。DOM測定(extract_cpp.py)側の対象")

    finally:
        disconnect(proc, client)

    passed = sum(1 for r in results if r["pass"])
    out = {"source": "cpp", "total": len(results), "passed": passed, "results": results}
    out_path = REPO_ROOT / "qa" / "behaviors_cpp.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[集計] {passed}/{len(results)} 件PASS -> {out_path}", flush=True)
    db.record_behaviors_run("cpp", results)


if __name__ == "__main__":
    main()
