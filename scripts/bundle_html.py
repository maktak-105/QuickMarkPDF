import base64
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)


def bundle(output_dir=None):
    ui = os.path.join(ROOT, "src", "ui")
    with open(os.path.join(ui, "index.html"), encoding="utf-8") as stream:
        html = stream.read()
    with open(os.path.join(ui, "css", "style.css"), encoding="utf-8") as stream:
        css = stream.read()
    with open(os.path.join(ui, "js", "i18n.js"), encoding="utf-8") as stream:
        i18n_js = stream.read()
    with open(os.path.join(ui, "js", "app.js"), encoding="utf-8") as stream:
        app_js = stream.read()

    body_start = html.find("<body>")
    body_end = html.find("</body>")
    if body_start < 0 or body_end < 0 or body_end <= body_start:
        raise ValueError("src/ui/index.html must contain a valid body element")
    body = html[body_start + len("<body>"):body_end]
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.IGNORECASE | re.DOTALL)

    def inline_image(match):
        src = match.group(2)
        if src.startswith(("data:", "http://", "https://")):
            return match.group(0)
        path = os.path.normpath(os.path.join(ui, src))
        if not os.path.isfile(path):
            print(f"[警告] 画像が見つかりません: {path}")
            return match.group(0)
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        return f"{match.group(1)}data:{mime};base64,{encoded}{match.group(3)}"

    body = re.sub(r'(<img\b[^>]*\bsrc=")([^"]+)(")', inline_image, body, flags=re.IGNORECASE)
    result = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>QuickMarkPDF</title><style>{css}</style>
<script>window.MathJax = {{tex: {{inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]}}, svg: {{fontCache: 'global'}}}};</script>
<script defer src="vendor/mathjax/tex-svg.js"></script><script defer src="vendor/mermaid/mermaid.min.js"></script>
</head><body>{body}
<script>{i18n_js}</script><script>{app_js}</script></body></html>'''
    output_dir = output_dir or os.path.join(ROOT, "build", "intermediate")
    os.makedirs(output_dir, exist_ok=True)
    destination = os.path.join(output_dir, "index.html")
    with open(destination, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(result)
    print(f"[完了] 自己完結HTMLを生成しました: {destination} ({len(result)} bytes)")
    return destination


if __name__ == "__main__":
    bundle()
