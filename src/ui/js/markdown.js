// Markdown -> HTML converter used by the Markdown view (and, through
// PrintToPdf, by the Markdown -> PDF export). Pure functions with no DOM
// access, so tests/markdown_render_test.js can load this file in Node.
//
// Security contract: the returned HTML is built only from fixed tags and from
// text that went through escapeHtml, with link/image URLs restricted to an
// allow-list (sanitizeLinkUrl / sanitizeImageUrl). Raw HTML in the source
// never reaches the output.
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.QMMarkdown = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Compact Markdown -> HTML converter. Covers headings, paragraphs,
  // bold/italic, inline code, fenced code blocks (incl. ```mermaid blocks),
  // blockquotes (recursive), simple (non-nested) bullet/numbered lists,
  // links, images, GFM tables, inline/display math ($..$/$$..$$), and
  // horizontal rules -- deliberately not a full CommonMark implementation.
  // Escapes HTML in the source first (including quotes, and the LaTeX between
  // $ delimiters), so raw HTML embedded in a Markdown file renders as literal
  // text rather than executing -- a safe simplification, not a Python-parity
  // feature (the Python baseline's `Markdown` package allows raw HTML
  // passthrough). Link and image URLs are restricted to an allow-list.

  // Math protection: replaces $$..$$ (display) and $..$ (inline) segments
  // with opaque tokens before markdownToHtml runs, so bold/italic/code
  // regexes and HTML-escaping never touch the LaTeX source, then restores
  // the raw math text after conversion (mirrors markdown_manager.py's
  // _protect_math/_restore_math_tokens token-swap approach). Skips fenced
  // code blocks entirely, same as the Python version. MathJax's tex-svg.js
  // itself scans the final DOM text for the $/$$ delimiters at render time.
  let mathTokenCounter = 0;
  function protectMath(source) {
    if (!source || !source.includes('$')) {
      return { text: source || '', tokens: new Map() };
    }
    const tokens = new Map();
    const makeToken = (kind, content) => {
      const token = `@@QMPDFMATH${mathTokenCounter}@@`;
      mathTokenCounter += 1;
      tokens.set(token, { kind, content });
      return token;
    };
    const replaceMath = (segment) => segment
      .replace(/(?<!\\)\$\$([\s\S]+?)(?<!\\)\$\$/g, (m, inner) => makeToken('display', `$$${inner}$$`))
      .replace(/(?<!\\)\$(?!\$)([^$\n]+?)(?<!\\)\$/g, (m, inner) => makeToken('inline', `$${inner}$`));
    const parts = source.split(/(^```[\w-]*\s*$[\s\S]*?^```\s*$)/m);
    return { text: parts.map((part, idx) => (idx % 2 === 0 ? replaceMath(part) : part)).join(''), tokens };
  }
  function restoreMathTokens(html, tokens) {
    let restored = html;
    tokens.forEach((value, token) => {
      // The LaTeX source is escaped like any other text. MathJax reads the DOM
      // *text*, in which &lt; / &amp; are exactly the characters it expects,
      // while markup typed between the $ delimiters stays inert.
      const safeContent = escapeHtml(value.content);
      if (value.kind === 'display') {
        restored = restored.split(`<p>${token}</p>`).join(`<div class="math">${safeContent}</div>`);
      }
      restored = restored.split(token).join(safeContent);
    });
    return restored;
  }
  function renderMarkdownDocument(source) {
    // NUL delimits the stash markers in renderInline and has no meaning in a document.
    const { text, tokens } = protectMath((source || '').replace(/\u0000/g, ''));
    return restoreMathTokens(markdownToHtml(text), tokens);
  }

  // Escapes every character that can start markup or end an attribute value.
  // The quotes matter: escaped text is later placed inside href="..." / alt="..."
  // and must never be able to close the attribute and add one of its own.
  function escapeHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ── URL allow-lists ──
  // These work on text that already went through escapeHtml. The scheme check
  // runs on the decoded text with whitespace/control characters removed,
  // because browsers ignore those inside a URL ("java\tscript:" is javascript:).
  const LINK_SCHEMES = new Set(['http', 'https', 'mailto']);
  const IMAGE_SCHEMES = new Set(['http', 'https']);
  const DATA_IMAGE = /^data:image\/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=]*$/i;

  function decodeEntities(text) {
    return text
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&');
  }
  function urlForCheck(url) {
    // eslint-disable-next-line no-control-regex
    return decodeEntities(url).replace(/[\u0000-\u0020\u007f-\u009f\u00ad\u200b-\u200f\u2028-\u202f\u2060\ufeff]/g, '');
  }
  function urlScheme(checkedUrl) {
    const match = /^([a-z][a-z0-9+.-]*):/i.exec(checkedUrl);
    return match ? match[1].toLowerCase() : null;
  }
  // Returns the value to use in href, or null when the text must not become a
  // link: only http(s), mailto and in-page "#..." targets are allowed.
  function sanitizeLinkUrl(url) {
    const checked = urlForCheck(url);
    if (checked === '') return null;
    const scheme = urlScheme(checked);
    if (scheme === null) return checked.startsWith('#') ? url.trim() : null;
    return LINK_SCHEMES.has(scheme) ? url.trim() : null;
  }
  // Returns the value to use in src, or null when no image may be shown:
  // http(s) and base64 raster data URIs only (no relative paths -- the page has
  // no files next to it -- and no SVG, which can carry script).
  function sanitizeImageUrl(url) {
    const checked = urlForCheck(url);
    if (checked === '') return null;
    const scheme = urlScheme(checked);
    if (scheme === 'data') return DATA_IMAGE.test(checked) ? url.trim() : null;
    return scheme !== null && IMAGE_SCHEMES.has(scheme) ? url.trim() : null;
  }

  // Inline markup. Code spans, images and links are generated first and parked
  // in `stash` behind NUL-delimited markers, so the emphasis regexes below can
  // never reach into an attribute value, and the generated tags are put back
  // only at the very end.
  function renderInline(source) {
    // NUL delimits the stash markers, so it must not occur in the input.
    let out = escapeHtml(source.replace(/\u0000/g, ''));
    const stash = [];
    const plainText = new Map();  // marker -> escaped text, for spots that cannot hold markup (alt, url)
    const park = (html, plain) => {
      stash.push(html);
      const marker = `\u0000${stash.length - 1}\u0000`;
      if (plain !== undefined) plainText.set(marker, plain);
      return marker;
    };
    const toPlain = (text) => text.replace(/\u0000\d+\u0000/g, (marker) => plainText.get(marker) || '');

    out = out.replace(/`([^`]+)`/g, (match, code) => park(`<code>${code}</code>`, code));

    out = out.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, url) => {
      const altText = toPlain(alt);
      const src = sanitizeImageUrl(toPlain(url));
      if (src === null) return altText;
      return park(`<img alt="${altText}" src="${src}" referrerpolicy="no-referrer">`);
    });

    out = out.replace(/\[([^\]]*)\]\(([^)]+)\)/g, (match, label, url) => {
      const href = sanitizeLinkUrl(toPlain(url));
      if (href === null) return label;
      // In-page "#" targets stay in the page; everything else opens in the
      // system browser (NewWindowRequested on the native side).
      const target = href.startsWith('#') ? '' : ' target="_blank" rel="noopener noreferrer"';
      return park(`<a href="${href}"${target}>`) + label + park('</a>');
    });

    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    return out.replace(/\u0000(\d+)\u0000/g, (match, index) => stash[Number(index)]);
  }

  // GFM table row splitting: strips one optional leading/trailing pipe,
  // then splits on '|'. A cell containing an escaped pipe ('\|') is not
  // supported (matches this converter's general "compact, not full
  // CommonMark" scope).
  function splitTableRow(line) {
    let trimmed = line.trim();
    if (trimmed.startsWith('|')) trimmed = trimmed.slice(1);
    if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1);
    return trimmed.split('|').map((c) => c.trim());
  }
  function isTableSeparatorRow(line) {
    if (!/\|/.test(line) && !/^:?-+:?$/.test(line.trim())) return false;
    const cells = splitTableRow(line);
    return cells.length > 0 && cells.every((c) => /^:?-{1,}:?$/.test(c));
  }

  // The one raw-HTML construct this converter honours instead of escaping
  // (see the escapeHtml note above): a standalone page-break <div>. Both
  // spellings other Markdown->PDF tools use are accepted -- an inline style
  // naming a page break ('page-break-before/after: always', or the CSS3
  // 'break-before/after: page') and Markdown PDF's class="page" -- written
  // <div ...></div>, <div ... />, or <div ...> on a line of its own. Any
  // other raw HTML still renders as literal text.
  function isPageBreakLine(line) {
    const match = line.trim().match(/^<div\s+([^>]*?)\/?>(?:\s*<\/div>)?$/i);
    if (!match) return false;
    const attrs = match[1];
    const style = attrs.match(/style\s*=\s*["']([^"']*)["']/i);
    if (style && /(?:page-)?break-(?:before|after)\s*:\s*(?:always|page)/i.test(style[1])) return true;
    const cls = attrs.match(/class\s*=\s*["']([^"']*)["']/i);
    return !!cls && cls[1].trim().split(/\s+/).some((c) => c.toLowerCase() === 'page');
  }

  function markdownToHtml(source) {
    const lines = source.replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    let i = 0;
    let paragraphLines = [];
    let list = null;  // { type: 'ul'|'ol', items: [] }

    const flushParagraph = () => {
      if (paragraphLines.length) {
        html.push('<p>' + renderInline(paragraphLines.join(' ')) + '</p>');
        paragraphLines = [];
      }
    };
    const flushList = () => {
      if (list) {
        html.push(`<${list.type}>` + list.items.map((item) => `<li>${renderInline(item)}</li>`).join('') +
          `</${list.type}>`);
        list = null;
      }
    };

    while (i < lines.length) {
      const line = lines[i];

      if (/^```/.test(line)) {
        flushParagraph();
        flushList();
        const langMatch = line.match(/^```([\w-]*)/);
        const lang = langMatch ? langMatch[1].toLowerCase() : '';
        const codeLines = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) {
          codeLines.push(lines[i]);
          i += 1;
        }
        i += 1;
        if (lang === 'mermaid') {
          html.push('<pre class="mermaid">' + escapeHtml(codeLines.join('\n')) + '</pre>');
        } else {
          html.push('<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>');
        }
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushParagraph();
        flushList();
        const level = heading[1].length;
        html.push(`<h${level}>${renderInline(heading[2].trim())}</h${level}>`);
        i += 1;
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flushParagraph();
        flushList();
        html.push('<hr>');
        i += 1;
        continue;
      }

      if (isPageBreakLine(line)) {
        flushParagraph();
        flushList();
        html.push('<div class="page-break"></div>');
        i += 1;
        continue;
      }

      if (/\|/.test(line) && i + 1 < lines.length && isTableSeparatorRow(lines[i + 1])) {
        flushParagraph();
        flushList();
        const headerCells = splitTableRow(line);
        const aligns = splitTableRow(lines[i + 1]).map((c) => {
          const left = c.startsWith(':');
          const right = c.endsWith(':');
          if (left && right) return 'center';
          if (right) return 'right';
          if (left) return 'left';
          return '';
        });
        i += 2;
        const bodyRows = [];
        while (i < lines.length && lines[i].trim() !== '' && /\|/.test(lines[i])) {
          bodyRows.push(splitTableRow(lines[i]));
          i += 1;
        }
        const alignAttr = (idx) => (aligns[idx] ? ` style="text-align:${aligns[idx]}"` : '');
        const theadHtml = '<thead><tr>' +
          headerCells.map((c, idx) => `<th${alignAttr(idx)}>${renderInline(c)}</th>`).join('') +
          '</tr></thead>';
        const tbodyHtml = '<tbody>' + bodyRows.map((row) => '<tr>' +
          headerCells.map((_, idx) => `<td${alignAttr(idx)}>${renderInline(row[idx] || '')}</td>`).join('') +
          '</tr>').join('') + '</tbody>';
        html.push('<table>' + theadHtml + tbodyHtml + '</table>');
        continue;
      }

      if (/^>\s?/.test(line)) {
        flushParagraph();
        flushList();
        const quoted = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          quoted.push(lines[i].replace(/^>\s?/, ''));
          i += 1;
        }
        html.push('<blockquote>' + markdownToHtml(quoted.join('\n')) + '</blockquote>');
        continue;
      }

      const bullet = line.match(/^[-*+]\s+(.*)$/);
      if (bullet) {
        flushParagraph();
        if (!list || list.type !== 'ul') {
          flushList();
          list = { type: 'ul', items: [] };
        }
        list.items.push(bullet[1]);
        i += 1;
        continue;
      }

      const numbered = line.match(/^\d+\.\s+(.*)$/);
      if (numbered) {
        flushParagraph();
        if (!list || list.type !== 'ol') {
          flushList();
          list = { type: 'ol', items: [] };
        }
        list.items.push(numbered[1]);
        i += 1;
        continue;
      }

      if (line.trim() === '') {
        flushParagraph();
        flushList();
        i += 1;
        continue;
      }

      paragraphLines.push(line.trim());
      i += 1;
    }
    flushParagraph();
    flushList();
    return html.join('\n');
  }

  return { renderMarkdownDocument, markdownToHtml, renderInline, escapeHtml, sanitizeLinkUrl, sanitizeImageUrl };
});
