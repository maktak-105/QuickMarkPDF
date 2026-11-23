// Tests for src/ui/js/markdown.js (the Markdown -> HTML converter).
// Run with: node tests/markdown_render_test.js
//
// The converter handles untrusted file content, so most of this file checks
// that nothing the source says can turn into script: a known list of attack
// strings plus a randomized fuzz run, each checked by assertSafeHtml(), a strict
// validator for the converter's output grammar. The rest pins the HTML produced
// for ordinary Markdown.
'use strict';

const assert = require('assert');
const path = require('path');

const { renderMarkdownDocument, sanitizeLinkUrl, sanitizeImageUrl, escapeHtml } =
  require(path.join(__dirname, '..', 'src', 'ui', 'js', 'markdown.js'));

// ---------------------------------------------------------------------------
// Output validator
// ---------------------------------------------------------------------------
// The converter only ever emits the tags below, with quoted attribute values
// that cannot contain a quote or angle bracket. Anything else -- a stray '<' or
// '>', an unknown tag or attribute, an on* handler, a URL with another scheme --
// means markup from the source reached the output.
const ALLOWED_ATTRIBUTES = {
  a: ['href', 'target', 'rel'],
  img: ['alt', 'src', 'referrerpolicy'],
  div: ['class'],
  pre: ['class'],
  th: ['style'],
  td: ['style'],
};
const PLAIN_TAGS = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'code', 'blockquote', 'strong', 'em',
  'hr', 'table', 'thead', 'tbody', 'tr'];
const TAG_PATTERN = /<(\/?)([a-z][a-z0-9]*)((?:\s+[a-z-]+(?:="[^"<>]*")?)*)\s*\/?>/g;
const ATTRIBUTE_PATTERN = /\s+([a-z-]+)(?:="([^"]*)")?/g;

function decode(text) {
  return text.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

function assertSafeHtml(html, label) {
  const fail = (message) => assert.fail(`${message}\n  input: ${label}\n  output: ${html}`);

  const text = html.replace(TAG_PATTERN, '');
  if (/[<>]/.test(text)) fail('stray angle bracket outside a generated tag');
  if (/\u0000/.test(html)) fail('stash marker leaked into the output');

  for (const match of html.matchAll(TAG_PATTERN)) {
    const [, closing, name, attributes] = match;
    const allowedAttributes = ALLOWED_ATTRIBUTES[name];
    if (!allowedAttributes && !PLAIN_TAGS.includes(name)) fail(`tag <${name}> is not allowed`);
    if (closing && attributes.trim() !== '') fail('closing tag with attributes');
    for (const attribute of attributes.matchAll(ATTRIBUTE_PATTERN)) {
      const attributeName = attribute[1];
      const value = attribute[2] === undefined ? '' : attribute[2];
      if (!allowedAttributes || !allowedAttributes.includes(attributeName)) {
        fail(`attribute ${attributeName} is not allowed on <${name}>`);
      }
      const checked = decode(value).replace(/[\u0000-\u0020]/g, '');
      if (attributeName === 'href') {
        if (!/^(https?:|mailto:|#)/i.test(checked)) fail(`href with a disallowed target: ${value}`);
      } else if (attributeName === 'src') {
        if (!/^(https?:|data:image\/(png|jpe?g|gif|webp);base64,)/i.test(checked)) fail(`src with a disallowed target: ${value}`);
      } else if (attributeName === 'style') {
        if (!/^text-align:(left|right|center)$/.test(value)) fail(`unexpected style: ${value}`);
      } else if (attributeName === 'class') {
        if (!['math', 'mermaid', 'page-break'].includes(value)) fail(`unexpected class: ${value}`);
      } else if (attributeName === 'target') {
        if (value !== '_blank') fail(`unexpected target: ${value}`);
      } else if (attributeName === 'rel') {
        if (value !== 'noopener noreferrer') fail(`unexpected rel: ${value}`);
      } else if (attributeName === 'referrerpolicy') {
        if (value !== 'no-referrer') fail(`unexpected referrerpolicy: ${value}`);
      }
    }
  }
}

function render(source) {
  return renderMarkdownDocument(source);
}

let checks = 0;
function section(name, fn) {
  fn();
  checks += 1;
  console.log(`ok - ${name}`);
}

// ---------------------------------------------------------------------------
// Attack strings
// ---------------------------------------------------------------------------
const ATTACKS = [
  // The three routes found in the 2026-11-23 audit (math passthrough, attribute injection, javascript: href)
  '$<img src=x onerror="alert(1)">$',
  '$$<script>alert(1)</script>$$',
  'text $<img src=x onerror=alert(1)>$ more',
  '![x" onerror="alert(1)](a.png)',
  '![x\' onerror=\'alert(1)](a.png)',
  '[click](y" onmouseover="alert(1)")',
  '[click](y\' onfocus=\'alert(1)\' autofocus tabindex=1)',
  '[js](javascript:alert(1))',
  '[js](JaVaScRiPt:alert(1))',
  '[js](java\tscript:alert(1))',
  '[js](java\nscript:alert(1))',
  '[js](  javascript:alert(1))',
  '[js](\u0001javascript:alert(1))',
  '[js](&#106;avascript:alert(1))',
  '[js](&#x6A;avascript:alert(1))',
  '[js](javascript&colon;alert(1))',
  '[vb](vbscript:msgbox(1))',
  '[data](data:text/html,<script>alert(1)</script>)',
  '[data](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)',
  '[file](file:///C:/Windows/win.ini)',
  '[unc](\\\\evil\\share\\x)',
  '[proto](//evil.example/x)',
  '[rel](relative/path.md)',
  '[empty]()',
  '![img](javascript:alert(1))',
  '![img](data:text/html;base64,PHNjcmlwdD4=)',
  '![img](data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+)',
  '![img](file:///C:/secret.png)',
  '![img](//evil.example/x.png)',
  // Nesting and stash-marker games
  '[[x](javascript:alert(1))](https://a.example)',
  '[![a](javascript:alert(1))](https://a.example)',
  '[x](https://a.example/`code`)',
  '![`code`](https://a.example/i.png)',
  '\u00000\u0000 \u00001\u0000',
  '`a` \u00000\u0000 [x](\u00000\u0000)',
  '**[x](javascript:alert(1))**',
  '*![x](y" onerror="alert(1))*',
  // Raw HTML in every block type
  '<img src=x onerror=alert(1)>',
  '<script>alert(1)</script>',
  '<iframe src="https://evil.example"></iframe>',
  '<div style="page-break-after: always" onclick="alert(1)"></div>',
  '<div class="page" onclick="alert(1)">',
  '# <img src=x onerror=alert(1)>',
  '> <img src=x onerror=alert(1)>',
  '- <img src=x onerror=alert(1)>',
  '1. <svg onload=alert(1)>',
  '| a | b |\n|---|---|\n| <img src=x onerror=alert(1)> | [x](javascript:alert(1)) |',
  '| <b onmouseover=alert(1)>h | x |\n|:--|--:|\n| 1 | 2 |',
  '```\n</code></pre><img src=x onerror=alert(1)>\n```',
  '```mermaid\nA["<img src=x onerror=alert(1)>"] --> B\nclick B href "javascript:alert(1)"\n```',
  '```"><img src=x onerror=alert(1)>\ncode\n```',
  // Quotes and entities in plain text
  '" onmouseover="alert(1)',
  '&lt;script&gt;alert(1)&lt;/script&gt;',
  '&quot; onerror=&quot;alert(1)',
];

section('attack strings never produce script-capable markup', () => {
  for (const attack of ATTACKS) assertSafeHtml(render(attack), JSON.stringify(attack));
});

section('math between $ delimiters is escaped, not passed through', () => {
  assert.strictEqual(render('$<img src=x onerror=alert(1)>$'), '<p>$&lt;img src=x onerror=alert(1)&gt;$</p>');
  assert.ok(render('$$<b>x</b>$$').includes('<div class="math">$$&lt;b&gt;x&lt;/b&gt;$$</div>'));
});

section('javascript: and other schemes are not links', () => {
  // The URL ends at the first ")", so a trailing ")" of "alert(1)" stays behind as text.
  for (const source of ['[js](javascript:alert(1))', '[js](JaVaScRiPt:alert(1))', '[js](java\tscript:alert(1))']) {
    const out = render(source);
    assert.ok(!/<a\b/.test(out), out);
    assert.ok(out.startsWith('<p>js'), out);
  }
  assert.strictEqual(render('[js](javascript:alert)'), '<p>js</p>');
  assert.strictEqual(render('[f](file:///C:/Windows/win.ini)'), '<p>f</p>');
  assert.strictEqual(sanitizeLinkUrl('javascript:alert(1)'), null);
  assert.strictEqual(sanitizeLinkUrl('//evil.example'), null);
  assert.strictEqual(sanitizeImageUrl('data:image/svg+xml;base64,AAAA'), null);
  assert.strictEqual(sanitizeImageUrl('relative.png'), null);
});

section('quotes cannot close an attribute', () => {
  const out = render('![x" onerror="alert(1)](https://a.example/i.png)');
  const imgTag = out.match(/<img\b[^>]*>/)[0];
  // The attacker's text stays inside alt="...": the tag carries exactly its own three attributes.
  assert.deepStrictEqual([...imgTag.matchAll(ATTRIBUTE_PATTERN)].map((m) => m[1]), ['alt', 'src', 'referrerpolicy']);
  assert.ok(out.includes('alt="x&quot; onerror=&quot;alert(1)"'), out);
  assert.strictEqual(escapeHtml('"\'<>&'), '&quot;&#39;&lt;&gt;&amp;');
});

// ---------------------------------------------------------------------------
// Fuzz: random mixtures of the characters the converter treats specially
// ---------------------------------------------------------------------------
section('random input always yields safe output', () => {
  let seed = 0x5eed1234;
  const random = () => {  // mulberry32
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const pieces = ['[', ']', '(', ')', '!', '"', "'", '<', '>', '$', '$$', '`', '```', '```mermaid\n', '*', '**', '_', '__',
    '\n', '\n\n', '|', '---', '|---|', '#', '# ', '> ', '- ', '1. ', ' ', '\t', '\u0000', '\u00000\u0000', '&', '&amp;',
    '&quot;', 'javascript:', 'JaVaScRiPt:', 'data:text/html,', 'data:image/png;base64,', 'https://a.example/', 'http://',
    'mailto:', '#top', 'onerror=', 'onclick=', '<img src=x onerror=alert(1)>', '<script>', '</script>',
    '<div style="page-break-after: always">', 'alert(1)', 'a', 'b', 'x', '\\', '@@QMPDFMATH0@@', '=', ':'];
  for (let i = 0; i < 30000; i += 1) {
    const length = 1 + Math.floor(random() * 24);
    let source = '';
    for (let j = 0; j < length; j += 1) source += pieces[Math.floor(random() * pieces.length)];
    assertSafeHtml(render(source), JSON.stringify(source));
  }
});

// ---------------------------------------------------------------------------
// Ordinary Markdown still renders
// ---------------------------------------------------------------------------
section('headings, paragraphs and emphasis', () => {
  assert.strictEqual(render('# Title'), '<h1>Title</h1>');
  assert.strictEqual(render('###### Six'), '<h6>Six</h6>');
  assert.strictEqual(render('**b** *i* `c`'), '<p><strong>b</strong> <em>i</em> <code>c</code></p>');
  assert.strictEqual(render('line one\nline two'), '<p>line one line two</p>');
  assert.strictEqual(render('a __b__ c'), '<p>a <strong>b</strong> c</p>');
});

section('links and images', () => {
  assert.strictEqual(
    render('[ok](https://example.com/a?b=1&c=2)'),
    '<p><a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">ok</a></p>');
  assert.strictEqual(
    render('![alt text](https://example.com/i.png)'),
    '<p><img alt="alt text" src="https://example.com/i.png" referrerpolicy="no-referrer"></p>');
  assert.strictEqual(
    render('[mail](mailto:someone@example.com)'),
    '<p><a href="mailto:someone@example.com" target="_blank" rel="noopener noreferrer">mail</a></p>');
  assert.strictEqual(render('[top](#top)'), '<p><a href="#top">top</a></p>');
  assert.strictEqual(
    render('[**bold link**](https://example.com)'),
    '<p><a href="https://example.com" target="_blank" rel="noopener noreferrer"><strong>bold link</strong></a></p>');
  assert.strictEqual(
    render('[![badge](https://img.example/b.svg)](https://example.com)'),
    '<p><a href="https://example.com" target="_blank" rel="noopener noreferrer">' +
    '<img alt="badge" src="https://img.example/b.svg" referrerpolicy="no-referrer"></a></p>');
  assert.ok(render('![p](data:image/png;base64,iVBORw0KGgo=)').includes('src="data:image/png;base64,iVBORw0KGgo="'));
  // URLs with markup characters are kept intact, not mangled by emphasis rules
  assert.ok(render('[u](https://example.com/a_b_c/*d*)').includes('href="https://example.com/a_b_c/*d*"'));
});

section('code is literal', () => {
  assert.strictEqual(render('`a*b*c`'), '<p><code>a*b*c</code></p>');
  assert.strictEqual(render('```\nsay "hi" <b>\n```'), '<pre><code>say &quot;hi&quot; &lt;b&gt;</code></pre>');
  assert.strictEqual(render('```mermaid\nA --> B\n```'), '<pre class="mermaid">A --&gt; B</pre>');
});

section('lists, quotes, rules, tables, page breaks', () => {
  assert.strictEqual(render('- a\n- b'), '<ul><li>a</li><li>b</li></ul>');
  assert.strictEqual(render('1. a\n2. b'), '<ol><li>a</li><li>b</li></ol>');
  assert.strictEqual(render('> quoted'), '<blockquote><p>quoted</p></blockquote>');
  assert.strictEqual(render('---'), '<hr>');
  assert.strictEqual(render('<div style="page-break-after: always"></div>'), '<div class="page-break"></div>');
  assert.strictEqual(render('<div class="page"></div>'), '<div class="page-break"></div>');
  assert.strictEqual(
    render('| a | b |\n|:--|--:|\n| 1 | 2 |'),
    '<table><thead><tr><th style="text-align:left">a</th><th style="text-align:right">b</th></tr></thead>' +
    '<tbody><tr><td style="text-align:left">1</td><td style="text-align:right">2</td></tr></tbody></table>');
});

section('math is kept for MathJax', () => {
  assert.strictEqual(render('$a<b$'), '<p>$a&lt;b$</p>');
  assert.strictEqual(render('inline $x^2$ here'), '<p>inline $x^2$ here</p>');
  assert.ok(render('$$\nE=mc^2\n$$').includes('<div class="math">$$\nE=mc^2\n$$</div>'));
  assert.strictEqual(render('price \\$5 and \\$6'), '<p>price \\$5 and \\$6</p>');
});

section('Japanese text and empty input', () => {
  assert.strictEqual(render('# 見出し\n\n本文です。'), '<h1>見出し</h1>\n<p>本文です。</p>');
  assert.strictEqual(render(''), '');
});

console.log(`\nAll ${checks} markdown_render_test checks passed.`);
