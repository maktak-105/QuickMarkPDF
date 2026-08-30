"""Drive the real, running C++/WebView2 QuickMarkPDF.exe via WebDriver to
verify the UI-layer-only behaviors qa/check_behaviors_cpp.py cannot observe
(it only talks to PdfManager over the TCP test API, never app.js/the DOM):
thumbnail size switching, preview wheel-zoom/right-drag-pan, the
preferences wheel-mode setting, the crop-selection rubber-band, and
Markdown mode switching.

These features are all already implemented (verified once by hand via
screenshots earlier) -- what was missing was an automated, repeatable check
that actually exercises them, so qa/behaviors_cpp.json's per-check
not_implemented() stubs for these names were honest but permanent dead
ends. This script replaces those specific entries (matched by check name)
in qa/behaviors_cpp.json with real PASS/FAIL results and re-records the
merged set to qa/qa_history.db, leaving every TCP-based result untouched.

Run: .venv\\Scripts\\python.exe qa\\check_ui_behaviors_cpp.py
(requires qa/tools/msedgedriver.exe -- see document/environment.md)
"""
import json
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF, for building test fixtures

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "qa"))
from selenium_client import connect, disconnect, post_message  # noqa: E402
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


def make_test_pdf(path: Path, pages: int = 3):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=560)
        page.insert_text((50, 50), f"UI behavior test page {i + 1}", fontsize=14)
    doc.save(str(path))
    doc.close()


def fire(driver, target_selector, type_, x, y, button=0, base_selector="#preview"):
    """Dispatch a synthetic MouseEvent at (x, y) relative to base_selector's
    top-left, targeting target_selector -- mirrors real event delivery
    closely enough for plain JS listeners (verified in this same session:
    the crop-selection feature's overlay geometry matched a real drag
    exactly when checked this way).
    """
    driver.execute_script(
        """
        const base = document.querySelector(arguments[4]).getBoundingClientRect();
        const target = document.querySelector(arguments[0]);
        const ev = new MouseEvent(arguments[1], {
            bubbles: true, cancelable: true, view: window,
            clientX: base.left + arguments[2], clientY: base.top + arguments[3], button: arguments[5],
        });
        target.dispatchEvent(ev);
        """,
        target_selector, type_, x, y, base_selector, button,
    )


def main():
    if not EXE_PATH.exists():
        raise SystemExit(f"{EXE_PATH} が見つかりません。先に build_native.py でビルドしてください。")

    tmp_dir = REPO_ROOT / "qa" / "_tmp_ui_cpp"
    tmp_dir.mkdir(exist_ok=True)
    pdf_path = tmp_dir / "ui_behavior_test.pdf"
    make_test_pdf(pdf_path)
    md_path = tmp_dir / "ui_behavior_test.md"
    md_path.write_text("# UI Behavior Test\n\nbody\n", encoding="utf-8")

    # ── PDFセッション: サムネイルサイズ・ホイールズーム・右ドラッグパン・
    #    環境設定・クロップ選択 ──
    proc, driver = connect(EXE_PATH, extra_args=[str(pdf_path)])
    try:
        time.sleep(1.5)  # let the first page render so .page-thumbnail exists

        def _thumb_size(size, expected_w, button_id):
            before = driver.execute_script(
                "return document.querySelector('.page-thumbnail').getBoundingClientRect().width")
            driver.find_element("css selector", button_id).click()
            time.sleep(0.5)
            after = driver.execute_script(
                "return document.querySelector('.page-thumbnail').getBoundingClientRect().width")
            checked = driver.execute_script(
                f"return document.querySelector('{button_id}').classList.contains('checked')")
            ok = abs(after - expected_w) <= 2 and checked
            return before, after, ok, (
                f"サムネイルサイズを「{size}」に切り替えたところ、実描画幅が{before}px→{after}pxに変化し"
                f"(期待値{expected_w}px)、ボタンのchecked状態も実際に切り替わった"
            )
        check("thumbnail_size_small", lambda: _thumb_size("小", 80, "#thumb-size-small"))
        check("thumbnail_size_medium", lambda: _thumb_size("中", 120, "#thumb-size-medium"))
        check("thumbnail_size_toggle", lambda: _thumb_size("大", 200, "#thumb-size-large"))
        # 次のチェックのために既定(中)へ戻す
        driver.find_element("css selector", "#thumb-size-medium").click()
        time.sleep(0.3)

        def _wheel_zoom():
            before = driver.execute_script(
                "return document.querySelector('#preview img').getBoundingClientRect().width")
            driver.execute_script("""
                const el = document.querySelector('#preview');
                el.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, deltaY: -300}));
            """)
            time.sleep(0.3)
            after = driver.execute_script(
                "return document.querySelector('#preview img').getBoundingClientRect().width")
            ok = after > before
            return before, after, ok, (
                f"環境設定が既定の「ズーム」モードの状態でプレビュー上にホイールイベント(deltaY=-300)を"
                f"送ったところ、表示幅が{before:.1f}px→{after:.1f}pxに変化した(拡大された)"
            )
        check("preview_wheel_zoom_default_mode", _wheel_zoom)

        def _right_drag_pan():
            before = driver.execute_script("return document.querySelector('#preview').scrollLeft")
            fire(driver, "#preview", "mousedown", 400, 300, button=2)
            fire(driver, "body", "mousemove", 300, 300, button=2, base_selector="#preview")
            fire(driver, "body", "mouseup", 300, 300, button=2, base_selector="#preview")
            time.sleep(0.3)
            after = driver.execute_script("return document.querySelector('#preview').scrollLeft")
            ok = after != before
            return before, after, ok, (
                f"「ズーム」モードで右ボタンドラッグ(x: 400→300)したところ、"
                f"scrollLeftが{before}→{after}に変化した(パン動作)"
            )
        check("preview_right_drag_pan_zoom_mode", _right_drag_pan)

        def _wheel_mode_setting():
            # 設定メニュー -> 環境設定 -> 「スクロール」モードに切替 -> OK
            driver.find_element("css selector", "#settings-menu .menu-label").click()
            time.sleep(0.2)
            driver.find_element("css selector", "#preferences-item").click()
            time.sleep(0.2)
            driver.find_element("css selector", 'input[name="wheel-mode"][value="scroll"]').click()
            driver.find_element("css selector", "#preferences-ok").click()
            time.sleep(0.2)
            before = driver.execute_script(
                "return document.querySelector('#preview img').getBoundingClientRect().width")
            fire(driver, "#preview", "mousedown", 400, 300, button=2)
            fire(driver, "body", "mousemove", 300, 200, button=2, base_selector="#preview")
            fire(driver, "body", "mouseup", 300, 200, button=2, base_selector="#preview")
            time.sleep(0.3)
            after = driver.execute_script(
                "return document.querySelector('#preview img').getBoundingClientRect().width")
            ok = after != before
            # 元に戻す(以降のチェックに影響しないよう既定の「ズーム」に戻す)
            driver.find_element("css selector", "#settings-menu .menu-label").click()
            time.sleep(0.2)
            driver.find_element("css selector", "#preferences-item").click()
            time.sleep(0.2)
            driver.find_element("css selector", 'input[name="wheel-mode"][value="zoom"]').click()
            driver.find_element("css selector", "#preferences-ok").click()
            return before, after, ok, (
                f"環境設定を「スクロール」モードに切り替えた状態で右ドラッグしたところ、"
                f"(パンではなく)表示幅が{before:.1f}px→{after:.1f}pxに変化した(モード切替が実際に効いている)"
            )
        check("preview_wheel_mode_setting_switches_behavior", _wheel_mode_setting)

        def _toggle_preview_mode_via_context_menu():
            # previewMode ('text' | 'crop') was introduced by app.js's text-
            # selection feature (commit 7830db5, after crop-selection was
            # first implemented) and defaults to 'text' -- the mousedown
            # handler that starts a crop drag now early-returns unless the
            # user has switched to 'crop' mode first via the preview's
            # right-click context menu (togglePreviewMode is always the
            # LAST menu item, appended after the page-action items).
            fire(driver, "#preview", "contextmenu", 100, 100)
            time.sleep(0.3)
            driver.execute_script("""
                const buttons = document.querySelectorAll('.context-menu button');
                if (buttons.length) buttons[buttons.length - 1].click();
            """)
            time.sleep(0.2)

        def _crop_selection():
            # Earlier checks in this same session zoomed/panned the preview,
            # so the image's on-screen box has moved -- click a fresh page
            # to trigger fitPreviewToWidth()'s zoom/scroll reset (and the
            # page_rendered handler's clearCropSelection()) before dragging,
            # so (50,50)-(250,200) is guaranteed to land inside the image.
            driver.execute_script("document.querySelectorAll('.page-item')[1]?.click()")
            time.sleep(0.8)
            driver.execute_script("document.querySelector('#crop-overlay')?.remove()")
            _toggle_preview_mode_via_context_menu()  # 'text' -> 'crop'
            fire(driver, "#preview", "mousedown", 50, 50, button=0)
            fire(driver, "body", "mousemove", 120, 120, button=0, base_selector="#preview")
            fire(driver, "body", "mousemove", 250, 200, button=0, base_selector="#preview")
            fire(driver, "body", "mouseup", 250, 200, button=0, base_selector="#preview")
            overlay = driver.execute_script("""
                const el = document.querySelector('#crop-overlay');
                return el ? {w: parseFloat(el.style.width), h: parseFloat(el.style.height)} : null;
            """)
            ok = bool(overlay and overlay["w"] > 5 and overlay["h"] > 5)
            _toggle_preview_mode_via_context_menu()  # 'crop' -> 'text', don't leak into later checks
            return "選択なし", overlay, ok, (
                f"プレビュー上で(50,50)から(250,200)へ左ドラッグしたところ、"
                f"実際に#crop-overlayが生成され、サイズは{overlay}だった"
            )
        check("preview_crop_area_selection", _crop_selection)

        def _page_number_labels_distinct():
            # 3ページ中1ページ目(index 0)を削除すると、残る2ページの
            # source_page(元ファイル内での通し番号)は1,2のままだが、
            # 編集後の位置(ガター番号)は1,2に詰まる -- 削除前は
            # 両方とも1,2,3で偶然一致していたのが、削除後は
            # ガター=1,2 / p.N=2,3 と実際に食い違うことを確認する
            # (thumbnail_panel.py: f"p.{info.original_page_index + 1}" と
            # 同じ意味を持たせる修正を検証)。
            post_message(driver, {"type": "delete_pages", "indices": [0]})
            time.sleep(1.0)
            labels = driver.execute_script("""
                return Array.from(document.querySelectorAll('.page-item')).map(item => ({
                    gutter: item.querySelector('.page-gutter').textContent,
                    pageNumber: item.querySelector('.page-number').textContent,
                }));
            """)
            ok = (
                len(labels) == 2
                and labels[0]["gutter"] == "1" and labels[0]["pageNumber"] == "p.2"
                and labels[1]["gutter"] == "2" and labels[1]["pageNumber"] == "p.3"
            )
            return "削除前: 両方とも1,2,3", labels, ok, (
                f"3ページの文書から1ページ目を削除したところ、残り2ページの表示が{labels}になった"
                "(ガター番号=編集後の位置、p.N=削除前の元ファイル内での番号、という異なる意味の"
                "2つの数値が実際に別々の値になった)"
            )
        check("page_number_labels_distinct_from_position", _page_number_labels_distinct)
    finally:
        disconnect(proc, driver)

    # ── Markdownセッション: 別プロセスとして起動(モード切替は起動時の拡張子判定なので) ──
    proc, driver = connect(EXE_PATH, extra_args=[str(md_path)])
    try:
        time.sleep(1.5)

        def _markdown_mode():
            # window.__qa.mode (install_message_hook) flips to 'markdown' the
            # instant the markdown_opened message is processed by OUR
            # listener -- app.js's own setMode() call runs from the SAME
            # event, just a separate listener, so if our hook saw the
            # message but the DOM hasn't caught up yet, a short extra wait
            # (not a poll loop -- see wait_bridge_alive's docstring on why)
            # covers it without re-querying execute_script repeatedly.
            qa_mode = driver.execute_script("return window.__qa.mode")
            if qa_mode != "markdown":
                time.sleep(2.0)
            pdf_hidden = driver.execute_script(
                "return document.querySelector('#pdf-workspace').hidden")
            md_hidden = driver.execute_script(
                "return document.querySelector('#markdown-workspace').hidden")
            content_len = driver.execute_script(
                "return document.querySelector('#markdown-content').innerHTML.length")
            history_types = driver.execute_script(
                "return window.__qa.history.map(h => h.type)")
            ok = bool(pdf_hidden and not md_hidden and content_len > 0)
            return "pdf", ("markdown" if ok else f"pdf_hidden={pdf_hidden},md_hidden={md_hidden}"), ok, (
                f".mdファイルを起動時に指定して開いたところ、window.__qa.mode={qa_mode}、"
                f"pdf-workspace.hidden={pdf_hidden}、markdown-workspace.hidden={md_hidden}、"
                f"本文HTML長={content_len}文字、受信メッセージ種別={history_types}"
                + ("となり、実際にMarkdownモードへ切り替わった" if ok else "(切替失敗)")
            )
        check("markdown_mode_switch", _markdown_mode)
    finally:
        disconnect(proc, driver)

    # ── qa/behaviors_cpp.json の該当エントリだけを実結果で置き換えてマージ ──
    behaviors_path = REPO_ROOT / "qa" / "behaviors_cpp.json"
    existing = json.loads(behaviors_path.read_text(encoding="utf-8")) if behaviors_path.exists() else {
        "source": "cpp", "total": 0, "passed": 0, "results": []}
    by_name = {r["name"]: r for r in existing["results"]}
    for r in results:
        by_name[r["name"]] = r
    merged = list(by_name.values())
    passed = sum(1 for r in merged if r["pass"])
    out = {"source": "cpp", "total": len(merged), "passed": passed, "results": merged}
    behaviors_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[集計] このスクリプトで{len(results)}件更新 -> 全体{passed}/{len(merged)} 件PASS -> {behaviors_path}",
          flush=True)
    db.record_behaviors_run("cpp", merged)


if __name__ == "__main__":
    main()
