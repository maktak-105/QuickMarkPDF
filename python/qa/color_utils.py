"""Shared pixel-sampling logic used by BOTH extract_python.py and
extract_cpp.py, so the two sides measure color with the literally identical
algorithm (not just a conceptually similar one) -- see the "risk" note in
plans/2026-08-20_C++版Python完全一致化_v1.3.md about asymmetric measurement
being a source of checker bugs.
"""
import colorsys
from collections import Counter


def representative_hsv(pil_img, rect, margin=4):
    """Most-common RGB color within rect (a dict with x/y/w/h), shrunk by
    `margin` px on each side to dodge anti-aliased edges. Returns None if the
    rect is empty after clamping to the image bounds.
    """
    x0, y0, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    if w > margin * 2 and h > margin * 2:
        x0, y0, w, h = x0 + margin, y0 + margin, w - margin * 2, h - margin * 2
    x1, y1 = x0 + w, y0 + h
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = min(pil_img.width, int(x1))
    y1 = min(pil_img.height, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None

    step_x = max(1, (x1 - x0) // 40)
    step_y = max(1, (y1 - y0) // 40)
    counter = Counter()
    px = pil_img.load()
    for y in range(y0, y1, step_y):
        for x in range(x0, x1, step_x):
            counter[px[x, y][:3]] += 1
    if not counter:
        return None
    (r, g, b), _count = counter.most_common(1)[0]
    h_, s_, v_ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return {"h": round(h_ * 360, 1), "s": round(s_ * 100, 1), "v": round(v_ * 100, 1), "rgb": [r, g, b]}
