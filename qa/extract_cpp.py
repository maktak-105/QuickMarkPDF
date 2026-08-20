"""Extract the C++/WebView2 QuickMarkPDF.exe's UI as numeric ground truth,
via Selenium + Microsoft Edge WebDriver (see selenium_client.py) -- the
C++-side counterpart to extract_python.py. Uses the identical HSV-sampling
algorithm (color_utils.representative_hsv) so both sides are measured
symmetrically (see the "risk" note in
plans/2026-08-20_C++版Python完全一致化_v1.3.md about asymmetric measurement
being a source of checker bugs).

Walks every visible DOM element with a single execute_script call
(getBoundingClientRect() per element -- the DOM counterpart of Python's
findChildren(QWidget) + .geometry()), takes one screenshot, and samples HSV
from it exactly like extract_python.py samples from QWidget.grab().

Output: qa/baseline_cpp.json (same shape as qa/baseline.json). Path strings
are NOT directly comparable to Python's widget paths -- Qt's widget tree and
the DOM tree have unrelated shapes -- see qa/part_mapping.yaml, which
dashboard.py uses to cross-reference the two.

Run: .venv\\Scripts\\python.exe qa\\extract_cpp.py
"""
import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "qa"))
from selenium_client import connect, disconnect  # noqa: E402
from color_utils import representative_hsv  # noqa: E402
import db  # noqa: E402

EXE_PATH = REPO_ROOT / "dist" / "binary" / "QuickMarkPDF.exe"

# Structurally the DOM equivalent of extract_python.py's findChildren(QWidget)
# walk: every visible element's window-relative rect, tag/id/class, and (for
# leaf elements) its own text -- gathered in one round-trip instead of one
# call per element.
DOM_WALK_JS = r"""
function widgetPath(el) {
  const names = [];
  let e = el;
  while (e && e.nodeType === 1) {
    names.push(e.id || e.tagName.toLowerCase());
    e = e.parentElement;
  }
  return names.reverse().join('/');
}
const out = [];
document.querySelectorAll('*').forEach(el => {
  const cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden') return;
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return;
  let cls = el.className;
  if (cls && typeof cls === 'object' && 'baseVal' in cls) cls = cls.baseVal;  // SVGAnimatedString
  out.push({
    path: widgetPath(el),
    tag: el.tagName.toLowerCase(),
    id: el.id || '',
    cls: cls || '',
    rect: {x: r.x, y: r.y, w: r.width, h: r.height},
    text: el.childElementCount === 0 ? el.textContent.trim() : '',
    disabled: !!el.disabled,
  });
});
// A handful of elements are worth measuring as a whole but have no id of
// their own to hang a stable path on (the two toolbar <header> rows) --
// giving them one would change EVERY descendant's widgetPath() too (id is
// used at every ancestor level, not just the leaf), silently breaking every
// existing mapping keyed to the old id-less path. Measured here instead,
// by direct selector, under a synthetic path that can't collide with
// anything widgetPath() itself would ever produce.
[
  ['html/body/header[toolbar-1]', 'header.toolbar:not(.size-toolbar)'],
  ['html/body/header[toolbar-2]', 'header.toolbar.size-toolbar'],
].forEach(([path, selector]) => {
  const el = document.querySelector(selector);
  if (!el) return;
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return;
  out.push({ path, tag: el.tagName.toLowerCase(), id: el.id || '', cls: el.className || '',
             rect: {x: r.x, y: r.y, w: r.width, h: r.height}, text: '', disabled: false });
});
// Python's central QWidget (setCentralWidget) is #pdf-workspace's box BEFORE
// its own CSS margin is applied -- reconstruct it from getComputedStyle
// rather than adding a real wrapper element just to measure it.
(() => {
  const el = document.querySelector('#pdf-workspace');
  if (!el) return;
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  const mt = parseFloat(cs.marginTop) || 0, mr = parseFloat(cs.marginRight) || 0;
  const mb = parseFloat(cs.marginBottom) || 0, ml = parseFloat(cs.marginLeft) || 0;
  out.push({
    path: 'html/body[central-widget]', tag: el.tagName.toLowerCase(), id: '', cls: '',
    rect: {x: r.x - ml, y: r.y - mt, w: r.width + ml + mr, h: r.height + mt + mb},
    text: '', disabled: false,
  });
})();
return {
  elements: out,
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
  devicePixelRatio: window.devicePixelRatio,
};
"""


def main():
    if not EXE_PATH.exists():
        raise SystemExit(f"{EXE_PATH} が見つかりません。先に build_native.py でビルドしてください。")

    proc, driver = connect(EXE_PATH)
    try:
        payload = driver.execute_script(DOM_WALK_JS)
        elements = payload["elements"]

        png_bytes = driver.get_screenshot_as_png()
        pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGB")

        # getBoundingClientRect() is in CSS px; the screenshot can be in
        # device px if devicePixelRatio != 1. Scale rects onto the actual
        # screenshot pixel grid before sampling color from it.
        scale_x = pil_img.width / payload["innerWidth"] if payload["innerWidth"] else 1.0
        scale_y = pil_img.height / payload["innerHeight"] if payload["innerHeight"] else 1.0

        parts = []
        actions = []
        for el in elements:
            r = el["rect"]
            px_rect = {
                "x": round(r["x"] * scale_x), "y": round(r["y"] * scale_y),
                "w": round(r["w"] * scale_x), "h": round(r["h"] * scale_y),
            }
            hsv = representative_hsv(pil_img, px_rect)
            parts.append({
                "path": el["path"],
                "class": el["tag"],
                "object_name": el["id"],
                "rect": px_rect,
                "hsv": hsv,
            })
            if el["tag"] == "button":
                actions.append({
                    "path": el["path"],
                    "text": el["text"],
                    "tooltip": "",
                    "shortcut": "",
                    "checkable": False,
                    "enabled": not el["disabled"],
                    "separator": False,
                })

        png_buf = io.BytesIO()
        pil_img.save(png_buf, format="PNG")
        screenshot_b64 = base64.b64encode(png_buf.getvalue()).decode("ascii")

        out = {
            "source": "cpp",
            "window_size": {"w": payload["innerWidth"], "h": payload["innerHeight"]},
            "screenshot_size": {"w": pil_img.width, "h": pil_img.height},
            "device_pixel_ratio": payload["devicePixelRatio"],
            "screenshot_png_base64": screenshot_b64,
            "parts": parts,
            "actions": actions,
        }
        out_path = REPO_ROOT / "qa" / "baseline_cpp.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[完了] パーツ{len(parts)}件、アクション{len(actions)}件を計測 -> {out_path}")
        db.record_baseline_run("cpp", parts, actions)
        return out
    finally:
        disconnect(proc, driver)


if __name__ == "__main__":
    main()
