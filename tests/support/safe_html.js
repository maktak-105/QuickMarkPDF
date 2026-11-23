// Strict validator for the HTML that src/ui/js/markdown.js produces.
//
// The converter only ever emits the elements below, with quoted attribute values that
// cannot contain a quote or angle bracket, and every non-void element is closed in the
// right order. Anything else -- a stray '<' or '>', an unknown element or attribute, an
// on* handler, a URL with another scheme, a class that is not one of the fixed ones, an
// unbalanced tag -- means markup from the source got through.
'use strict';

const assert = require('assert');

const ALIGN_CLASSES = ['align-left', 'align-right', 'align-center'];
const VOID_TAGS = new Set(['br', 'wbr', 'hr', 'img']);
const TAG_PATTERN = /<(\/?)([a-z][a-z0-9]*)((?:\s+[a-z-]+(?:="[^"<>]*")?)*)\s*\/?>/g;
const ATTRIBUTE_PATTERN = /\s+([a-z-]+)(?:="([^"]*)")?/g;

function decode(text) {
  return text.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

const text = () => true;
const digits = (value) => /^\d{1,6}$/.test(value);
const size = (value) => /^\d{1,4}$/.test(value) || /^\d{1,3}%$/.test(value);
const equals = (expected) => (value) => value === expected;
const oneOf = (list) => (value) => list.includes(value);
const alignClass = oneOf(ALIGN_CLASSES);
const href = (value) => /^(https?:|mailto:|#)/i.test(decode(value).replace(/[\x00-\x20]/g, ''));
const src = (value) => /^(https?:|data:image\/(png|jpe?g|gif|webp);base64,)/i.test(decode(value).replace(/[\x00-\x20]/g, ''));
const textAlignStyle = (value) => /^text-align:(left|right|center)$/.test(value);

// element -> allowed attributes (with a check for each value). Elements missing here are not allowed.
const RULES = {};
for (const name of ['p', 'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'del', 'ins', 'mark', 'small', 'sub', 'sup', 'kbd',
  'code', 'tt', 'samp', 'var', 'cite', 'q', 'dfn', 'span', 'ruby', 'rt', 'rp', 'br', 'wbr', 'hr', 'blockquote', 'ul', 'li',
  'dl', 'dt', 'dd', 'summary', 'figure', 'figcaption', 'caption', 'thead', 'tbody', 'tfoot', 'tr']) {
  RULES[name] = {};
}
for (const name of ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table']) RULES[name] = { class: alignClass };
RULES.a = { href, title: text, target: equals('_blank'), rel: equals('noopener noreferrer') };
RULES.img = { alt: text, src, width: size, height: size, title: text, class: alignClass, referrerpolicy: equals('no-referrer') };
RULES.abbr = { title: text };
RULES.ol = { start: digits };
RULES.td = { style: textAlignStyle, class: alignClass, colspan: digits, rowspan: digits };
RULES.th = RULES.td;
RULES.div = { class: oneOf(['math', 'page-break', ...ALIGN_CLASSES]) };
RULES.details = { open: equals('') };
RULES.pre = { class: equals('mermaid') };

function assertSafeHtml(html, label) {
  const fail = (message) => assert.fail(`${message}\n  input: ${label}\n  output: ${html}`);

  const remaining = html.replace(TAG_PATTERN, '');
  if (/[<>]/.test(remaining)) fail('stray angle bracket outside a generated tag');
  if (/\x00/.test(html)) fail('stash marker leaked into the output');

  // Opens and closes must pair up per element: a closing tag never comes before its
  // opening tag and nothing stays open, so no formatting can leak into what follows.
  // (The order of nesting is not checked here: the emphasis markers ** __ * of the
  // Markdown part may overlap -- "**a*b**c*" -- which the browser repairs; the nesting of
  // HTML tags is checked exactly in tests/markdown_html_test.js.)
  const open = {};
  for (const match of html.matchAll(TAG_PATTERN)) {
    const [, closing, name, attributes] = match;
    const rules = RULES[name];
    if (!rules) fail(`element <${name}> is not allowed`);
    if (closing) {
      if (attributes.trim() !== '') fail('closing tag with attributes');
      if (VOID_TAGS.has(name)) fail(`closing tag for the void element <${name}>`);
      if (!open[name]) fail(`</${name}> closes an element that is not open`);
      open[name] -= 1;
      continue;
    }
    const seen = new Set();
    for (const attribute of attributes.matchAll(ATTRIBUTE_PATTERN)) {
      const attributeName = attribute[1];
      const value = attribute[2] === undefined ? '' : attribute[2];
      if (!Object.prototype.hasOwnProperty.call(rules, attributeName)) {
        fail(`attribute ${attributeName} is not allowed on <${name}>`);
      }
      if (seen.has(attributeName)) fail(`attribute ${attributeName} appears twice on <${name}>`);
      seen.add(attributeName);
      if (!rules[attributeName](value)) fail(`unexpected value for ${attributeName} on <${name}>: ${value}`);
      if (/[\x00-\x08\x0b-\x1f\x7f]/.test(value)) fail(`control character in ${attributeName}`);
    }
    if (!VOID_TAGS.has(name)) open[name] = (open[name] || 0) + 1;
  }
  const unclosed = Object.keys(open).filter((name) => open[name] !== 0);
  if (unclosed.length) fail(`unclosed elements: ${unclosed.join(', ')}`);
}

module.exports = { assertSafeHtml, ATTRIBUTE_PATTERN };
