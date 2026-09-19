import tempfile
import unittest
from pathlib import Path

from src.pdf_editor.markdown.markdown_manager import MarkdownManager


class TestMarkdownManager(unittest.TestCase):
    def setUp(self):
        self.manager = MarkdownManager()

    def test_load_markdown_reads_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.md"
            path.write_text("# Title\n\nhello", encoding="utf-8")

            document = self.manager.load_markdown(path)

            self.assertEqual(document.title, "sample")
            self.assertIn("hello", document.text)

    def test_render_html_promotes_mermaid_blocks(self):
        markdown_text = """# Flow

```mermaid
graph TD
  A[Start] --> B[Done]
```
"""
        document = type("Doc", (), {"title": "flow", "text": markdown_text})()

        html = self.manager.render_html_document(document)

        self.assertIn('<pre class="mermaid">', html)
        self.assertIn("graph TD", html)

    def test_render_html_keeps_math_expressions(self):
        markdown_text = "# Math\n\nInline $a^2+b^2=c^2$ and block:\n\n$$E=mc^2$$"
        document = type("Doc", (), {"title": "math", "text": markdown_text})()

        html = self.manager.render_html_document(document)

        self.assertIn("$a^2+b^2=c^2$", html)
        self.assertIn("$$E=mc^2$$", html)

    def test_render_html_preserves_matrix_block_math(self):
        markdown_text = r"""# Matrix

$$
A =
\begin{bmatrix}
1 & 2 & 3 \\
0 & 1 & 4 \\
5 & 6 & 0
\end{bmatrix}
$$
"""
        document = type("Doc", (), {"title": "matrix", "text": markdown_text})()

        html = self.manager.render_html_document(document)

        self.assertIn(r"\begin{bmatrix}", html)
        self.assertIn(r"\end{bmatrix}", html)
        self.assertIn(r"1 & 2 & 3 \\", html)
        self.assertIn('<div class="math">$$', html)

    def test_render_html_uses_local_asset_urls(self):
        markdown_text = "# Offline\n\n```mermaid\ngraph TD\nA-->B\n```"
        document = type("Doc", (), {"title": "offline", "text": markdown_text})()

        html = self.manager.render_html_document(
            document,
            asset_urls={
                "mermaid_js_url": "file:///tmp/mermaid.min.js",
                "mathjax_js_url": "file:///tmp/tex-svg.js",
            },
        )

        self.assertIn('src="file:///tmp/mermaid.min.js"', html)
        self.assertIn('src="file:///tmp/tex-svg.js"', html)
        self.assertNotIn("cdn.jsdelivr.net", html)


if __name__ == "__main__":
    unittest.main()
