// Tests for the raw-HTML handling of src/ui/js/markdown.js.
// Run with: node tests/markdown_html_test.js
//
// Rules under test (plans/2026-11-23_Markdown内HTML許可_v1.1.md):
//  - allow-listed HTML is rendered (elements, attributes and URLs are re-generated, never passed on);
//  - everything else is dropped: dangerous elements with their content, other unknown elements as
//    tags only (their text stays), attributes one by one; comments disappear;
//  - "1 < 2" and similar, code, and math stay literal text.
'use strict';

const assert = require('assert');
const path = require('path');

const { renderMarkdownDocument } = require(path.join(__dirname, '..', 'src', 'ui', 'js', 'markdown.js'));
const { assertSafeHtml } = require(path.join(__dirname, 'support', 'safe_html.js'));

const render = (source) => renderMarkdownDocument(source);
const flat = (source) => render(source).replace(/\n/g, '');

let checks = 0;
function section(name, fn) {
  fn();
  checks += 1;
  console.log(`ok - ${name}`);
}

// Exact nesting check (for inputs without Markdown emphasis markers): every closing tag closes the
// innermost open element.
const TAG = /<(\/?)([a-z][a-z0-9]*)(?:\s+[a-z-]+(?:="[^"<>]*")?)*\s*\/?>/g;
const VOID = new Set(['br', 'wbr', 'hr', 'img']);
function assertNested(html, label) {
  const stack = [];
  for (const match of html.matchAll(TAG)) {
    const [, closing, name] = match;
    if (VOID.has(name)) continue;
    if (!closing) {
      stack.push(name);
    } else {
      assert.strictEqual(stack.pop(), name, `bad nesting at </${name}> for ${label}: ${html}`);
    }
  }
  assert.deepStrictEqual(stack, [], `unclosed elements for ${label}: ${html}`);
}

// ---------------------------------------------------------------------------
section('text-level tags are rendered', () => {
  assert.strictEqual(render('before <b>bold</b> after'), '<p>before <b>bold</b> after</p>');
  assert.strictEqual(render('line one<br>line two'), '<p>line one<br>line two</p>');
  assert.strictEqual(render('line one<br/>line two'), '<p>line one<br>line two</p>');
  assert.strictEqual(render('<B>x</B> <I>y</I>'), '<p><b>x</b> <i>y</i></p>');
  assert.strictEqual(render('H<sub>2</sub>O and E=mc<sup>2</sup>'), '<p>H<sub>2</sub>O and E=mc<sup>2</sup></p>');
  assert.strictEqual(render('<kbd>Ctrl</kbd>+<kbd>C</kbd>'), '<p><kbd>Ctrl</kbd>+<kbd>C</kbd></p>');
  assert.strictEqual(render('<mark>m</mark> <ins>i</ins> <del>d</del> <s>s</s> <u>u</u>'),
    '<p><mark>m</mark> <ins>i</ins> <del>d</del> <s>s</s> <u>u</u></p>');
  assert.strictEqual(render('<ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby>'),
    '<p><ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby></p>');
  assert.strictEqual(render('<abbr title="HyperText Markup Language">HTML</abbr>'),
    '<p><abbr title="HyperText Markup Language">HTML</abbr></p>');
  assert.strictEqual(render('a<wbr>b'), '<p>a<wbr>b</p>');
});

section('links and images in HTML form', () => {
  assert.strictEqual(render('<a href="https://example.com/?a=1&amp;b=2" title="T">l</a>'),
    '<p><a href="https://example.com/?a=1&amp;b=2" title="T" target="_blank" rel="noopener noreferrer">l</a></p>');
  assert.strictEqual(render('<a href=#top>t</a>'), '<p><a href="#top">t</a></p>');
  assert.strictEqual(render('<a href="mailto:a@example.com">m</a>'),
    '<p><a href="mailto:a@example.com" target="_blank" rel="noopener noreferrer">m</a></p>');
  // target and rel are always generated here, never taken from the source
  assert.strictEqual(render('<a href="https://example.com" target="_self" rel="opener">x</a>'),
    '<p><a href="https://example.com" target="_blank" rel="noopener noreferrer">x</a></p>');
  assert.strictEqual(render('<img src="https://example.com/a.png" width="100" height=50 alt="A" title="T">'),
    '<p><img alt="A" src="https://example.com/a.png" width="100" height="50" title="T" referrerpolicy="no-referrer"></p>');
  assert.strictEqual(render('<IMG SRC=\'https://example.com/a.png\' ONERROR="alert(1)">'),
    '<p><img alt="" src="https://example.com/a.png" referrerpolicy="no-referrer"></p>');
  assert.strictEqual(render('<img src="https://example.com/a.png" width="50%" align="right">'),
    '<p><img alt="" src="https://example.com/a.png" width="50%" class="align-right" referrerpolicy="no-referrer"></p>');
  assert.ok(render('<img src="data:image/png;base64,iVBORw0KGgo=">').includes('src="data:image/png;base64,iVBORw0KGgo="'));
  // sizes must be plain numbers
  assert.ok(!render('<img src="https://example.com/a.png" width="100px;position:fixed">').includes('width'));
  assert.ok(!render('<img src="https://example.com/a.png" width="5000%">').includes('width'));
});

section('script-capable targets are dropped', () => {
  assert.strictEqual(render('<a href="javascript:alert(1)">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="  JaVaScRiPt:alert(1)">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="&#106;avascript:alert(1)">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="&#x6A;avascript&colon;alert(1)">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="java&#9;script:alert(1)">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="data:text/html,<script>alert(1)</script>">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="vbscript:x">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="file:///C:/Windows/win.ini">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a href="//evil.example/x">x</a>'), '<p>x</p>');
  assert.strictEqual(render('<a>no href</a>'), '<p>no href</p>');
  assert.strictEqual(render('<img src="javascript:alert(1)">'), '');
  assert.strictEqual(render('<img src="relative.png">'), '');
  assert.strictEqual(render('<img src="data:image/svg+xml;base64,PHN2Zz4=">'), '');
  assert.strictEqual(render('<img src="data:text/html;base64,PHNjcmlwdD4=">'), '');
});

// ---------------------------------------------------------------------------
section('tags are balanced and properly nested', () => {
  const cases = {
    'unclosed': ['<b>bold', '<p><b>bold</b></p>'],
    'stray closer': ['text</b> more', '<p>text more</p>'],
    'mis-nested': ['<b><i>x</b></i>', '<p><b><i>x</i></b></p>'],
    'nested': ['<b>a <i>b</i> c</b>', '<p><b>a <i>b</i> c</b></p>'],
    'unclosed link': ['<a href="https://example.com">link', '<p><a href="https://example.com" target="_blank" rel="noopener noreferrer">link</a></p>'],
    'dropped link keeps text': ['<a href="javascript:x">a <b>b</b></a>', '<p>a <b>b</b></p>'],
  };
  for (const [name, [source, expected]] of Object.entries(cases)) {
    assert.strictEqual(render(source), expected, name);
  }
  // an unclosed formatting tag must not leak into the next paragraph
  const leak = render('<b>one\n\ntwo');
  assert.strictEqual(leak, '<p><b>one</b></p>\n<p>two</p>');
  assertNested(leak, 'leak');
  // nesting depth and amount are bounded
  const deep = render('<span>'.repeat(200) + 'x');
  assert.ok((deep.match(/<span>/g) || []).length <= 20, 'inline depth is capped');
  assertNested(deep, 'deep inline');
  assertSafeHtml(deep, 'deep inline');
  const manyTags = render('<b>x</b>'.repeat(5000));
  assert.ok((manyTags.match(/<b>/g) || []).length <= 2000, 'tags per run of text are capped');
  assertSafeHtml(manyTags, 'many tags');
});

// ---------------------------------------------------------------------------
section('block-level HTML around Markdown', () => {
  assert.strictEqual(flat('<div align="center">\n\n# Title\n\n</div>'),
    '<div class="align-center"><h1>Title</h1></div>');
  assert.strictEqual(flat('<p align="center">\n  <img src="https://example.com/logo.png" width="200">\n</p>'),
    '<div class="align-center"><p><img alt="" src="https://example.com/logo.png" width="200" referrerpolicy="no-referrer"></p></div>');
  assert.strictEqual(flat('<center>Text</center>'), '<div class="align-center"><p>Text</p></div>');
  assert.strictEqual(flat('<h2 align="right">T</h2>'), '<h2 class="align-right">T</h2>');
  assert.strictEqual(flat('<details>\n<summary>More</summary>\n\nhidden **text**\n\n</details>'),
    '<details><summary>More</summary><p>hidden <strong>text</strong></p></details>');
  assert.strictEqual(flat('<details open><summary>Open</summary>x</details>'),
    '<details open><summary>Open</summary><p>x</p></details>');
  assert.strictEqual(flat('<ul><li>a</li><li>b</li></ul>'), '<ul><li>a</li><li>b</li></ul>');
  assert.strictEqual(flat('<ol start="3"><li>c</li></ol>'), '<ol start="3"><li>c</li></ol>');
  assert.strictEqual(flat('<dl><dt>Term</dt><dd>Meaning</dd></dl>'), '<dl><dt>Term</dt><dd>Meaning</dd></dl>');
  assert.strictEqual(flat('<figure><img src="https://example.com/a.png"><figcaption>Cap</figcaption></figure>'),
    '<figure><p><img alt="" src="https://example.com/a.png" referrerpolicy="no-referrer"></p><figcaption>Cap</figcaption></figure>');
  assert.strictEqual(flat('<blockquote>quoted</blockquote>'), '<blockquote><p>quoted</p></blockquote>');
  assert.strictEqual(flat('a\n<hr>\nb'), '<p>a</p><hr><p>b</p>');
  assert.strictEqual(flat('<table>\n<tr><th>A</th><th>B</th></tr>\n<tr><td>1</td><td colspan="2" align="center">2</td></tr>\n</table>'),
    '<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td colspan="2" class="align-center">2</td></tr></table>');
  assert.strictEqual(flat('<table align="center"><caption>C</caption><thead><tr><th>h</th></tr></thead><tbody><tr><td>d</td></tr></tbody></table>'),
    '<table class="align-center"><caption>C</caption><thead><tr><th>h</th></tr></thead><tbody><tr><td>d</td></tr></tbody></table>');
  // Markdown keeps working between the tags
  assert.strictEqual(flat('<div>\n\n- a\n- b\n\n</div>'), '<div><ul><li>a</li><li>b</li></ul></div>');
  // preformatted text keeps its lines; text-level tags work in it, Markdown does not
  assert.strictEqual(render('<pre>\nline <b>1</b>\n  line 2 **x**\n</pre>'), '<pre>line <b>1</b>\n  line 2 **x**</pre>');
  // unclosed block elements are closed at the end; stray closers are ignored
  assert.strictEqual(flat('<div><details>text'), '<div><details><p>text</p></details></div>');
  assert.strictEqual(flat('text</div>more'), '<p>text</p><p>more</p>');
  for (const source of ['<div>\n<p>\nx\n</div>', '<table><tr><td>a<td>b</table>', '<ul><li>a<li>b</ul>', '<div><div><div>']) {
    assertSafeHtml(render(source), source);
  }
  // nesting depth of block elements is bounded
  const deep = render('<div>'.repeat(100) + 'x');
  assert.ok((deep.match(/<div>/g) || []).length <= 20, 'block depth is capped');
  assertNested(deep, 'deep block');
});

section('Markdown constructs keep working next to HTML', () => {
  assert.strictEqual(render('| a<br>b | <b>x</b> |\n|---|---|\n| 1 | 2 |'),
    '<table><thead><tr><th>a<br>b</th><th><b>x</b></th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>');
  assert.strictEqual(render('- item <b>bold</b>\n- second<br>line'), '<ul><li>item <b>bold</b></li><li>second<br>line</li></ul>');
  assert.strictEqual(render('# Title <i>x</i>'), '<h1>Title <i>x</i></h1>');
  assert.strictEqual(render('> quoted <b>b</b>'), '<blockquote><p>quoted <b>b</b></p></blockquote>');
  assert.strictEqual(render('[<b>bold link</b>](https://example.com)'),
    '<p><a href="https://example.com" target="_blank" rel="noopener noreferrer"><b>bold link</b></a></p>');
  assert.strictEqual(render('<div style="page-break-after: always"></div>'), '<div class="page-break"></div>');
  assert.strictEqual(render('<div class="page"></div>'), '<div class="page-break"></div>');
});

// ---------------------------------------------------------------------------
section('what is not on the allow-list is dropped', () => {
  // dangerous elements go together with their content
  assert.strictEqual(render('<script>alert(1)</script>'), '');
  assert.strictEqual(render('a <script>alert(1)</script> b'), '<p>a  b</p>');
  assert.strictEqual(render('<style>body{display:none}</style>'), '');
  assert.strictEqual(render('<iframe src="https://example.com"></iframe>'), '');
  assert.strictEqual(render('<object data="x"><embed src="y"></object>'), '');
  assert.strictEqual(render('<svg onload=alert(1)><circle/></svg>'), '');
  assert.strictEqual(render('<math><mi>x</mi></math>'), '');
  assert.strictEqual(render('<textarea>hidden</textarea>'), '');
  assert.strictEqual(render('<script>\nalert(1)\n</script>'), '');
  // (the removed lines leave a gap, which separates the paragraphs)
  assert.strictEqual(render('before\n<script type="text/javascript">\n  var a = 1;\n</script>\nafter'), '<p>before</p>\n<p>after</p>');
  // an unclosed one only loses its own tag (it must not swallow the rest of the document)
  assert.strictEqual(render('a <script>alert(1) b'), '<p>a alert(1) b</p>');
  assert.strictEqual(render('<script>one\n\nsecond paragraph stays'), '<p>one</p>\n<p>second paragraph stays</p>');
  // other unknown elements lose the tag only
  assert.strictEqual(render('<font color="red">red</font>'), '<p>red</p>');
  assert.strictEqual(render('<marquee>m</marquee>'), '<p>m</p>');
  assert.strictEqual(render('<form action="x"><input name="a"><button>go</button></form>'), '<p>go</p>');
  assert.strictEqual(render('<custom-tag>text</custom-tag>'), '<p>text</p>');
  assert.strictEqual(render('x<y and z>w'), '<p>xw</p>');
  // attributes are dropped one by one; the element stays
  assert.strictEqual(flat('<div class="x" onclick="alert(1)" style="color:red" id="a" name="b">t</div>'),
    '<div><p>t</p></div>');
  assert.strictEqual(render('<span class="x" onclick="alert(1)" style="position:fixed">t</span>'), '<p><span>t</span></p>');
  assert.strictEqual(render('<b onmouseover=alert(1)>t</b>'), '<p><b>t</b></p>');
  assert.strictEqual(render('<img src="https://example.com/a.png" onerror="alert(1)" onload="x" srcset="y" loading="lazy">'),
    '<p><img alt="" src="https://example.com/a.png" referrerpolicy="no-referrer"></p>');
  // comments and similar disappear
  assert.strictEqual(render('visible <!-- hidden --> visible'), '<p>visible  visible</p>');
  assert.strictEqual(render('a\n<!--\nhidden\n\nstill hidden\n-->\nb'), '<p>a</p>\n<p>b</p>');
  assert.strictEqual(render('<!DOCTYPE html>x'), '<p>x</p>');
  assert.strictEqual(render('<?php echo 1 ?>x'), '<p>x</p>');
  assert.strictEqual(render('<![CDATA[hidden]]>x'), '<p>x</p>');
  assert.strictEqual(render('a <!-- never closed b'), '<p>a  never closed b</p>');
  // tag-shaped text that is not valid syntax is dropped too
  assert.strictEqual(render('<img/src=x/onerror=alert(1)>'), '');
  assert.strictEqual(render('a <b c="unterminated> b'), '<p>a  b</p>');
});

section('literal text stays literal', () => {
  assert.strictEqual(render('1 < 2 and a <= b and 3<4'), '<p>1 &lt; 2 and a &lt;= b and 3&lt;4</p>');
  assert.strictEqual(render('a -> b <- c'), '<p>a -&gt; b &lt;- c</p>');
  assert.strictEqual(render('`<b>x</b>`'), '<p><code>&lt;b&gt;x&lt;/b&gt;</code></p>');
  assert.strictEqual(render('```html\n<b>x</b>\n<script>y</script>\n```'),
    '<pre><code>&lt;b&gt;x&lt;/b&gt;\n&lt;script&gt;y&lt;/script&gt;</code></pre>');
  assert.strictEqual(render('$<b>x</b>$'), '<p>$&lt;b&gt;x&lt;/b&gt;$</p>');
  assert.strictEqual(render('Entity &amp; stays text'), '<p>Entity &amp;amp; stays text</p>');
  // a comment inside code is not a comment
  assert.strictEqual(render('`<!-- x -->`'), '<p><code>&lt;!-- x --&gt;</code></p>');
});

// ---------------------------------------------------------------------------
section('known attack payloads end up inert', () => {
  const attacks = [
    '<img src=x onerror=alert(1)>', '<IMG SRC=x ONERROR=alert(1)>', '<img/src=x/onerror=alert(1)>',
    '<img src="x" onerror="alert(1)" >', '<svg/onload=alert(1)>', '<svg><script>alert(1)</script></svg>',
    '<math><mtext><table><mglyph><style><!--</style><img title="--&gt;&lt;img src=x onerror=alert(1)&gt;">',
    '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
    '<a href="javascript:alert(1)">x</a>', '<a href=javascript:alert(1)>x</a>', '<a href="JaVaScRiPt:alert(1)">x</a>',
    '<a href="&#0000106avascript:alert(1)">x</a>', '<a href="&#x6a;avascript:alert(1)">x</a>',
    '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">x</a>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>', '<iframe src="javascript:alert(1)"></iframe>',
    '<object data="javascript:alert(1)"></object>', '<embed src="javascript:alert(1)">',
    '<form action="javascript:alert(1)"><input type=submit></form>', '<button formaction="javascript:alert(1)">x</button>',
    '<input autofocus onfocus=alert(1)>', '<details open ontoggle=alert(1)>x</details>',
    '<div style="background:url(javascript:alert(1))">x</div>', '<div style="position:fixed;inset:0;z-index:99">cover</div>',
    '<div class="modal-overlay">fake dialog</div>', '<div id="MathJax">clobber</div>', '<img name="mermaid" src="https://example.com/a.png">',
    '<a href="https://example.com" onclick="alert(1)">x</a>', '<a href="https://example.com"onclick="alert(1)">x</a>',
    '<a href=https://example.com/"onmouseover="alert(1)>x</a>', '<b title="x" onmouseover="alert(1)">y</b>',
    '<b\nonmouseover=alert(1)>y</b>', '<b\tonmouseover=alert(1)>y</b>', '<b/onmouseover=alert(1)>y</b>',
    '<meta http-equiv="refresh" content="0;url=javascript:alert(1)">', '<link rel=stylesheet href="https://evil.example/x.css">',
    '<base href="https://evil.example/">', '<video src=x onerror=alert(1)></video>', '<audio src=x onerror=alert(1)></audio>',
    '<table background="javascript:alert(1)"><tr><td>x</td></tr></table>', '<td style="x" colspan="1" onclick="alert(1)">x</td>',
    '<ol start="1 onclick=alert(1)"><li>x</li></ol>', '<ol start="javascript:alert(1)"><li>x</li></ol>',
    '<img src="https://example.com/a.png" width="100" onload=alert(1)>', '<img src="https://example.com/a.png" alt="&quot; onerror=&quot;alert(1)">',
    '<a href="https://example.com" title="&quot; onmouseover=&quot;alert(1)">x</a>',
    '<abbr title="&quot;><img src=x onerror=alert(1)>">x</abbr>', '<a href="https://example.com"><img src=x onerror=alert(1)></a>',
    '<<script>alert(1)//<</script>', '<scr<script>ipt>alert(1)</scr</script>ipt>', '<!--><img src=x onerror=alert(1)>-->',
    '<!-- --><img src=x onerror=alert(1)><!-- -->', '<![CDATA[><img src=x onerror=alert(1)>]]>', '<?xml ><img src=x onerror=alert(1)>?>',
    '<style><img src="</style><img src=x onerror=alert(1)>">', '<title><img src="</title><img src=x onerror=alert(1)>">',
    '<textarea><img src="</textarea><img src=x onerror=alert(1)>">', '<template><img src=x onerror=alert(1)></template>',
    '<xmp><img src=x onerror=alert(1)></xmp>', '<noembed><img src=x onerror=alert(1)></noembed>',
    '<select><option><img src=x onerror=alert(1)></option></select>', '<canvas><img src=x onerror=alert(1)></canvas>',
    '<p title="<img src=x onerror=alert(1)>">x</p>', '<span title=\'<img src=x onerror=alert(1)>\'>x</span>',
    '<a href="x" href="javascript:alert(1)">x</a>', '<a href="javascript:alert(1)" href="https://example.com">x</a>',
    '<a href="https://example.com\u0001">x</a>'.replace('\u0001', String.fromCharCode(1)),
    '<a href="' + String.fromCharCode(1) + 'javascript:alert(1)">x</a>', '<a href="java' + String.fromCharCode(0) + 'script:alert(1)">x</a>',
    '<a href="\njavascript:alert(1)">x</a>', '<a href="java\nscript:alert(1)">x</a>', '<a href="javascript&#58;alert(1)">x</a>',
    '$<img src=x onerror=alert(1)>$', '$$<img src=x onerror=alert(1)>$$', '`<img src=x onerror=alert(1)>`',
    '![a" onerror="alert(1)](https://example.com/a.png)', '[a](https://example.com "x" onclick="alert(1)")',
  ];
  for (const attack of attacks) {
    const out = render(attack);
    assertSafeHtml(out, JSON.stringify(attack));
    // (attribute names and values are already checked by assertSafeHtml; the words "onerror=" or
    // "javascript:" may legitimately remain as ESCAPED text, e.g. inside a title or a code span)
    assert.ok(!/<script|<style|<iframe|<svg|<math|<form|<input|<button|<object|<embed|<meta|<link|<base/i.test(out), JSON.stringify(attack) + ' -> ' + out);
  }
});

section('random input with HTML fragments always yields safe output', () => {
  let seed = 0x7a6c3e91;
  const random = () => {  // mulberry32
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const tags = ['b', 'i', 'a', 'img', 'div', 'p', 'span', 'table', 'tr', 'td', 'th', 'ul', 'li', 'details', 'summary', 'pre',
    'script', 'style', 'iframe', 'svg', 'form', 'input', 'font', 'center', 'h1', 'blockquote', 'br', 'hr', 'ruby', 'rt', 'abbr', 'x-y'];
  const attributes = ['href="https://a.example/"', 'href="javascript:x"', 'src="https://a.example/i.png"', 'src=x', 'onerror=alert(1)',
    'onclick="a"', 'style="x"', 'class="y"', 'id=z', 'align=center', 'align="evil"', 'width=10', 'width="1e9"', 'colspan=2', 'open', 'title="t"',
    'title="&quot;"', 'start=3', 'x', '=', '"', "'"];
  const pieces = ['\n', '\n\n', ' ', 'text', '**', '*', '_', '`', '```', '$', '$$', '#', '# ', '> ', '- ', '1. ', '|', '|---|', '[', ']', '(', ')',
    '!', '<', '>', '/', '<!--', '-->', '<!', '<?', '?>', '&', '&amp;', '&#106;', '\x01', 'javascript:', 'https://a.example/'];
  const randomTag = () => {
    const closing = random() < 0.35;
    const name = tags[Math.floor(random() * tags.length)];
    if (closing) return '</' + name + (random() < 0.1 ? ' x' : '') + '>';
    let tag = '<' + name;
    const count = Math.floor(random() * 4);
    for (let k = 0; k < count; k += 1) tag += (random() < 0.9 ? ' ' : '') + attributes[Math.floor(random() * attributes.length)];
    return tag + (random() < 0.1 ? '/' : '') + (random() < 0.97 ? '>' : '');
  };
  for (let i = 0; i < 30000; i += 1) {
    const length = 1 + Math.floor(random() * 24);
    let source = '';
    for (let j = 0; j < length; j += 1) source += random() < 0.55 ? randomTag() : pieces[Math.floor(random() * pieces.length)];
    assertSafeHtml(render(source), JSON.stringify(source));
  }
});

section('hostile or huge input stays fast', () => {
  const inputs = {
    'many unclosed comments': '<!--'.repeat(30000),
    'many unclosed scripts': '<script>'.repeat(30000),
    'many open tags': '<b>'.repeat(30000),
    'many open divs': '<div>'.repeat(30000),
    'many attributes': '<a' + ' x'.repeat(5000) + '>',
    'long attribute value': '<a href="https://a.example/' + 'x'.repeat(100000) + '">x</a>',
    'many lines of tags': ('<div>\n<b>x</b>\n</div>\n').repeat(20000),
    'many less-than signs': '<'.repeat(100000),
    'tag-like noise': '<a '.repeat(30000),
  };
  for (const [name, source] of Object.entries(inputs)) {
    const started = Date.now();
    const out = render(source);
    const elapsed = Date.now() - started;
    assert.ok(elapsed < 3000, `${name} took ${elapsed} ms`);
    if (out.length < 400000) assertSafeHtml(out, name);
  }
});

console.log(`\nAll ${checks} markdown_html_test checks passed.`);
