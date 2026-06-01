"""
PDF Editor アプリアイコン生成スクリプト
スーパーサンプリング: 1024px で描画 → LANCZOS で各サイズに縮小
出力: resources/app_icon.png  (256x256 プレビュー用)
      resources/app_icon.ico  (PyInstaller 用 / 複数サイズ埋め込み)
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

# ── パレット ────────────────────────────────────────────────
BG_DARK   = (22,  38,  54)   # ダークネイビー
DOC_WHITE = (245, 248, 250)  # ほぼ白いドキュメント
FOLD_GRAY = (195, 210, 224)  # 折り目
RED       = (196,  56,  40)  # PDF ラベル
LINE_BLUE = (170, 195, 218)  # コンテンツ模擬ライン

MASTER = 1024  # 描画解像度（この後 LANCZOS で縮小）


def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/verdanab.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/verdana.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_master() -> Image.Image:
    """1024×1024 のマスター画像を生成する。"""
    s = MASTER
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    # ── 背景（角丸正方形）──────────────────────────────────
    bg_r = int(s * 0.14)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=bg_r, fill=BG_DARK)

    # ── ドキュメント本体 ────────────────────────────────────
    DL = int(s * 0.165);  DT = int(s * 0.130)
    DR = s - int(s * 0.165); DB = s - int(s * 0.130)
    FOLD = int(s * 0.145)

    doc_pts = [
        (DL, DT), (DR - FOLD, DT),
        (DR, DT + FOLD), (DR, DB), (DL, DB),
    ]
    d.polygon(doc_pts, fill=DOC_WHITE)

    fold_pts = [(DR - FOLD, DT), (DR, DT + FOLD), (DR - FOLD, DT + FOLD)]
    d.polygon(fold_pts, fill=FOLD_GRAY)

    # 折り目の境界線
    border_w = max(2, s // 256)
    d.line([(DR - FOLD, DT), (DR, DT + FOLD)], fill=(215, 228, 240), width=border_w)

    # ── PDF ラベル（赤い帯）──────────────────────────────────
    pad  = int(s * 0.055)
    LT   = DT + int(s * 0.095)
    LB   = LT + int(s * 0.165)
    LR   = DR - FOLD - int(s * 0.020)
    d.rounded_rectangle([DL + pad, LT, LR, LB], radius=int(s * 0.025), fill=RED)

    font = load_font(int(s * 0.145))
    txt  = "PDF"
    bbox = d.textbbox((0, 0), txt, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    lx   = (DL + pad + LR) // 2 - tw // 2
    ly   = (LT + LB) // 2 - th // 2 - s // 64
    d.text((lx, ly), txt, fill=(255, 255, 255), font=font)

    # ── コンテンツ模擬ライン ────────────────────────────────
    line_l = DL + pad
    line_r = DR - FOLD - int(s * 0.04)
    line_h = max(6, int(s * 0.022))
    gap    = int(s * 0.065)
    y      = LB + int(s * 0.075)
    for ratio in [0.88, 0.70, 0.92, 0.58]:
        w = int((line_r - line_l) * ratio)
        d.rounded_rectangle([line_l, y, line_l + w, y + line_h],
                            radius=line_h // 2, fill=LINE_BLUE)
        y += gap
        if y + line_h > DB - int(s * 0.04):
            break

    return img


def downscale(master: Image.Image, size: int) -> Image.Image:
    """LANCZOS + UnsharpMask でシャープに縮小する。
    UnsharpMask は RGBA 非対応なので RGB/alpha を分離して処理する。
    """
    resized = master.resize((size, size), Image.LANCZOS)
    if size >= 32 and resized.mode == "RGBA":
        r, g, b, a = resized.split()
        rgb = Image.merge("RGB", (r, g, b))
        rgb = rgb.filter(ImageFilter.UnsharpMask(radius=0.6, percent=130, threshold=2))
        r, g, b = rgb.split()
        resized = Image.merge("RGBA", (r, g, b, a))
    return resized


def save_ico(master: Image.Image, path: str):
    # 旧実装のバグ: frames[0]（16px）を sizes で引き伸ばしていた → ボケの原因
    # 修正: 1024px マスターを渡し、Pillow に LANCZOS で各サイズへ縮小させる
    sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
    master.save(path, format="ICO", sizes=sizes)


if __name__ == "__main__":
    os.makedirs("resources", exist_ok=True)

    master = create_master()

    ico_path = "resources/app_icon.ico"
    png_path = "resources/app_icon.png"

    save_ico(master, ico_path)
    downscale(master, 256).save(png_path)

    print(f"OK  {png_path}")
    print(f"OK  {ico_path}")
