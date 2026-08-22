"""Turn qa/baseline.json into a human-readable qa/dashboard.html.

Run: .venv\\Scripts\\python.exe qa\\dashboard.py
"""
import json
import html
from pathlib import Path

import yaml

import db

REPO_ROOT = Path(__file__).resolve().parent.parent


def parts_match(py_p, cpp_p, tol_pct=0.10, min_tol_px=2, hue_tol=10, sv_tol=10):
    """True/False once both sides have a measurement, None if the C++ side
    hasn't been measured yet (kept out of the pass/fail denominator rather
    than counted as a fail, since "not measured" and "measured and wrong"
    are different facts).

    Position/size tolerance is +-10% of that part's own Python-measured
    width/height (user instruction, 2026-08-20: treat small coordinate
    drift as acceptable for now rather than chasing every last pixel) --
    min_tol_px keeps very small parts (e.g. a 4px splitter handle) from
    getting an unreasonably tight tolerance.
    """
    if cpp_p is None:
        return None
    pr, cr = py_p["rect"], cpp_p["rect"]

    def within(a, b, scale):
        tol = max(min_tol_px, abs(scale) * tol_pct)
        return abs(a - b) <= tol

    pos_ok = within(pr["x"], cr["x"], pr["w"]) and within(pr["y"], cr["y"], pr["h"])
    size_ok = within(pr["w"], cr["w"], pr["w"]) and within(pr["h"], cr["h"], pr["h"])
    py_hsv, cpp_hsv = py_p["hsv"], cpp_p["hsv"]
    if py_hsv and cpp_hsv:
        dh = abs(py_hsv["h"] - cpp_hsv["h"])
        dh = min(dh, 360 - dh)
        hsv_ok = dh <= hue_tol and abs(py_hsv["s"] - cpp_hsv["s"]) <= sv_tol and abs(py_hsv["v"] - cpp_hsv["v"]) <= sv_tol
    else:
        hsv_ok = py_hsv is None and cpp_hsv is None
    return pos_ok and size_ok and hsv_ok


def hsv_cell(hsv):
    if not hsv:
        return '<td class="hsv">-</td>'
    r, g, b = hsv["rgb"]
    hexcode = f"#{r:02x}{g:02x}{b:02x}"
    return (
        f'<td class="hsv"><span class="swatch" style="background:{hexcode}"></span>'
        f'H={hsv["h"]} S={hsv["s"]} V={hsv["v"]} <code>{hexcode}</code></td>'
    )


ACTION_BEHAVIOR_DESC = {
    "開く": "クリックするとファイル選択ダイアログが開き、選んだPDF/Markdownを読み込んで表示する(Ctrl+Oでも同じ)",
    "PDF切り出し": "選択中のページだけを新しいPDFファイルとして保存先ダイアログ経由で書き出す",
    "画像出力": "選択範囲(または全ページ)をPNG/JPEG画像として指定フォルダに書き出す設定ダイアログを開く",
    "右90°": "選択中のページを右へ90度回転する",
    "左90°": "選択中のページを左へ90度回転する",
    "180°": "選択中のページを180度回転する",
    "保存": "上書き保存/名前を付けて保存を選ぶダイアログを経て、現在の編集内容をPDFとして書き出す",
    "サムネ": "(ラベルのみ、クリック不可)",
    "小": "サムネイル表示サイズを小さくする",
    "中": "サムネイル表示サイズを標準にする(既定値)",
    "大": "サムネイル表示サイズを大きくする",
    "設定": "メニューを開くだけの入口。実際の設定操作は子項目「環境設定...」で行う",
    "環境設定...": "プレビューのホイール操作モード(ズーム/スクロール)を切り替えるダイアログを開く",
}

SHORTCUT_BEHAVIOR_DESC = {
    "Del": "選択中のページを削除する",
    "Ctrl+Z": "直前の操作(回転/削除/並べ替え/ファイルを閉じる)を1つ元に戻す",
}

# 各QActionが実際に何によって動作検証されているかの対応表。
# キーは (text, shortcut)。値はcheck_behaviors_python.pyのcheck名のリスト。
# 空リスト = そのアクション自体は入口/既定値でしかなく、個別チェックの対象ではない
# (別のアクションのチェックが間接的に担保している、または元々操作を伴わない)。
ACTION_CHECK_MAP = {
    ("設定", ""): [],
    ("環境設定...", ""): ["preview_wheel_mode_setting_switches_behavior"],
    ("開く", "Ctrl+O"): ["open_pdf", "password_protected_pdf_retry", "duplicate_file_detection", "mixed_pdf_markdown_open_rejected"],
    ("PDF切り出し", ""): ["split_pdf_cutout"],
    ("画像出力", ""): ["export_images_png", "export_images_with_crop"],
    ("右90°", ""): ["rotate"],
    ("左90°", ""): ["rotate_left_90"],
    ("180°", ""): ["rotate_180"],
    ("保存", "Ctrl+S"): ["overwrite_save_persists_to_disk"],
    ("小", ""): ["thumbnail_size_small"],
    ("中", ""): ["thumbnail_size_medium"],
    ("大", ""): ["thumbnail_size_toggle"],
    ("Main Toolbar", ""): [],
    ("Thumbnail Size Toolbar", ""): [],
    ("サムネ", ""): [],
}

SHORTCUT_CHECK_MAP = {
    "Del": ["delete"],
    "Ctrl+Z": ["undo_rotate", "undo_delete", "undo_reorder"],
}


CPP_NOT_MEASURED = "未計測"


def cpp_mark_cell(cpp_result):
    """結果マーク用<td>。cpp_result=Noneならグレーで「未計測」、あればPython側と同じPASS/FAIL表示。"""
    if cpp_result is None:
        return f'<td class="mark cpp-missing">{CPP_NOT_MEASURED}</td>'
    ok = cpp_result["pass"]
    cls = "pass" if ok else "fail"
    return f'<td class="mark {cls}">{"PASS" if ok else "FAIL"}</td>'


def build(
    source_json: Path,
    out_html: Path,
    title: str,
    behaviors_json: Path | None = None,
    cpp_source_json: Path | None = None,
    cpp_behaviors_json: Path | None = None,
):
    data = json.loads(source_json.read_text(encoding="utf-8"))
    parts = data.get("parts", [])
    actions = data.get("actions", [])
    screenshot_b64 = data.get("screenshot_png_base64")

    behaviors = None
    if behaviors_json and behaviors_json.exists():
        behaviors = json.loads(behaviors_json.read_text(encoding="utf-8"))

    behaviors_by_name = {}
    if behaviors:
        behaviors_by_name = {r["name"]: r for r in behaviors["results"]}

    # C++版の対応データ。C++版はCDP等での自動操作プログラムを作らず、人間が実機で
    # 確認する方針のため、qa/baseline_cpp.json・qa/behaviors_cpp.jsonは通常存在しない
    # -- 存在すれば(人間が値を置けば)自動的に埋まり、無ければ「未計測」と正直に出す。
    cpp_data = None
    if cpp_source_json and cpp_source_json.exists():
        cpp_data = json.loads(cpp_source_json.read_text(encoding="utf-8"))
    cpp_parts_by_path = {p["path"]: p for p in cpp_data.get("parts", [])} if cpp_data else {}

    cpp_behaviors = None
    if cpp_behaviors_json and cpp_behaviors_json.exists():
        cpp_behaviors = json.loads(cpp_behaviors_json.read_text(encoding="utf-8"))
    cpp_behaviors_by_name = {r["name"]: r for r in cpp_behaviors["results"]} if cpp_behaviors else {}

    # Python widget path <-> C++ DOM path 対応表(qa/part_mapping.yaml)。Qtの
    # findChildren順とDOMツリーは構造が全く違うので、path文字列の直接一致では
    # 対応が取れない -- 計画書(plans/2026-08-20_*_v1.3.md)通り、人手で1回作った
    # 対応表を経由してのみ突き合わせる。
    part_mapping_path = REPO_ROOT / "qa" / "part_mapping.yaml"
    part_mapping = {}
    extra_in_cpp = []
    if part_mapping_path.exists():
        mapping_doc = yaml.safe_load(part_mapping_path.read_text(encoding="utf-8")) or {}
        part_mapping = mapping_doc.get("mappings", {}) or {}
        extra_in_cpp = mapping_doc.get("extra_in_cpp", []) or []

    def describe_part(p):
        r = p["rect"]
        label = p["object_name"] or p["class"]
        if p["hsv"] is None:
            return f"{label}({p['class']})は座標({r['x']},{r['y']})・サイズ{r['w']}×{r['h']}pxで検出されたが、背景色のHSV取得に失敗した"
        h, s, v = p["hsv"]["h"], p["hsv"]["s"], p["hsv"]["v"]
        rgb = p["hsv"]["rgb"]
        hexcode = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        return (
            f"{label}({p['class']})は座標({r['x']},{r['y']})に実測サイズ{r['w']}×{r['h']}pxで配置され、"
            f"代表色はHSV({h:.0f}°,{s:.0f}%,{v:.0f}%)/{hexcode}として実測された"
        )

    parts_ok = 0
    parts_cpp_measured = 0
    parts_cpp_matched = 0
    rows_parts = []
    # Python's findChildren can return several parts with the IDENTICAL path
    # string (e.g. three unlabeled QToolBar separator QWidgets) -- a plain
    # {python_path: cpp_path} dict can only ever point at one of them, so
    # part_mapping.yaml may disambiguate repeats with a 1-based "path[N]"
    # suffix (N = which occurrence, in list order); look that up first and
    # fall back to the plain path for everything that isn't duplicated.
    path_occurrence = {}
    for p in parts:
        r = p["rect"]
        rect_valid = r["w"] > 0 and r["h"] > 0
        hsv_valid = p["hsv"] is not None
        ok = rect_valid and hsv_valid
        parts_ok += 1 if ok else 0
        row_class = "pass" if ok else "fail"
        mark = "PASS" if ok else "FAIL"
        reason = "" if ok else (" rect不正" if not rect_valid else "") + (" HSV取得失敗" if not hsv_valid else "")

        occurrence = path_occurrence.get(p["path"], 0) + 1
        path_occurrence[p["path"]] = occurrence
        indexed_key = f"{p['path']}[{occurrence}]"
        mapped_cpp_path = part_mapping.get(indexed_key) or part_mapping.get(p["path"])
        cpp_p = cpp_parts_by_path.get(mapped_cpp_path) if mapped_cpp_path else None
        if cpp_p is None:
            cpp_rect_cell = f'<td class="cpp-missing">{CPP_NOT_MEASURED}</td>'
            cpp_hsv_cell_html = f'<td class="hsv cpp-missing">{CPP_NOT_MEASURED}</td>'
            cpp_desc_cell = f'<td class="cpp-missing">{CPP_NOT_MEASURED}</td>'
        else:
            parts_cpp_measured += 1
            match = parts_match(p, cpp_p)
            if match:
                parts_cpp_matched += 1
            cr = cpp_p["rect"]
            match_mark = "&#10003; 一致" if match else "&#10007; 不一致"
            match_class = "match-ok" if match else "match-bad"
            cpp_rect_cell = f'<td><span class="{match_class}">{match_mark}</span> {cr["x"]},{cr["y"]} {cr["w"]}x{cr["h"]}</td>'
            cpp_hsv_cell_html = hsv_cell(cpp_p["hsv"])
            cpp_desc_cell = f"<td>{html.escape(describe_part(cpp_p))}</td>"

        rows_parts.append(
            f'<tr class="{row_class}">'
            f'<td class="mark">{mark}{html.escape(reason)}</td>'
            f"<td>{html.escape(p['path'])}</td>"
            f"<td>{html.escape(p['class'])}</td>"
            f"<td>{r['x']},{r['y']} {r['w']}x{r['h']}</td>"
            f"{hsv_cell(p['hsv'])}"
            f"{cpp_rect_cell}"
            f"{cpp_hsv_cell_html}"
            f"<td>{html.escape(describe_part(p))}</td>"
            f"{cpp_desc_cell}"
            "</tr>"
        )

    actions_verified = 0
    actions_verified_cpp = 0
    actions_checkable = 0
    rows_actions = []
    for a in actions:
        text = a["text"]
        shortcut = a["shortcut"]
        is_sep = a.get("separator", False)

        check_names = []
        row_class = "warn"
        no_check_needed = False  # True = 意図的に個別チェック対象外(入口/既定値など)、隠さず理由を出す
        if is_sep:
            desc = "ツールバー/メニューの区切り線(セパレータ)。ラベルもショートカットも持たない実データで、操作対象ではない"
            row_class = "sep"
            no_check_needed = True
        elif not text and shortcut:
            check_names = SHORTCUT_CHECK_MAP.get(shortcut, [])
            desc = SHORTCUT_BEHAVIOR_DESC.get(shortcut, "")
        elif not text and not shortcut:
            if "QMenuBar" in a["path"]:
                desc = ("メニューバーの内部アクション。text/shortcutともに空でセパレータでもない。"
                        "window.show()後にのみ出現するため、Qt内部実装(メニューバーのオーバーフロー処理等)が自動生成したものと推定。"
                        "ユーザーが操作できるUI要素ではない")
            else:
                desc = "画面上のボタン/メニュー項目としては現れない内部用トグルアクション(例: ツールバー自体の表示/非表示切替、Qtが自動生成)"
            row_class = "internal"
            no_check_needed = True
        else:
            key = (text, shortcut) if (text, shortcut) in ACTION_CHECK_MAP else (text, "")
            if key in ACTION_CHECK_MAP:
                check_names = ACTION_CHECK_MAP[key]
                no_check_needed = not check_names
            desc = ACTION_BEHAVIOR_DESC.get(text, "")
            if text == "設定":
                desc += " (実際の検証は子項目「環境設定...」の行を参照)"
            elif text in ("Main Toolbar", "Thumbnail Size Toolbar"):
                desc = "ツールバー自体の表示/非表示を切り替えるトグルアクション(QMainWindowが自動生成。メニューには未接続のため画面上には現れない)"
            elif text == "サムネ":
                desc = "ラベル表示専用のツールバー項目(QLabelを埋め込んだもの)。クリックしても何も起きない"

        matched = [behaviors_by_name[n] for n in check_names if n in behaviors_by_name]
        if not is_sep and (text or shortcut) and check_names:
            actions_checkable += 1
        if matched:
            all_pass = all(m["pass"] for m in matched)
            n_pass = sum(1 for m in matched if m["pass"])
            if all_pass:
                verdict = f"PASS({n_pass}/{len(matched)})"
                if not is_sep:
                    actions_verified += 1
                row_class = "pass"
            else:
                verdict = f"FAIL({n_pass}/{len(matched)})"
                row_class = "fail"
            evidence = " / ".join(f"[{'PASS' if m['pass'] else 'FAIL'}] {m['behavior']}" for m in matched)
            desc = f"{desc} {evidence}" if desc else evidence
        elif no_check_needed:
            verdict = "-"
            row_class = "internal" if row_class == "warn" else row_class
        else:
            verdict = "未検証"
            row_class = "warn"

        cpp_matched = [cpp_behaviors_by_name[n] for n in check_names if n in cpp_behaviors_by_name]
        if cpp_matched:
            cpp_n_pass = sum(1 for m in cpp_matched if m["pass"])
            cpp_all_pass = cpp_n_pass == len(cpp_matched)
            if cpp_all_pass and not is_sep:
                actions_verified_cpp += 1
            cpp_verdict = f"PASS({cpp_n_pass}/{len(cpp_matched)})" if cpp_all_pass else f"FAIL({cpp_n_pass}/{len(cpp_matched)})"
            cpp_verdict_cell = f'<td class="mark">{html.escape(cpp_verdict)}</td>'
            cpp_evidence = " / ".join(f"[{'PASS' if m['pass'] else 'FAIL'}] {m['behavior']}" for m in cpp_matched)
            cpp_desc_cell = f"<td>{html.escape(cpp_evidence)}</td>"
        elif no_check_needed:
            cpp_verdict_cell = '<td class="mark">-</td>'
            cpp_desc_cell = "<td>-</td>"
        else:
            cpp_verdict_cell = f'<td class="mark cpp-missing">{CPP_NOT_MEASURED}</td>'
            cpp_desc_cell = f'<td class="cpp-missing">{CPP_NOT_MEASURED}</td>'

        rows_actions.append(
            f'<tr class="{row_class}">'
            f'<td class="mark">{html.escape(verdict)}</td>'
            f"{cpp_verdict_cell}"
            f"<td>{html.escape(a['path'])}</td>"
            f"<td>{html.escape(text) or ('(セパレータ)' if is_sep else '(空 = ツールバー非表示)')}</td>"
            f"<td>{html.escape(shortcut) or '-'}</td>"
            f"<td>{'✓' if a['enabled'] else '×'}</td>"
            f"<td>{html.escape(desc)}</td>"
            f"{cpp_desc_cell}"
            "</tr>"
        )

    behaviors_cpp_measured = 0
    behaviors_cpp_passed = 0
    rows_behaviors = []
    if behaviors:
        for r in behaviors["results"]:
            row_class = "pass" if r["pass"] else "fail"
            mark = "PASS" if r["pass"] else "FAIL"
            err = f'<div class="err">例外: {html.escape(r["error"])}</div>' if r.get("error") else ""

            cpp_r = cpp_behaviors_by_name.get(r["name"])
            if cpp_r is not None:
                behaviors_cpp_measured += 1
                if cpp_r["pass"]:
                    behaviors_cpp_passed += 1
                cpp_behavior_cell = f'<td>{html.escape(cpp_r["behavior"] or "-")}</td>'
            else:
                cpp_behavior_cell = f'<td class="cpp-missing">{CPP_NOT_MEASURED}</td>'

            rows_behaviors.append(
                f'<tr class="{row_class}">'
                f'<td class="mark">{mark}</td>'
                f'{cpp_mark_cell(cpp_r)}'
                f'<td>{html.escape(r["name"])}</td>'
                f'<td>{html.escape(r["behavior"] or "-")}{err}</td>'
                f'{cpp_behavior_cell}'
                "</tr>"
            )

    # C++側にのみ存在し、Python版に対応が無い要素(qa/part_mapping.yamlのextra_in_cpp)。
    # 「対応がつけられない」を理由に消さず、常に不一致(FAIL)として明示する。
    rows_extra_cpp = []
    cpp_actions_by_path = {a["path"]: a for a in cpp_data.get("actions", [])} if cpp_data else {}
    for item in extra_in_cpp:
        epath = item["path"]
        note = item.get("note", "")
        ea = cpp_actions_by_path.get(epath)
        ep = cpp_parts_by_path.get(epath)
        text = ea["text"] if ea else (ep["object_name"] if ep else epath)
        enabled = ("✓" if ea["enabled"] else "×") if ea else "-"
        measured = "✓ 実機で確認済み" if (ea or ep) else f'<span class="cpp-missing">{CPP_NOT_MEASURED}</span>'
        rows_extra_cpp.append(
            '<tr class="fail">'
            '<td class="mark">FAIL</td>'
            f"<td>{html.escape(epath)}</td>"
            f"<td>{html.escape(text)}</td>"
            f"<td>{enabled}</td>"
            f"<td>{measured}</td>"
            f"<td>{html.escape(note)}</td>"
            "</tr>"
        )
    extra_cpp_section = ""
    if extra_in_cpp:
        extra_cpp_section = f"""
<h2>C++版にのみ存在する要素(Python版に対応なし = 仕様との不一致)</h2>
<div class="behavior-summary"><b>{len(extra_in_cpp)} 件</b>(qa/part_mapping.yamlのextra_in_cppに記録。対応がつけられないからと隠さず、常にFAILとして表示)</div>
<table>
<tr><th>結果</th><th>C++側パス</th><th>テキスト</th><th>有効</th><th>C++側での実測</th><th>理由</th></tr>
{''.join(rows_extra_cpp)}
</table>
"""

    screenshot_html = ""
    if screenshot_b64:
        screenshot_html = (
            '<h2>ウィンドウ全体スクリーンショット</h2>'
            f'<img class="shot" src="data:image/png;base64,{screenshot_b64}" alt="screenshot">'
        )

    behavior_section = ""
    if behaviors:
        behavior_section = f"""
<h2>機能・操作チェック結果(Python版を直接操作して確認・C++版と横並びで比較)</h2>
<div class="behavior-summary"><b>Python: {behaviors['passed']}/{behaviors['total']} 件PASS</b> ／ <b>C++: {behaviors_cpp_measured}/{behaviors['total']} 件計測済み</b>(灰色「{CPP_NOT_MEASURED}」=C++側の測定プログラム未実装のため未計測)</div>
<table>
<tr><th>結果(Python)</th><th>結果(C++)</th><th>チェック名</th><th>実際に確認した挙動(Python)</th><th>実際に確認した挙動(C++)</th></tr>
{''.join(rows_behaviors)}
</table>
"""

    kind_labels = {"baseline": "見た目・座標計測", "behaviors": "機能・操作チェック"}
    source_labels = {"python": "Python", "cpp": "C++"}
    history_rows = []
    for run in db.recent_runs(30):
        kind_label = kind_labels.get(run["kind"], run["kind"])
        source_label = source_labels.get(run["source"], run["source"])
        passed_cell = "-" if run["passed"] is None else f"{run['passed']}/{run['total']}"
        history_rows.append(
            f"<tr><td>{html.escape(run['timestamp'])}</td><td>{kind_label}</td>"
            f"<td>{source_label}</td><td>{run['total']}</td><td>{passed_cell}</td></tr>"
        )
    history_html = f"""
<h2>実行履歴(qa/qa_history.db。実行のたびに追記され、過去分は消えない)</h2>
<div class="behavior-summary">直近{len(history_rows)}件(新しい順)。全履歴は qa/qa_history.db をSQLiteで直接参照。</div>
<table>
<tr><th>日時(UTC)</th><th>種別</th><th>対象</th><th>件数</th><th>PASS</th></tr>
{''.join(history_rows) if history_rows else '<tr><td colspan="5">まだ記録がありません(各qa/*.pyスクリプトを実行すると自動的に記録されます)</td></tr>'}
</table>
"""

    total_python_checks = behaviors["total"] + len(parts) + actions_checkable if behaviors else len(parts) + actions_checkable
    total_cpp_pass = behaviors_cpp_passed + parts_cpp_matched + actions_verified_cpp
    overall_pct = round(100 * total_cpp_pass / total_python_checks, 1) if total_python_checks else 0.0

    html_out = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body {{ font-family: "Segoe UI", "Yu Gothic UI", sans-serif; margin: 24px; background:#f5f5f5; color:#202020; }}
h1 {{ font-size: 20px; }}
h2 {{ font-size: 15px; margin-top: 32px; }}
table {{ border-collapse: collapse; width: 100%; background:#fff; font-size: 12px; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; vertical-align: middle; }}
th {{ background: #eee; position: sticky; top: 0; }}
.swatch {{ display:inline-block; width:14px; height:14px; border:1px solid #999; vertical-align:middle; margin-right:6px; }}
.no-text {{ background: #fff8dc; }}
.shot {{ max-width: 100%; border: 1px solid #999; }}
.summary {{ background:#fff; padding:10px 16px; border:1px solid #ddd; display:inline-block; }}
tr.pass td.mark {{ background:#d4edda; color:#155724; font-weight:bold; }}
tr.fail td.mark {{ background:#f8d7da; color:#721c24; font-weight:bold; }}
tr.fail {{ background:#fff5f5; }}
.err {{ color:#a00; font-size:11px; margin-top:2px; }}
.behavior-summary {{ font-size:14px; margin: 8px 0 16px; }}
tr.sep td {{ background:#f0f0f0; color:#888; }}
tr.internal td {{ background:#f7f7f7; color:#666; }}
tr.warn td.mark {{ background:#fff3cd; color:#856404; font-weight:bold; }}
td.cpp-missing {{ background:#f0f0f0; color:#999; font-style:italic; }}
.match-ok {{ color:#155724; font-weight:bold; }}
.match-bad {{ color:#721c24; font-weight:bold; }}
.progress-banner {{ display:flex; gap:16px; flex-wrap:wrap; background:#fff; border:1px solid #ddd; border-radius:8px; padding:20px 24px; margin:16px 0 24px; }}
.progress-cell {{ flex:1; min-width:160px; text-align:center; }}
.progress-cell .num {{ font-size:44px; font-weight:800; line-height:1.1; }}
.progress-cell .num small {{ font-size:20px; font-weight:600; color:#888; }}
.progress-cell .label {{ font-size:13px; color:#555; margin-top:4px; }}
.progress-cell.overall .num {{ color:#0d6efd; }}
.progress-cell.zero .num {{ color:#721c24; }}
</style></head>
<body>
<h1>{html.escape(title)}</h1>
<div class="progress-banner">
  <div class="progress-cell overall">
    <div class="num">{overall_pct}<small>%</small></div>
    <div class="label">総合進捗(C++が一致/PASSした割合)<br>{total_cpp_pass}/{total_python_checks}件</div>
  </div>
  <div class="progress-cell{' zero' if behaviors['total'] and behaviors_cpp_passed == 0 else ''}">
    <div class="num">{behaviors_cpp_passed}<small>/{behaviors['total']}</small></div>
    <div class="label">機能・操作(C++ PASS)<br>Python: {behaviors['passed']}/{behaviors['total']}</div>
  </div>
  <div class="progress-cell{' zero' if len(parts) and parts_cpp_matched == 0 else ''}">
    <div class="num">{parts_cpp_matched}<small>/{len(parts)}</small></div>
    <div class="label">見た目・座標一致(C++)<br>計測済み{parts_cpp_measured}件中{parts_cpp_matched}件一致</div>
  </div>
  <div class="progress-cell{' zero' if actions_checkable and actions_verified_cpp == 0 else ''}">
    <div class="num">{actions_verified_cpp}<small>/{actions_checkable}</small></div>
    <div class="label">アクション検証(C++ PASS)<br>Python: {actions_verified}/{actions_checkable}</div>
  </div>
</div>
<div class="summary">パーツ数: {len(parts)} / アクション数: {len(actions)} / ウィンドウサイズ: {data.get('window_size')}{' / C++側は未計測(qa/extract_cpp.py・qa/check_behaviors_cpp.py未実装)' if cpp_data is None and not cpp_behaviors_by_name else ''}</div>
{screenshot_html}
{behavior_section}
<h2>パーツ一覧(サイズ・HSV実測。Python/C++を横並びで比較。各行に実測内容をプロースで記述)</h2>
<div class="behavior-summary"><b>Python: {parts_ok}/{len(parts)} 件で座標・HSVとも正常に取得できた</b> ／ <b>C++: {parts_cpp_measured}/{len(parts)} 件計測済み</b>(測定自体が成功したかの自己整合性チェック。灰色「{CPP_NOT_MEASURED}」=C++側未計測)</div>
<table>
<tr><th>結果</th><th>パス</th><th>クラス</th><th>座標(Python)</th><th>HSV(Python)</th><th>座標(C++)</th><th>HSV(C++)</th><th>実測内容(Python)</th><th>実測内容(C++)</th></tr>
{''.join(rows_parts)}
</table>
<h2>アクション一覧(実際にトリガーした時の挙動を記述し、対応する自動チェックのPASS/FAILをPython/C++で突き合わせ)</h2>
<div class="behavior-summary"><b>Python: {actions_verified}/{actions_checkable} 件で対応チェックが全てPASS</b>(灰色行=セパレータ/内部専用アクションで検証対象外、黄色「未検証」=対応する自動チェックが未実装、灰色「{CPP_NOT_MEASURED}」=C++側未計測)</div>
<table>
<tr><th>結果(Python)</th><th>結果(C++)</th><th>パス</th><th>テキスト</th><th>ショートカット</th><th>有効</th><th>挙動(Python、実際に観察した内容を含む)</th><th>挙動(C++)</th></tr>
{''.join(rows_actions)}
</table>
{extra_cpp_section}
{history_html}
</body></html>
"""
    out_html.write_text(html_out, encoding="utf-8")
    print(f"[完了] {out_html}")


if __name__ == "__main__":
    build(
        REPO_ROOT / "qa" / "baseline.json",
        REPO_ROOT / "qa" / "dashboard.html",
        "QuickMarkPDF QA Dashboard - Python版ベースライン",
        behaviors_json=REPO_ROOT / "qa" / "behaviors.json",
        # C++側の計測プログラムはまだ実装していない(次のステップ)。
        # qa/baseline_cpp.json・qa/behaviors_cpp.json ができれば自動的にC++列が埋まる。
        cpp_source_json=REPO_ROOT / "qa" / "baseline_cpp.json",
        cpp_behaviors_json=REPO_ROOT / "qa" / "behaviors_cpp.json",
    )
