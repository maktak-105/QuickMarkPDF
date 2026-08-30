"""Extract the Python/PySide6 MainWindow's UI as numeric ground truth.

For every visible widget: window-relative bounding box (px) and a
representative HSV color sampled from a single full-window screenshot
(QWidget.grab()). For every QAction: text/tooltip/shortcut/checkable/enabled.

This is the "spec of record" baseline (plans/2026-08-20_C++版Python完全一致化_v1.3.md,
section 0). Output: qa/baseline.json.

Run: .venv\\Scripts\\python.exe qa\\extract_python.py
"""
import os
import sys
import json
import base64
import io
from pathlib import Path

# Deliberately NOT forcing QT_QPA_PLATFORM=offscreen: this sandbox's offscreen
# Qt platform has no CJK-capable font (documented in document/environment.md),
# so Japanese UI text renders as tofu boxes and the screenshot is useless for
# a human to review. We run on a real, live Windows desktop session (this is
# exactly what environment.md's "real_screen" tier exists for), so the native
# "windows" platform renders real fonts -- at the cost of a window briefly
# appearing on screen during capture.

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "prototype"))
sys.path.insert(0, str(REPO_ROOT / "qa"))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from PySide6.QtGui import QAction, QImage  # noqa: E402
from PIL import Image  # noqa: E402
from color_utils import representative_hsv
import db  # noqa: E402


def qimage_to_pil(qimage: QImage):
    """Convert a QImage to a PIL Image -- the SAME representation
    extract_cpp.py decodes its CDP screenshot into, so both sides run the
    identical representative_hsv() on the identical image type.
    """
    qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    width = qimage.width()
    height = qimage.height()
    bpl = qimage.bytesPerLine()
    ptr = qimage.bits()
    if hasattr(ptr, "setsize"):
        ptr.setsize(height * bpl)
    buf = bytes(ptr)
    img = Image.frombuffer("RGBA", (width, height), buf, "raw", "RGBA", bpl, 1)
    return img.convert("RGB"), width, height


def widget_path(widget) -> str:
    names = []
    w = widget
    while w is not None:
        name = w.objectName()
        if not name:
            # A QToolButton auto-generated from a QAction has no objectName,
            # so several buttons in the same toolbar all fall back to the
            # same class name ("QToolButton") -- indistinguishable, which
            # breaks any path-based Python<->C++ part mapping. Use the
            # associated action's text instead so each one is unique.
            default_action = getattr(w, "defaultAction", None)
            action = default_action() if callable(default_action) else None
            if action is not None and action.text():
                name = f"{type(w).__name__}:{action.text()}"
            else:
                name = type(w).__name__
        names.append(name)
        w = w.parentWidget() if hasattr(w, "parentWidget") else w.parent()
    return "/".join(reversed(names))


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    from src.pdf_editor.ui.main_window import MainWindow  # noqa: E402

    window = MainWindow()
    window.resize(1024, 768)
    window.show()
    for _ in range(10):
        app.processEvents()

    qimage = window.grab().toImage()
    pil_img, img_w, img_h = qimage_to_pil(qimage)

    parts = []
    seen_ids = set()
    candidates = [window] + window.findChildren(QWidget)
    for widget in candidates:
        if id(widget) in seen_ids:
            continue
        seen_ids.add(id(widget))
        if not widget.isVisible():
            continue

        if widget is window:
            rect = {"x": 0, "y": 0, "w": window.width(), "h": window.height()}
        else:
            top_left = widget.mapTo(window, widget.rect().topLeft())
            rect = {"x": top_left.x(), "y": top_left.y(), "w": widget.width(), "h": widget.height()}

        if rect["w"] <= 0 or rect["h"] <= 0:
            continue

        parts.append({
            "path": widget_path(widget),
            "class": type(widget).__name__,
            "object_name": widget.objectName(),
            "rect": rect,
            "hsv": representative_hsv(pil_img, rect),
        })

    actions = []
    for action in window.findChildren(QAction):
        parent = action.parent()
        parent_path = widget_path(parent) if parent is not None else "?"
        actions.append({
            "path": f"{parent_path}/action:{action.objectName() or action.text()}",
            "text": action.text(),
            "tooltip": action.toolTip(),
            "shortcut": action.shortcut().toString(),
            "checkable": action.isCheckable(),
            "enabled": action.isEnabled(),
            "separator": action.isSeparator(),
        })

    png_buf = io.BytesIO()
    pil_img.save(png_buf, format="PNG")
    screenshot_b64 = base64.b64encode(png_buf.getvalue()).decode("ascii")

    out = {
        "source": "python",
        "window_size": {"w": window.width(), "h": window.height()},
        "screenshot_size": {"w": img_w, "h": img_h},
        "screenshot_png_base64": screenshot_b64,
        "parts": parts,
        "actions": actions,
    }

    out_path = REPO_ROOT / "qa" / "baseline.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[完了] パーツ{len(parts)}件、アクション{len(actions)}件を計測 -> {out_path}")
    db.record_baseline_run("python", parts, actions)
    window.close()
    return out


if __name__ == "__main__":
    main()
