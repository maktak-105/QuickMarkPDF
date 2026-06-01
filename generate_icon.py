"""
PDF Editor アプリアイコン生成スクリプト
出力: resources/app_icon.png  (256x256 プレビュー用)
      resources/app_icon.ico  (PyInstaller 用 / 複数サイズ埋め込み)
"""
from PIL import Image, ImageDraw, ImageFont
import math, os

# ── パレット ────────────────────────────────────────────────
BG_DARK   = (22,  38,  54)   # ダークネイビー
DOC_WHITE = (245, 248, 250)  # ほぼ白いドキュメント
FOLD_GRAY = (195, 210, 224)  # 折り目
RED       = (196,  56,  40)  # PDF ラベル
LINE_BLUE = (170, 195, 218)  # コンテンツ模擬ライン


def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/verdanab.ttf",
        "C:/Windows/Fonts/verdana.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_rounded_rect(draw, bbox, r, fill):
    draw.rounded_rectangle(bbox, radius=r, fill=fill)


def create_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    s   = size

    # ── 背景（角丸正方形）──────────────────────────────────
    bg_r = max(6, int(s * 0.14))
    draw_rounded_rect(d, [0, 0, s - 1, s - 1], bg_r, BG_DARK)

    # ── ドキュメント本体 ────────────────────────────────────
    ml = int(s * 0.165)     # left margin
    mt = int(s * 0.130)     # top margin
    mr = int(s * 0.165)     # right margin
    mb = int(s * 0.130)     # bottom margin
    DL, DT = ml, mt
    DR, DB = s - mr, s - mb
    FOLD   = int(s * 0.145)

    # ドキュメント（折り目あり）
    doc_pts = [
        (DL, DT),
        (DR - FOLD, DT),
        (DR, DT + FOLD),
        (DR, DB),
        (DL, DB),
    ]
    d.polygon(doc_pts, fill=DOC_WHITE)

    # 折り目三角
    fold_pts = [
        (DR - FOLD, DT),
        (DR, DT + FOLD),
        (DR - FOLD, DT + FOLD),
    ]
    d.polygon(fold_pts, fill=FOLD_GRAY)

    # 折り目の境界線（白）
    d.line([(DR - FOLD, DT), (DR, DT + FOLD)], fill=(220, 233, 243), width=max(1, s // 128))

    # ── PDF ラベル（赤い帯）──────────────────────────────────
    pad  = int(s * 0.055)
    LT   = DT + int(s * 0.095)
    LB   = LT + int(s * 0.165)
    LR   = DR - FOLD - int(s * 0.02)
    label_r = max(3, int(s * 0.025))
    draw_rounded_rect(d, [DL + pad, LT, LR, LB], label_r, RED)

    font_size = max(12, int(s * 0.145))
    font      = load_font(font_size)
    txt       = "PDF"

    bbox = d.textbbox((0, 0), txt, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    lbl_cx = (DL + pad + LR) // 2
    lbl_cy = (LT + LB) // 2
    d.text((lbl_cx - tw // 2, lbl_cy - th // 2 - max(1, s // 64)),
           txt, fill=(255, 255, 255), font=font)

    # ── コンテンツ模擬ライン ────────────────────────────────
    line_left  = DL + pad
    line_right = DR - FOLD - int(s * 0.04)
    line_h     = max(2, int(s * 0.022))
    gap        = int(s * 0.065)
    ratios     = [0.88, 0.70, 0.92, 0.58]

    y = LB + int(s * 0.075)
    for ratio in ratios:
        w = int((line_right - line_left) * ratio)
        rect_r = line_h // 2
        draw_rounded_rect(d, [line_left, y, line_left + w, y + line_h], rect_r, LINE_BLUE)
        y += gap
        if y + line_h > DB - int(s * 0.04):
            break

    return img


def save_ico(img_256: Image.Image, path: str):
    sizes  = [16, 24, 32, 48, 64, 128, 256]
    frames = []
    for sz in sizes:
        resized = img_256.resize((sz, sz), Image.LANCZOS)
        frames.append(resized)
    frames[0].save(
        path, format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=frames[1:],
    )


if __name__ == "__main__":
    os.makedirs("resources", exist_ok=True)

    icon = create_icon(256)

    png_path = "resources/app_icon.png"
    ico_path = "resources/app_icon.ico"

    icon.save(png_path)
    save_ico(icon, ico_path)

    print(f"✓ {png_path}")
    print(f"✓ {ico_path}")
