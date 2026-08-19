import os
import re
import base64


def bundle(output_dir=None):
    base_dir = os.path.dirname(__file__)
    tmpl_path = os.path.join(base_dir, "templates", "index.html")
    css_path = os.path.join(base_dir, "static", "css", "style.css")
    app_path = os.path.join(base_dir, "static", "js", "app.js")

    with open(tmpl_path, "r", encoding="utf-8") as f:
        html = f.read()
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    with open(app_path, "r", encoding="utf-8") as f:
        app_js = f.read()

    # WebView2 の Navigate(file://...) は同梱先が丸ごと必要になるため、CSS/JS を
    # インライン化した自己完結HTMLを1枚生成し、配布物を index.html 単体にする。
    bundled = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuickMarkPDF</title>
  <style>
{css}
  </style>
</head>
<body>
"""
    body_start = html.find("<body>") + len("<body>")
    body_end = html.find("</body>")
    body_content = html[body_start:body_end]
    body_content = re.sub(r'<script.*?</script>', '', body_content, flags=re.DOTALL)

    # 相対パスの画像もdata URIへ埋め込む(将来の画像追加に備えた汎用処理)
    def _inline_img(match):
        prefix, src, suffix = match.group(1), match.group(2), match.group(3)
        if src.startswith("data:") or src.startswith("http://") or src.startswith("https://"):
            return match.group(0)
        img_path = os.path.normpath(os.path.join(os.path.dirname(tmpl_path), src))
        if not os.path.isfile(img_path):
            print(f"[WARN] image not found for inline: {img_path}")
            return match.group(0)
        ext = os.path.splitext(img_path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
        with open(img_path, "rb") as imgf:
            b64 = base64.b64encode(imgf.read()).decode("ascii")
        return f'{prefix}data:{mime};base64,{b64}{suffix}'

    body_content = re.sub(r'(<img\b[^>]*\bsrc=")([^"]+)(")', _inline_img, body_content)

    bundled += body_content
    bundled += f"""
  <script>
{app_js}
  </script>
</body>
</html>
"""

    if output_dir is None:
        output_dir = os.path.join(base_dir, "dist", "binary")
    os.makedirs(output_dir, exist_ok=True)
    dist_index = os.path.join(output_dir, "index.html")
    with open(dist_index, "w", encoding="utf-8") as f:
        f.write(bundled)

    print(f"[OK] Generated self-contained bundle at {dist_index} ({len(bundled)} bytes)")


if __name__ == "__main__":
    bundle()
