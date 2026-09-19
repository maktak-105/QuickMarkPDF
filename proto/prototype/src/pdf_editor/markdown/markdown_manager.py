from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import re

try:
    import markdown as markdown_lib
except ImportError:  # pragma: no cover - covered by fallback tests instead
    markdown_lib = None


_MERMAID_BLOCK_RE = re.compile(
    r"<pre><code class=\"language-mermaid\">(.*?)</code></pre>",
    re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_FENCED_CODE_SPLIT_RE = re.compile(r"(^```[\w-]*\s*$.*?^```\s*$)", re.MULTILINE | re.DOTALL)
_DISPLAY_MATH_RE = re.compile(r"(?s)(?<!\\)\$\$(.+?)(?<!\\)\$\$")
_INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?!\$)([^$\n]+?)(?<!\\)\$")


@dataclass
class MarkdownDocument:
    path: Path
    text: str

    @property
    def title(self) -> str:
        return self.path.stem or "Markdown"


class MarkdownManager:
    """Load Markdown and convert it to a browser-friendly HTML document."""

    def load_markdown(self, path: Path) -> MarkdownDocument:
        text = self._read_text(path)
        return MarkdownDocument(path=path, text=text)

    def render_html_document(self, document: MarkdownDocument, asset_urls: dict[str, str] | None = None) -> str:
        body = self._render_markdown_body(document.text)
        title = escape(document.title)
        assets = asset_urls or {}
        mermaid_url = escape(assets.get("mermaid_js_url", ""))
        mathjax_url = escape(assets.get("mathjax_js_url", ""))
        script_tags = []
        if mathjax_url:
            script_tags.append(f'  <script defer src="{mathjax_url}"></script>')
        if mermaid_url:
            script_tags.append(f'  <script defer src="{mermaid_url}"></script>')
        external_scripts = "\n".join(script_tags)
        note = (
            "Mermaid と数式の描画資産はアプリに同梱されています。"
            if mermaid_url and mathjax_url
            else "Mermaid と数式の描画資産が見つからないため、プレーンな Markdown 表示になります。"
        )
        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3efe7;
      --paper: #fffdf8;
      --ink: #1c1c1c;
      --muted: #6e665d;
      --line: #ddd4c6;
      --accent: #0d6b78;
      --code-bg: #f5f1e8;
      --quote-bg: #f7f4ed;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top right, rgba(13, 107, 120, 0.08), transparent 24rem),
        linear-gradient(180deg, #f7f3eb 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: "Segoe UI", "Yu Gothic UI", sans-serif;
      line-height: 1.7;
    }}
    .sheet {{
      width: min(960px, calc(100vw - 40px));
      margin: 24px auto 40px;
      padding: 40px 48px 56px;
      background: var(--paper);
      border: 1px solid rgba(170, 156, 137, 0.25);
      box-shadow: 0 20px 60px rgba(73, 56, 36, 0.10);
      border-radius: 18px;
    }}
    .runtime-note {{
      margin: 0 0 24px;
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px solid rgba(13, 107, 120, 0.18);
      background: rgba(13, 107, 120, 0.06);
      color: var(--muted);
      font-size: 13px;
    }}
    h1, h2, h3, h4, h5, h6 {{
      line-height: 1.25;
      margin: 1.5em 0 0.6em;
      color: #13262c;
    }}
    h1 {{
      font-size: 2.2rem;
      margin-top: 0;
      padding-bottom: 0.35em;
      border-bottom: 1px solid var(--line);
    }}
    h2 {{
      font-size: 1.6rem;
      padding-bottom: 0.25em;
      border-bottom: 1px solid rgba(221, 212, 198, 0.8);
    }}
    p, ul, ol, pre, blockquote, table {{
      margin: 0 0 1.1em;
    }}
    a {{
      color: var(--accent);
    }}
    code {{
      padding: 0.15em 0.4em;
      border-radius: 6px;
      background: var(--code-bg);
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 0.95em;
    }}
    pre {{
      overflow-x: auto;
      padding: 14px 16px;
      border-radius: 14px;
      background: #1f2430;
      color: #f4f7ff;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }}
    pre code {{
      padding: 0;
      background: transparent;
      color: inherit;
    }}
    pre.mermaid {{
      background: #fbfaf7;
      color: inherit;
      box-shadow: inset 0 0 0 1px rgba(19, 38, 44, 0.08);
    }}
    blockquote {{
      padding: 12px 16px;
      border-left: 4px solid rgba(13, 107, 120, 0.45);
      background: var(--quote-bg);
      color: #4b433a;
      border-radius: 0 12px 12px 0;
    }}
    img {{
      max-width: 100%;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 10px 12px;
      border: 1px solid var(--line);
      text-align: left;
    }}
    th {{
      background: #f7f2e9;
    }}
    .math {{
      overflow-x: auto;
    }}
    @media print {{
      body {{
        background: #fff;
      }}
      .sheet {{
        width: auto;
        margin: 0;
        padding: 0;
        border: none;
        border-radius: 0;
        box-shadow: none;
      }}
      .runtime-note {{
        display: none;
      }}
    }}
  </style>
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
      }},
      svg: {{ fontCache: 'global' }}
    }};
  </script>
{external_scripts}
  <script>
    const markReady = () => {{
      if (document.body) {{
        document.body.dataset.rendered = '1';
      }}
    }};

    window.addEventListener('load', () => {{
      setTimeout(async () => {{
        try {{
          if (window.mermaid) {{
            window.mermaid.initialize({{
              startOnLoad: false,
              securityLevel: 'loose',
              theme: 'default'
            }});
            await window.mermaid.run({{ querySelector: '.mermaid' }});
          }}

          if (window.MathJax && window.MathJax.typesetPromise) {{
            await window.MathJax.typesetPromise();
          }}
        }} catch (error) {{
          console.warn('Markdown enhancement render failed:', error);
        }} finally {{
          markReady();
        }}
      }}, 0);

      setTimeout(markReady, 4000);
    }});
  </script>
</head>
<body>
  <main class="sheet">
    <p class="runtime-note">
      {note} PDF保存時は現在の表示内容をそのまま出力します。
    </p>
    {body}
  </main>
</body>
</html>
"""

    def _read_text(self, path: Path) -> str:
        encodings = ("utf-8", "utf-8-sig", "cp932")
        last_error: Exception | None = None
        for encoding in encodings:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc
        if last_error:
            raise last_error
        return path.read_text()

    def _render_markdown_body(self, text: str) -> str:
        protected_text, math_tokens = self._protect_math(text)
        if markdown_lib is not None:
            html = markdown_lib.markdown(
                protected_text,
                extensions=[
                    "extra",
                    "fenced_code",
                    "tables",
                    "sane_lists",
                    "toc",
                ],
            )
            html = self._restore_math_tokens(html, math_tokens)
            return self._convert_mermaid_blocks(html)
        return self._render_markdown_fallback(protected_text, math_tokens)

    def _protect_math(self, text: str) -> tuple[str, dict[str, tuple[str, str]]]:
        tokens: dict[str, tuple[str, str]] = {}
        token_index = 0

        def make_token(kind: str, content: str) -> str:
            nonlocal token_index
            token = f"@@PDFEDITOR_MATH_{token_index}@@"
            token_index += 1
            tokens[token] = (kind, content)
            return token

        def replace_math(segment: str) -> str:
            segment = _DISPLAY_MATH_RE.sub(
                lambda m: make_token("display", f"$${m.group(1)}$$"),
                segment,
            )
            segment = _INLINE_MATH_RE.sub(
                lambda m: make_token("inline", f"${m.group(1)}$"),
                segment,
            )
            return segment

        parts = _FENCED_CODE_SPLIT_RE.split(text)
        for i, part in enumerate(parts):
            if i % 2 == 0:
                parts[i] = replace_math(part)
        return "".join(parts), tokens

    def _restore_math_tokens(self, html: str, tokens: dict[str, tuple[str, str]]) -> str:
        restored = html
        for token, (kind, content) in tokens.items():
            if kind == "display":
                restored = restored.replace(f"<p>{token}</p>", f'<div class="math">{content}</div>')
                restored = restored.replace(token, content)
            else:
                restored = restored.replace(token, content)
        return restored

    def _convert_mermaid_blocks(self, html: str) -> str:
        def repl(match: re.Match[str]) -> str:
            mermaid_source = match.group(1)
            mermaid_source = (
                mermaid_source
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
            )
            return f'<pre class="mermaid">{mermaid_source}</pre>'

        return _MERMAID_BLOCK_RE.sub(repl, html)

    def _render_markdown_fallback(
        self,
        text: str,
        math_tokens: dict[str, tuple[str, str]] | None = None,
    ) -> str:
        lines = text.splitlines()
        out: list[str] = []
        paragraph: list[str] = []
        list_type: str | None = None
        list_items: list[str] = []
        in_code = False
        code_lang = ""
        code_lines: list[str] = []

        def flush_paragraph():
            nonlocal paragraph
            if paragraph:
                joined = "<br>\n".join(self._render_inline(line.strip()) for line in paragraph)
                out.append(f"<p>{joined}</p>")
                paragraph = []

        def flush_list():
            nonlocal list_type, list_items
            if list_type and list_items:
                items = "".join(f"<li>{item}</li>" for item in list_items)
                out.append(f"<{list_type}>{items}</{list_type}>")
            list_type = None
            list_items = []

        def flush_code():
            nonlocal in_code, code_lang, code_lines
            code_html = escape("\n".join(code_lines))
            if code_lang == "mermaid":
                out.append(f'<pre class="mermaid">{code_html}</pre>')
            else:
                class_attr = f' class="language-{escape(code_lang)}"' if code_lang else ""
                out.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
            in_code = False
            code_lang = ""
            code_lines = []

        for raw_line in lines:
            line = raw_line.rstrip()
            fence = re.match(r"^```([\w-]*)\s*$", line)
            if fence:
                flush_paragraph()
                flush_list()
                if in_code:
                    flush_code()
                else:
                    in_code = True
                    code_lang = fence.group(1).lower()
                continue

            if in_code:
                code_lines.append(raw_line)
                continue

            if not line.strip():
                flush_paragraph()
                flush_list()
                continue

            heading = re.match(r"^(#{1,6})\s+(.*)$", line)
            if heading:
                flush_paragraph()
                flush_list()
                level = len(heading.group(1))
                out.append(f"<h{level}>{self._render_inline(heading.group(2).strip())}</h{level}>")
                continue

            quote = re.match(r"^>\s?(.*)$", line)
            if quote:
                flush_paragraph()
                flush_list()
                out.append(f"<blockquote><p>{self._render_inline(quote.group(1).strip())}</p></blockquote>")
                continue

            unordered = re.match(r"^\s*[-*+]\s+(.*)$", line)
            ordered = re.match(r"^\s*\d+\.\s+(.*)$", line)
            if unordered or ordered:
                flush_paragraph()
                current_type = "ul" if unordered else "ol"
                if list_type and list_type != current_type:
                    flush_list()
                list_type = current_type
                list_items.append(self._render_inline((unordered or ordered).group(1).strip()))
                continue

            paragraph.append(line)

        if in_code:
            flush_code()
        flush_paragraph()
        flush_list()
        html = "\n".join(out)
        return self._restore_math_tokens(html, math_tokens or {})

    def _render_inline(self, text: str) -> str:
        rendered = escape(text)
        rendered = _LINK_RE.sub(r'<a href="\2">\1</a>', rendered)
        rendered = _BOLD_RE.sub(r"<strong>\1</strong>", rendered)
        rendered = _ITALIC_RE.sub(r"<em>\1</em>", rendered)
        rendered = _INLINE_CODE_RE.sub(r"<code>\1</code>", rendered)
        return rendered
